import time
import pytest
from unittest.mock import MagicMock
from app.cache import MetadataCache
from app.cloud_store import CloudJobStore, metadata, jobs, tenants, abuse_controls
from sqlalchemy import create_engine


def test_metadata_cache_fallback_when_no_redis():
    """Verify MetadataCache handles None gracefully without raising exceptions."""
    cache = MetadataCache(redis_url=None)
    assert cache.get_file("tenant-1", "video.mp4") is None
    cache.set_file("tenant-1", "video.mp4", {"id": "1"}, ttl=60)
    cache.invalidate_file("tenant-1", "video.mp4")

    assert cache.get_tenant("tenant-1") is None
    cache.set_tenant("tenant-1", {"name": "Test"}, ttl=60)
    cache.invalidate_tenant("tenant-1")

    assert cache.get_abuse_controls() is None
    cache.set_abuse_controls({"kill_switch_enabled": False}, ttl=60)
    cache.invalidate_abuse_controls()
    cache.close()


def test_metadata_cache_operations_with_mock():
    """Verify MetadataCache formats keys and serialization correctly."""
    cache = MetadataCache(redis_url=None)
    mock_redis = MagicMock()
    cache._client = mock_redis

    # 1. File lookup
    mock_redis.get.return_value = '{"id": "job-1", "filename": "test.mp4"}'
    res = cache.get_file("t-1", "test.mp4")
    assert res == {"id": "job-1", "filename": "test.mp4"}
    mock_redis.get.assert_called_with("snacky:cache:file:t-1:test.mp4")

    cache.set_file("t-1", "test.mp4", {"id": "job-1"}, ttl=300)
    mock_redis.set.assert_called_with("snacky:cache:file:t-1:test.mp4", '{"id": "job-1"}', ex=300)

    cache.invalidate_file("t-1", "test.mp4")
    mock_redis.delete.assert_called_with("snacky:cache:file:t-1:test.mp4")

    # 2. Tenant lookup
    mock_redis.get.return_value = '{"id": "t-1", "tier": "pro"}'
    tenant = cache.get_tenant("t-1")
    assert tenant == {"id": "t-1", "tier": "pro"}
    mock_redis.get.assert_called_with("snacky:cache:tenant:t-1")

    cache.set_tenant("t-1", {"id": "t-1"}, ttl=60)
    mock_redis.set.assert_called_with("snacky:cache:tenant:t-1", '{"id": "t-1"}', ex=60)

    cache.invalidate_tenant("t-1")
    mock_redis.delete.assert_called_with("snacky:cache:tenant:t-1")

    # 3. Abuse controls
    mock_redis.get.return_value = '{"kill_switch_enabled": true}'
    controls = cache.get_abuse_controls()
    assert controls["kill_switch_enabled"] is True
    mock_redis.get.assert_called_with("snacky:cache:abuse_controls")

    cache.set_abuse_controls({"kill_switch_enabled": True}, ttl=60)
    mock_redis.set.assert_called_with("snacky:cache:abuse_controls", '{"kill_switch_enabled": true}', ex=60)

    cache.invalidate_abuse_controls()
    mock_redis.delete.assert_called_with("snacky:cache:abuse_controls")


def test_promoted_column_store_integration(tmp_path):
    """Verify that CloudJobStore stores filename in indexed column and finds it."""
    db_file = tmp_path / "test_perf.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    metadata.create_all(engine)
    engine.dispose()

    store = CloudJobStore(db_url, redis_url=None)

    # 1. Test tenant creation
    t = store.create_tenant("Perf Test Tenant", slug="perf-tenant")
    tenant_id = t["id"]

    # 2. Insert job and mark completed with filename
    job_id = store.create_job(
        url="https://instagram.com/p/test123",
        media_format="mp4",
        quality="1080",
        photo_index=0,
        title="Sunset Video",
        capacity=100,
        tenant_id=tenant_id,
    )
    assert job_id is not None

    # Worker claims and updates with filename
    assert store.claim(job_id, "worker-test", 120)
    store.worker_update(job_id, "worker-test", 120, status="completed", filename="sunset_video.mp4")

    # Verify column was populated on write
    with store.engine.connect() as conn:
        row = conn.execute(jobs.select().where(jobs.c.id == job_id)).mappings().first()
        assert row["filename"] == "sunset_video.mp4"
        assert row["deleted_at"] is None

    # 3. Test find_file using promoted column
    found = store.find_file("sunset_video.mp4", tenant_id=tenant_id)
    assert found is not None
    assert found["id"] == job_id

    # 4. Test soft-delete updates deleted_at column
    del_id = store.soft_delete_by_filename("sunset_video.mp4", tenant_id=tenant_id)
    assert del_id == job_id

    # find_file should now return None because row is soft-deleted
    assert store.find_file("sunset_video.mp4", tenant_id=tenant_id) is None

    # Verify deleted_at column in DB is populated
    with engine.connect() as conn:
        row = conn.execute(jobs.select().where(jobs.c.id == job_id)).mappings().first()
        assert row["deleted_at"] is not None

    store.close()
