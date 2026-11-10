"""Media lifecycle management, soft-delete purging, and stuck/poison job reaper."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def purge_expired_media(
    store: Any,
    storage: Any,
    retention_seconds: float = 30 * 86400,
    limit: int = 100,
) -> dict[str, Any]:
    """Find media files soft-deleted past retention window, delete from S3, and hard-delete from database."""
    if not hasattr(store, "find_expired_media"):
        return {"purged_count": 0, "purged_keys": []}

    expired = store.find_expired_media(retention_seconds=retention_seconds, limit=limit)
    purged_keys: list[str] = []
    purged_count = 0

    for item in expired:
        job_id = item["id"]
        storage_key = item.get("storage_key")

        # 1. Delete physical object from S3 storage if key is present
        if storage_key and hasattr(storage, "remove_object"):
            try:
                storage.remove_object(storage_key)
                purged_keys.append(storage_key)
            except Exception as exc:
                logger.warning("Failed to remove S3 object %s during purge: %s", storage_key, exc)

        # 2. Hard delete database record
        try:
            if hasattr(store, "hard_delete_job"):
                store.hard_delete_job(job_id)
                purged_count += 1
        except Exception as exc:
            logger.error("Failed to hard-delete job %s: %s", job_id, exc)

    logger.info("Purged %d expired media records (retention=%ds)", purged_count, retention_seconds)
    return {"purged_count": purged_count, "purged_keys": purged_keys}


def reap_stuck_jobs(
    store: Any,
    max_lease_seconds: float = 300,
    max_attempts: int = 3,
) -> dict[str, int]:
    """Reap orphaned worker leases and quarantine poison jobs exceeding max attempts."""
    if not hasattr(store, "reap_stuck_jobs"):
        return {"reaped": 0, "poison": 0}

    stats = store.reap_stuck_jobs(max_lease_seconds=max_lease_seconds, max_attempts=max_attempts)
    logger.info("Reaped stuck jobs: %d released back to queue, %d quarantined as poison jobs", stats["reaped"], stats["poison"])
    return stats

