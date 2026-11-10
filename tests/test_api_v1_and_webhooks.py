"""Enterprise unit and integration tests for Phase 3:
- Versioned API (/api/v1)
- RFC 9457 Problem Details
- Scoped API Keys (snk_live_...)
- Idempotency-Key deduplication
- SSRF-Hardened Webhooks & HMAC signing
- Media Source Plugin Registry
- TikTok retry sleep safety
"""
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.downloader import _safe_retry_sleep
from app.main import create_app
from app.plugins import (
    BaseMediaPlugin,
    FacebookPlugin,
    GenericWebMediaPlugin,
    InstagramPlugin,
    MediaPluginRegistry,
    TikTokPlugin,
    TwitterPlugin,
    YouTubePlugin,
    get_default_registry,
)
from app.webhooks import (
    WebhookSSRFError,
    calculate_backoff,
    sign_payload,
    validate_webhook_url,
)


# -----------------------------------------------------------------------------
# 1. TikTok & Downloader Retry Sleep Bug Verification
# -----------------------------------------------------------------------------
def test_safe_retry_sleep_handles_all_argument_patterns():
    # yt-dlp RetryManager calls sleep_func(n=count - 1)
    assert _safe_retry_sleep(n=0) >= 1
    assert _safe_retry_sleep(n=2) == 4
    assert _safe_retry_sleep(n=10) == 10  # Max clamp

    # Legacy positional argument call
    assert _safe_retry_sleep(3) == 6

    # Attempt kwarg
    assert _safe_retry_sleep(attempt=2) >= 1

    # Empty or malformed kwargs
    assert _safe_retry_sleep() >= 1
    assert _safe_retry_sleep(n="invalid") >= 1


