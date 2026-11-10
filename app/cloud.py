"""API-side distributed scheduler. PostgreSQL persists jobs before dispatch."""
import logging
import threading

from app.cloud_store import CloudJobStore

logger = logging.getLogger(__name__)


class CloudDownloadManager:
    def __init__(self, settings, *, store=None, broker=None):
        import redis
        from app.worker import celery_app
        self.settings = settings
        self.store = store or CloudJobStore(settings.database_url, redis_url=settings.redis_url)
        self.redis = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        self.broker = broker or celery_app
        self.closed = threading.Event()
        self.dispatcher = threading.Thread(target=self._dispatch, name="snacky-outbox", daemon=True)
        self.dispatcher.start()

    def owns(self, job_id):
        return True  # Cancellation is durable and shared, not process-local.

    def start(self, url, media_format, quality, photo_index=0, title="", *, tenant_id="default-tenant", user_id=None, batch_id=None):
        job_id = self.store.create_job(
            url,
            media_format,
            quality,
            photo_index,
            title,
            self.settings.max_cloud_jobs,
            tenant_id=tenant_id,
            user_id=user_id,
            batch_id=batch_id,
        )
        self.notify(job_id, tenant_id=tenant_id)
        return job_id

    def notify(self, job_id, *, tenant_id="default-tenant"):
        try:
            self.redis.publish("snacky:tasks", job_id)
            self.redis.publish(f"snacky:tenant:{tenant_id}:tasks", job_id)
        except Exception:
            logger.warning("Progress notification unavailable; snapshots remain in PostgreSQL")

    def _dispatch(self):
        while not self.closed.is_set():
            try:
                self.store.dispatch_due(lambda job_id: self.broker.send_task("snacky.download", args=[job_id], task_id=job_id))
            except Exception:
                logger.warning("Queue dispatch unavailable; durable queued jobs will be retried", exc_info=True)
            self.closed.wait(2)

    def cancel(self, job_id):
        task = self.store.cancel(job_id)
        self.notify(job_id)
        return task

    def shutdown(self):
        self.closed.set()
        self.dispatcher.join(timeout=10)
        # API shutdown does not cancel workers or recover shared jobs.
        self.redis.close()
        self.store.close()
