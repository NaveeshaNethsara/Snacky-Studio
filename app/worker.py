"""Celery media workers with fencing leases and cooperative shared cancellation."""
import logging
import signal
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from celery import Celery

from app.config import Settings
from app.jobs import DownloadCancelled

logger = logging.getLogger(__name__)
settings = Settings()
celery_app = Celery("snacky", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"visibility_timeout": 21600},
    task_default_queue="media",
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5, "interval_max": 1},
    beat_schedule={
        "snacky-reap-and-purge": {
            "task": "snacky.reap_and_purge",
            "schedule": 60.0,
        },
        "snacky-dispatch-webhooks": {
            "task": "snacky.dispatch_webhooks",
            "schedule": 5.0,
        },
    },
)

# -----------------------------------------------------------------------------
# Graceful Shutdown & Active Lease Registry
# -----------------------------------------------------------------------------
_active_jobs_lock = threading.Lock()
_active_jobs: dict[str, tuple[str, Any, Any]] = {}


def register_active_job(job_id: str, owner: str, store: Any, cancel: Any):
    with _active_jobs_lock:
        _active_jobs[job_id] = (owner, store, cancel)


def unregister_active_job(job_id: str):
    with _active_jobs_lock:
        _active_jobs.pop(job_id, None)


def handle_graceful_shutdown():
    """Triggered on SIGTERM/SIGINT: signals cancellations and releases leases immediately."""
    logger.info("Graceful shutdown initiated: releasing active job leases")
    with _active_jobs_lock:
        jobs_to_release = list(_active_jobs.items())
    for job_id, (owner, store, cancel) in jobs_to_release:
        try:
            if cancel and hasattr(cancel, "event"):
                cancel.event.set()
            if hasattr(store, "release_job_lease"):
                store.release_job_lease(job_id, owner)
                logger.info("Released lease for job %s (owner=%s)", job_id, owner)
        except Exception as exc:
            logger.warning("Error releasing lease during shutdown for job %s: %s", job_id, exc)


def _install_signal_handlers():
    def _sig_handler(signum, frame):
        logger.warning("Received signal %d, initiating graceful worker termination", signum)
        handle_graceful_shutdown()
        raise SystemExit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
    except (ValueError, AttributeError, RuntimeError):
        pass
    try:
        signal.signal(signal.SIGINT, _sig_handler)
    except (ValueError, AttributeError, RuntimeError):
        pass


_install_signal_handlers()


class SharedCancellation:
    def __init__(self, store, job_id, owner, ttl):
        self.store, self.job_id, self.owner, self.ttl = store, job_id, owner, ttl
        self.event, self.stopped = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._refresh, daemon=True)
        self.thread.start()

    def _refresh(self):
        while not self.stopped.wait(1):
            try:
                task = self.store.get(self.job_id)
                if not task or task.get("cancel_requested") or not self.store.heartbeat(self.job_id, self.owner, self.ttl):
                    self.event.set()
                    return
            except Exception:
                # Losing the shared-state connection must not publish unowned output.
                self.event.set()
                return

    def is_set(self):
        return self.event.is_set()

    def wait(self, timeout=None):
        return self.event.wait(timeout)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=5)