# -----------------------------------------------------------------------------
# 2. Media Source Plugin Architecture Tests
# -----------------------------------------------------------------------------
def test_plugin_registry_routing():
    reg = get_default_registry()

    yt_plugin = reg.get_plugin("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert isinstance(yt_plugin, YouTubePlugin)

    tt_plugin = reg.get_plugin("https://www.tiktok.com/@creator/video/123456789")
    assert isinstance(tt_plugin, TikTokPlugin)

    ig_plugin = reg.get_plugin("https://www.instagram.com/reel/Cx12345")
    assert isinstance(ig_plugin, InstagramPlugin)

    fb_plugin = reg.get_plugin("https://www.facebook.com/reel/987654321")
    assert isinstance(fb_plugin, FacebookPlugin)

    x_plugin = reg.get_plugin("https://twitter.com/user/status/112233")
    assert isinstance(x_plugin, TwitterPlugin)

    generic_plugin = reg.get_plugin("https://example.com/video.mp4")
    assert isinstance(generic_plugin, GenericWebMediaPlugin)


def test_custom_plugin_registration():
    class VimeoPlugin(BaseMediaPlugin):
        name = "Vimeo"
        platform_id = "vimeo"
        badge = "Vimeo"
        supported_domains = ("vimeo.com",)

        def extract_info(self, url: str):
            return {"title": "Vimeo Sample", "url": url}

        def download(self, *args, **kwargs):
            return {"filename": "vimeo.mp4"}

    custom_reg = MediaPluginRegistry()
    custom_reg.register(VimeoPlugin())
    custom_reg.register(GenericWebMediaPlugin(), fallback=True)

    plugin = custom_reg.get_plugin("https://vimeo.com/76979871")
    assert isinstance(plugin, VimeoPlugin)
    assert plugin.extract_info("https://vimeo.com/76979871")["title"] == "Vimeo Sample"


# -----------------------------------------------------------------------------
# 3. Webhook Security: SSRF Validation & Replay Signing Tests
# -----------------------------------------------------------------------------
def test_webhook_ssrf_rejects_forbidden_targets():
    # Loopback
    with pytest.raises(WebhookSSRFError):
        validate_webhook_url("http://127.0.0.1:8080/webhook")
    with pytest.raises(WebhookSSRFError):
        validate_webhook_url("http://localhost/webhook")

    # Cloud metadata service (169.254.169.254)
    with pytest.raises(WebhookSSRFError):
        validate_webhook_url("http://169.254.169.254/latest/meta-data")

    # Non-HTTP scheme
    with pytest.raises(WebhookSSRFError):
        validate_webhook_url("ftp://example.com/webhook")


def test_webhook_hmac_signature_and_backoff():
    secret = "test-secret-key-123"
    timestamp = 1700000000.0
    payload = b'{"event":"job.completed","data":{"id":"job-1"}}'

    sig1 = sign_payload(secret, timestamp, payload)
    assert isinstance(sig1, str)
    assert len(sig1) == 64

    # Timestamp alteration changes signature (replay attack defense)
    sig2 = sign_payload(secret, timestamp + 10, payload)
    assert sig1 != sig2

    # Backoff with jitter increases with attempts
    b1 = calculate_backoff(1)
    b3 = calculate_backoff(3)
    assert b1 < b3
    assert b3 <= 3600.0


# -----------------------------------------------------------------------------
# 4. API v1 Integration Tests: RFC 9457, Idempotency & Auth Scopes
# -----------------------------------------------------------------------------
@pytest.fixture
def mock_cloud_client(tmp_path):
    settings = Settings(
        mode="cloud",
        database_url="postgresql+psycopg://unused",
        session_secret="cloud-secret-test-key-32-bytes-long!",
        data_dir=tmp_path / "data",
        downloads_dir=tmp_path / "downloads",
    )
    app = create_app(settings)

    # In-memory mock store implementing CloudJobStore interface
    class InMemoryCloudStore:
        def __init__(self):
            self.jobs = {}
            self.api_keys = {}
            self.idempotency = {}
            self.webhooks = {}
            self.deliveries = []

        def get(self, job_id, *, tenant_id=None):
            return self.jobs.get(job_id)

        def list_cursor(self, *, tenant_id="default-tenant", cursor=None, limit=20):
            items = list(self.jobs.values())
            return {"items": items[:limit], "next_cursor": None, "has_more": len(items) > limit}

        def create_api_key(self, tenant_id, user_id, name, scopes, expires_at=None):
            raw_key = f"snk_live_{name}_secret"
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            record = {
                "id": f"key-{name}",
                "tenant_id": tenant_id,
                "user_id": user_id,
                "name": name,
                "key_prefix": raw_key[:12],
                "key_hash": key_hash,
                "scopes": scopes,
                "expires_at": expires_at,
                "is_revoked": False,
            }
            self.api_keys[key_hash] = record
            return {"id": record["id"], "key": raw_key, "name": name, "scopes": scopes}

        def get_api_key_by_hash(self, key_hash):
            return self.api_keys.get(key_hash)

        def touch_api_key(self, key_id):
            pass

        def revoke_api_key(self, tenant_id, key_id):
            for k, rec in self.api_keys.items():
                if rec["id"] == key_id:
                    rec["is_revoked"] = True
                    return True
            return False

        def get_idempotency_key(self, tenant_id, key):
            return self.idempotency.get(f"{tenant_id}:{key}")

        def save_idempotency_key(self, tenant_id, key, request_hash, response_code, response_body, ttl=86400):
            self.idempotency[f"{tenant_id}:{key}"] = {
                "request_hash": request_hash,
                "response_code": response_code,
                "response_body": response_body,
            }

        def enqueue_webhook_events(self, tenant_id, event_name, payload):
            return 1

    class MockManager:
        def __init__(self, store):
            self.store = store
            self.downloads_dir = tmp_path / "downloads"

        def create(self, url, media_format, quality, photo_index=0, *, tenant_id="default-tenant", user_id=None):
            job_id = f"job-{len(self.store.jobs) + 1}"
            task = {
                "id": job_id,
                "tenant_id": tenant_id,
                "url": url,
                "format": media_format,
                "quality": quality,
                "status": "queued",
                "created_at": time.time(),
            }
            self.store.jobs[job_id] = task
            return job_id

        def get(self, job_id, *, tenant_id=None):
            return self.store.get(job_id, tenant_id=tenant_id)

        def cancel(self, job_id, *, tenant_id=None):
            task = self.store.get(job_id, tenant_id=tenant_id)
            if task:
                task["status"] = "cancelled"
            return task

        def shutdown(self):
            pass

    mock_store = InMemoryCloudStore()
    app.state.jobs = MockManager(mock_store)

    return TestClient(app), mock_store


def test_rfc9457_error_on_unauthenticated_v1(mock_cloud_client):
    client, _ = mock_cloud_client
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    data = resp.json()
    assert data["status"] == 401
    assert data["title"] == "Unauthorized"
    assert "instance" in data


def test_api_key_auth_and_scoping(mock_cloud_client):
    client, store = mock_cloud_client

    # Create write-only key and read-only key
    write_key = store.create_api_key("tenant-1", "user-1", "writer", ["jobs:write"])
    read_key = store.create_api_key("tenant-1", "user-2", "reader", ["jobs:read"])

    # 1. Read-only key trying to create job fails with 403 Problem Detail
    resp = client.post(
        "/api/v1/jobs",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "format": "mp4", "quality": "best"},
        headers={"Authorization": f"Bearer {read_key['key']}"},
    )
    assert resp.status_code == 403
    assert resp.headers["content-type"] == "application/problem+json"
    assert "jobs:write" in resp.json()["detail"]

    # 2. Write key creating job succeeds with 201 Created
    resp = client.post(
        "/api/v1/jobs",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "format": "mp4", "quality": "best"},
        headers={"X-API-Key": write_key["key"]},
    )
    assert resp.status_code == 201
    job = resp.json()
    assert job["id"] == "job-1"

    # 3. Read key reading job succeeds
    resp = client.get(
        f"/api/v1/jobs/{job['id']}",
        headers={"Authorization": f"Bearer {read_key['key']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://youtu.be/dQw4w9WgXcQ"


def test_idempotency_key_deduplication(mock_cloud_client):
    client, store = mock_cloud_client
    admin_key = store.create_api_key("tenant-1", "user-1", "admin", ["*"])

    payload = {"url": "https://youtu.be/dQw4w9WgXcQ", "format": "mp4", "quality": "best"}
    headers = {
        "Authorization": f"Bearer {admin_key['key']}",
        "Idempotency-Key": "idemp-unique-12345",
    }

    # First request: Created
    resp1 = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert resp1.status_code == 201
    job_id = resp1.json()["id"]

    # Second request: Cached response returned with HIT-IDEMPOTENT header
    resp2 = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert resp2.status_code == 201
    assert resp2.headers.get("X-Cache") == "HIT-IDEMPOTENT"
    assert resp2.json()["id"] == job_id

    # Third request with SAME idempotency key but DIFFERENT payload returns 409 Conflict Problem Detail
    conflict_payload = {"url": "https://youtu.be/other_video", "format": "mp4", "quality": "best"}
    resp3 = client.post("/api/v1/jobs", json=conflict_payload, headers=headers)
    assert resp3.status_code == 409
    assert resp3.headers["content-type"] == "application/problem+json"
    assert resp3.json()["title"] == "Idempotency Conflict"

