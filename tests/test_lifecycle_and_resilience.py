"""Phase 5 Tests: Data lifecycle, soft deletes, stuck/poison job reaper,
Redis graceful degradation, and backup restore verification.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from app.cloud_store import CloudJobStore
from app.events import TaskEventHub
from app.lifecycle import purge_expired_media, reap_stuck_jobs
from app.worker import handle_graceful_shutdown, register_active_job, unregister_active_job
from scripts.backup import create_encrypted_backup
from scripts.verify_restore import verify_and_restore


@pytest.fixture
def test_cloud_store(tmp_path):
    """Ephemeral SQLite database for testing CloudJobStore methods with isolation."""
    db_file = tmp_path / "test_cloud.db"
    db_url = f"sqlite:///{db_file}"
    store = CloudJobStore(db_url, initialize=True)
    try:
        yield store
    finally:
        store.close()


def test_soft_delete_and_lifecycle_purge(test_cloud_store):
    store = test_cloud_store

    # 1. Create and complete a job
    job_id = store.create_job(
        "https://example.com/video.mp4",
        "mp4",
        "best",
        0,
        "Test Video",
        100,
        tenant_id="tenant-alpha",
    )
    owner = "worker-1"
    store.claim(job_id, owner, 120)
    store.worker_update(
        job_id,
        owner,
        120,
        status="completed",
        filename="video.mp4",
        storage_key="media/tenant-alpha/job-1/video.mp4",
        size_bytes=1024,
        completed_at=time.time(),
    )

    # 2. Verify job is in completed list
    completed_before = store.completed(tenant_id="tenant-alpha")
    assert any(j["id"] == job_id for j in completed_before)

    # 3. Soft delete the job
    assert store.soft_delete_job(job_id, tenant_id="tenant-alpha") is True

    # 4. Verify job is excluded from completed() and find_file()
    completed_after = store.completed(tenant_id="tenant-alpha")
    assert not any(j["id"] == job_id for j in completed_after)
    assert store.find_file("video.mp4", tenant_id="tenant-alpha") is None

    # 5. Query expired media (with 0s retention)
    expired = store.find_expired_media(retention_seconds=0)
    assert len(expired) >= 1
    assert any(e["id"] == job_id for e in expired)

    # 6. Execute purge_expired_media
    mock_storage = MagicMock()
    purge_stats = purge_expired_media(store, mock_storage, retention_seconds=0)
    assert purge_stats["purged_count"] >= 1
    assert "media/tenant-alpha/job-1/video.mp4" in purge_stats["purged_keys"]
    mock_storage.remove_object.assert_called_with("media/tenant-alpha/job-1/video.mp4")

    # 7. Verify job is hard-deleted from database
    assert store.get(job_id, tenant_id="tenant-alpha") is None


def test_stuck_job_reaper_and_poison_quarantine(test_cloud_store):
    store = test_cloud_store

    # 1. Enqueue job and set expired lease
    job1_id = store.create_job(
        "https://example.com/video1.mp4",
        "mp4",
        "best",
        0,
        "Stuck Vid",
        100,
        tenant_id="tenant-alpha",
    )
    # Claim and artificially expire lease
    store.claim(job1_id, "worker-crash-1", -10)

    # Reap: attempt_count = 1 < 3 -> should release back to outbox
    stats1 = reap_stuck_jobs(store, max_lease_seconds=300, max_attempts=3)
    assert stats1["reaped"] == 1
    assert stats1["poison"] == 0

    reaped_job = store.get(job1_id)
    assert reaped_job["status"] == "queued"

    # Also verify in database that lease_owner was cleared
    with store.engine.connect() as conn:
        from sqlalchemy import select
        from app.cloud_store import jobs
        row = conn.execute(select(jobs).where(jobs.c.id == job1_id)).mappings().first()
        assert row["lease_owner"] is None
        assert row["lease_until"] == 0

    # 2. Poison job test: claim 2 more times to reach attempt_count = 3
    store.claim(job1_id, "worker-crash-2", -10)
    store.claim(job1_id, "worker-crash-3", -10)

    # Reap again: attempt_count >= 3 -> should quarantine as poison job
    stats2 = reap_stuck_jobs(store, max_lease_seconds=300, max_attempts=3)
    assert stats2["poison"] == 1

    quarantined = store.get(job1_id)
    assert quarantined["status"] == "error"
    assert "Quarantined as poison job" in quarantined["error"]

    with store.engine.connect() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job1_id)).mappings().first()
        assert row["lease_owner"] is None
        assert row["status"] == "error"


def test_worker_graceful_shutdown_release():
    mock_store = MagicMock()
    mock_cancel = MagicMock()
    mock_cancel.event = MagicMock()

    register_active_job("job-abc-123", "worker-replica-1", mock_store, mock_cancel)

    handle_graceful_shutdown()

    mock_cancel.event.set.assert_called_once()
    mock_store.release_job_lease.assert_called_once_with("job-abc-123", "worker-replica-1")

    unregister_active_job("job-abc-123")


@pytest.mark.asyncio
async def test_redis_graceful_degradation_to_sql(test_cloud_store):
    """Proves TaskEventHub falls back cleanly to SQL polling when Redis is unavailable."""
    mock_manager = MagicMock()
    mock_manager.store = test_cloud_store

    mock_settings = MagicMock()
    mock_settings.mode = "cloud"
    mock_settings.redis_url = "redis://invalid-host-unreachable:6379/0"

    hub = TaskEventHub(mock_manager, mock_settings)
    await hub.start()

    # Wait for at least one SQL refresh cycle
    await asyncio.sleep(0.6)

    # Snapshot should have refreshed from SQL store without crashing
    assert "tasks" in hub.snapshot
    assert hub.serial >= 1

    await hub.close()


def test_automated_encrypted_backup_and_restore(tmp_path):
    """Test full cycle of encrypted database backup and verification."""
    db_file = tmp_path / "source.db"
    db_url = f"sqlite:///{db_file}"
    store = CloudJobStore(db_url, initialize=True)
    store.create_job(
        "https://example.com/test.mp4",
        "mp4",
        "best",
        0,
        "Backup Test",
        100,
        tenant_id="tenant-backup",
    )
    store.close()

    backup_dir = tmp_path / "backups"
    passphrase = "test_super_secret_encryption_key_2026"

    # 1. Create encrypted backup
    encrypted_file = create_encrypted_backup(
        database_url=db_url,
        output_dir=backup_dir,
        encryption_key=passphrase,
    )
    assert encrypted_file.exists()
    assert encrypted_file.stat().st_size > 0

    # 2. Verify and restore (offline decrypt + checksum verification)
    report = verify_and_restore(
        backup_file=encrypted_file,
        encryption_key=passphrase,
        verify_in_db=False,
    )

    assert report["encryption_verified"] is True
    assert report["rto_sla_met"] is True
    assert report["table_counts"]["media_jobs"] == 1
    assert report["table_counts"]["tenants"] >= 1