def execute_job(job_id, settings, store, storage, *, engine=None, notify=lambda _: None):
    from app.downloader import download_media, ensure_ffmpeg
    owner = str(uuid.uuid4())
    task = store.claim(job_id, owner, settings.job_lease_seconds)
    if not task:
        return  # Already complete, cancelled, or owned by another worker.
    cancel = SharedCancellation(store, job_id, owner, settings.job_lease_seconds)
    last_write, last_status = 0, None

    def progress(**changes):
        nonlocal last_write, last_status
        if cancel.is_set():
            raise DownloadCancelled()
        if time.monotonic() - last_write >= .5 or changes.get("status") != last_status:
            changes.setdefault("error", None)
            snapshot = store.worker_update(job_id, owner, settings.job_lease_seconds, **changes)
            if snapshot is None or snapshot.get("cancel_requested"):
                raise DownloadCancelled()
            last_write, last_status = time.monotonic(), changes.get("status")
            notify(job_id)

    register_active_job(job_id, owner, store, cancel)
    storage_key = None
    job_start = time.monotonic()
    tenant_id = task.get("tenant_id", "default-tenant")

    from app.metrics import JOB_LATENCY_SECONDS, JOBS_TOTAL, WORKER_ACTIVE_JOBS
    WORKER_ACTIVE_JOBS.inc()
    try:
        if engine is None:
            ensure_ffmpeg()
        with tempfile.TemporaryDirectory(prefix=f"snacky-{job_id}-", dir=settings.downloads_dir) as directory:
            folder = Path(directory)
            options = {"photo_index": task.get("photo_index", 0)} if task["format"] in {"photo", "png"} else {}
            result = (engine or download_media)(job_id, task["url"], task["format"], task["quality"], folder, progress, cancel, **options)
            if cancel.is_set():
                raise DownloadCancelled()
            from app.files import resolve_media_file
            output = resolve_media_file(folder, result["filename"])
            published = storage.publish({**task, "storage_attempt": owner}, output)
            storage_key = published["storage_key"]
            snapshot = store.worker_update(job_id, owner, settings.job_lease_seconds, **result, **published,
                status="completed", progress=100, error=None, speed="Done", eta="0s", completed_at=time.time())
            if snapshot is None:
                storage.remove_object(storage_key)
                storage_key = None
            JOB_LATENCY_SECONDS.labels(format=task["format"], status="completed").observe(time.monotonic() - job_start)
            JOBS_TOTAL.labels(status="completed", format=task["format"], tenant_id=tenant_id).inc()
            if hasattr(store, "enqueue_webhook_events"):
                store.enqueue_webhook_events(task.get("tenant_id", "default-tenant"), "job.completed", snapshot or {**task, "status": "completed"})
            if hasattr(store, "increment_tenant_bytes"):
                from app.quotas import get_today_utc
                store.increment_tenant_bytes(task.get("tenant_id", "default-tenant"), get_today_utc(), result.get("size_bytes", 0))
            notify(job_id)
    except DownloadCancelled:
        store.worker_update(job_id, owner, settings.job_lease_seconds, status="cancelled", error=None,
                            speed="—", eta="—", completed_at=time.time())
        JOBS_TOTAL.labels(status="cancelled", format=task["format"], tenant_id=tenant_id).inc()
        if storage_key:
            storage.remove_object(storage_key)
        if hasattr(store, "enqueue_webhook_events"):
            store.enqueue_webhook_events(task.get("tenant_id", "default-tenant"), "job.cancelled", {**task, "status": "cancelled"})
        notify(job_id)
    except Exception as exc:
        logger.exception("Worker failed for job %s", job_id)
        store.worker_update(job_id, owner, settings.job_lease_seconds, status="error", error=str(exc),
                            speed="—", eta="—", completed_at=time.time())
        JOB_LATENCY_SECONDS.labels(format=task["format"], status="error").observe(time.monotonic() - job_start)
        JOBS_TOTAL.labels(status="error", format=task["format"], tenant_id=tenant_id).inc()
        if storage_key:
            storage.remove_object(storage_key)
        if hasattr(store, "enqueue_webhook_events"):
            store.enqueue_webhook_events(task.get("tenant_id", "default-tenant"), "job.failed", {**task, "status": "error", "error": str(exc)})
        notify(job_id)
    finally:
        WORKER_ACTIVE_JOBS.dec()
        unregister_active_job(job_id)
        cancel.close()


@celery_app.task(name="snacky.download", bind=True)
def download_task(self, job_id, correlation_id=None):
    import redis
    from app.cloud_store import CloudJobStore
    from app.logging_conf import correlation_id_ctx
    from app.storage import S3MediaStorage

    c_id = correlation_id or getattr(self.request, "correlation_id", None) or self.request.id
    token = correlation_id_ctx.set(c_id)
    settings = Settings()
    settings.prepare()
    store = CloudJobStore(settings.database_url)
    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)

    def notify(job_id):
        try:
            client.publish("snacky:tasks", job_id)
        except Exception:
            pass  # SQL snapshots remain authoritative.

    try:
        execute_job(job_id, settings, store, S3MediaStorage(settings, store), notify=notify)
    finally:
        store.close()
        client.close()
        correlation_id_ctx.reset(token)


@celery_app.task(name="snacky.dispatch_webhooks")
def dispatch_webhooks_task(limit=20):
    from app.cloud_store import CloudJobStore
    from app.webhooks import dispatch_due_webhooks
    settings = Settings()
    settings.prepare()
    store = CloudJobStore(settings.database_url)
    try:
        return dispatch_due_webhooks(store, limit=limit)
    finally:
        store.close()


@celery_app.task(name="snacky.reap_and_purge")
def reap_and_purge_task(retention_days=30):
    """Periodic maintenance task: reaps stuck jobs, quarantines poison jobs, and purges expired media."""
    from app.cloud_store import CloudJobStore
    from app.lifecycle import purge_expired_media, reap_stuck_jobs
    from app.storage import S3MediaStorage
    settings = Settings()
    settings.prepare()
    store = CloudJobStore(settings.database_url)
    storage = S3MediaStorage(settings, store)
    try:
        reap_res = reap_stuck_jobs(store, max_lease_seconds=300, max_attempts=3)
        purge_res = purge_expired_media(store, storage, retention_seconds=retention_days * 86400)
        return {"reap": reap_res, "purge": purge_res}
    finally:
        store.close()
