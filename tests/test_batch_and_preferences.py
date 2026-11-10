"""Phase 8 Tests: Batch URL processing, individual status tracking,
user preferences persistence, and localized multi-field library queries.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import Settings
from app.cloud_store import CloudJobStore, metadata, user_preferences
from app.main import create_app


@pytest.fixture
def test_app(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    data_dir = root / "data"
    data_dir.mkdir()
    downloads_dir = root / "downloads"
    downloads_dir.mkdir()

    settings = Settings(
        mode="local",
        data_dir=data_dir,
        downloads_dir=downloads_dir,
    )

    def mock_worker(job_id, url, media_format, quality, directory, progress, cancel, **options):
        progress(status="downloading", progress=50)
        filename = f"media_{job_id}.{media_format}"
        (directory / filename).write_bytes(b"test fixture binary")
        return {"filename": filename}

    app = create_app(settings, worker=mock_worker)
    return app, settings


def test_batch_download_flow_local(test_app):
    app, settings = test_app
    with TestClient(app, base_url="http://localhost:8000") as client:
        # 1. Submit empty batch -> 400
        res_empty = client.post("/api/batch", json={"urls": []})
        assert res_empty.status_code == 400

        # 2. Submit valid batch of 2 URLs
        batch_payload = {
            "urls": [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.youtube.com/watch?v=9bZkp7q19f0",
            ],
            "format": "mp4",
            "quality": "best",
        }
        res = client.post("/api/batch", json=batch_payload)
        assert res.status_code == 200
        data = res.json()
        assert "batch_id" in data
        assert data["total"] == 2
        assert data["submitted"] == 2
        assert len(data["tasks"]) == 2
        batch_id = data["batch_id"]

        # Verify tasks have batch_id attached
        for task in data["tasks"]:
            assert task.get("batch_id") == batch_id

        # 3. Query batch status
        res_status = client.get(f"/api/batch/{batch_id}")
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert status_data["batch_id"] == batch_id
        assert status_data["total"] == 2
        assert len(status_data["tasks"]) == 2


def test_user_preferences_local_crud(test_app):
    app, settings = test_app
    with TestClient(app, base_url="http://localhost:8000") as client:
        # 1. Fetch default preferences
        res = client.get("/api/preferences")
        assert res.status_code == 200
        defaults = res.json()
        assert defaults["default_format"] == "mp4"
        assert defaults["theme"] == "system"
        assert defaults["language"] == "en"

        # 2. Update preferences
        update_payload = {
            "default_format": "mp3",
            "default_quality": "best",
            "default_audio_bitrate": "320",
            "theme": "dark",
            "language": "es",
            "auto_download": True,
        }
        res_put = client.put("/api/preferences", json=update_payload)
        assert res_put.status_code == 200
        updated = res_put.json()
        assert updated["default_format"] == "mp3"
        assert updated["theme"] == "dark"
        assert updated["language"] == "es"

        # 3. Verify persistence
        res_get = client.get("/api/preferences")
        assert res_get.status_code == 200
        persisted = res_get.json()
        assert persisted["default_format"] == "mp3"
        assert persisted["theme"] == "dark"
        assert persisted["language"] == "es"

        # Check local file was created
        pref_file = settings.data_dir / "preferences.json"
        assert pref_file.is_file()
        file_data = json.loads(pref_file.read_text(encoding="utf-8"))
        assert file_data["language"] == "es"


def test_cloud_store_user_preferences_integration(tmp_path):
    db_file = tmp_path / "test_cloud_pref.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    metadata.create_all(engine)
    engine.dispose()

    store = CloudJobStore(db_url, redis_url=None)

    # 1. Create tenant and user
    tenant = store.create_tenant("Preference Org", slug="pref-org")
    tenant_id = tenant["id"]
    user = store.create_user(tenant_id, "user@pref.test", "hashed_password", role="member")
    user_id = user["id"]

    # 2. Get unconfigured preferences -> None
    assert store.get_user_preferences(user_id, tenant_id) is None

    # 3. Save preferences
    custom_prefs = {
        "default_format": "photos",
        "default_quality": "best",
        "default_audio_bitrate": "256",
        "theme": "light",
        "language": "es",
        "auto_download": False,
    }
    saved = store.set_user_preferences(user_id, tenant_id, custom_prefs)
    assert saved == custom_prefs

    # 4. Fetch saved preferences
    loaded = store.get_user_preferences(user_id, tenant_id)
    assert loaded == custom_prefs

    # 5. Update preferences
    custom_prefs["theme"] = "dark"
    store.set_user_preferences(user_id, tenant_id, custom_prefs)
    assert store.get_user_preferences(user_id, tenant_id)["theme"] == "dark"

    store.close()

