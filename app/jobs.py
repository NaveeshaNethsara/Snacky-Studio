"""Bounded workers and durable snapshots; independent of HTTP and yt-dlp."""
import json
import logging
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from app.files import resolve_media_file

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"completed", "error", "cancelled", "interrupted"}


class QueueFullError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created_at REAL, payload TEXT NOT NULL)")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _save(self, db, task):
        db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?, ?)",
                   (task["id"], task["created_at"], json.dumps(task, ensure_ascii=False)))

    def create(self, task):
        with self.lock, self.connection() as db:
            self._save(db, task)

    def get(self, job_id):
        with self.lock, self.connection() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, job_id, **changes):
        with self.lock, self.connection() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            task = json.loads(row[0])
            task.update(changes, updated_at=time.time())
            self._save(db, task)
        return task

    def list(self, limit=50):
        with self.lock, self.connection() as db:
            rows = db.execute("""SELECT payload FROM jobs ORDER BY
                CASE WHEN json_extract(payload, '$.status') IN ('completed', 'error', 'cancelled', 'interrupted') THEN 1 ELSE 0 END,
                created_at DESC LIMIT ?""", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_cursor(self, *, cursor=None, limit=20, **_):
        import base64
        with self.lock, self.connection() as db:
            if cursor:
                try:
                    c_data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                    c_time = float(c_data["created_at"])
                    c_id = str(c_data["id"])
                    rows = db.execute("""
                        SELECT payload FROM jobs
                        WHERE created_at < ? OR (created_at = ? AND id < ?)
                        ORDER BY created_at DESC, id DESC LIMIT ?
                    """, (c_time, c_time, c_id, limit + 1)).fetchall()
                except Exception:
                    rows = db.execute("SELECT payload FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit + 1,)).fetchall()
            else:
                rows = db.execute("SELECT payload FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit + 1,)).fetchall()

        items = [json.loads(row[0]) for row in rows[:limit]]
        has_more = len(rows) > limit
        next_cursor = None
        if has_more and items:
            last = items[-1]
            c_data = {"created_at": last.get("created_at", 0), "id": last.get("id", "")}
            next_cursor = base64.urlsafe_b64encode(json.dumps(c_data).encode()).decode()
        return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

    def recover(self):
        with self.lock, self.connection() as db:
            rows = db.execute("SELECT payload FROM jobs").fetchall()
            for row in rows:
                task = json.loads(row[0])
                if task["status"] not in TERMINAL_STATUSES:
                    task.update(status="interrupted", error="The server stopped before this download finished. Start it again to retry.",
                                completed_at=time.time(), updated_at=time.time())
                    self._save(db, task)


class DownloadManager:
    def __init__(self, store: JobStore, downloads_dir: Path, worker, max_workers=2, max_queued=8, *, recover=True):
        self.store, self.downloads_dir, self.worker = store, downloads_dir, worker
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="snacky-download")
        self.capacity = threading.BoundedSemaphore(max_workers + max_queued)
        self.lock = threading.RLock()
        self.running = {}
        self.closed = False
        if recover:
            self.store.recover()

    def owns(self, job_id):
        with self.lock:
            return str(job_id) in self.running

    def start(self, url, media_format, quality, photo_index=0, title="", *, batch_id=None, **kwargs):
        with self.lock:
            if self.closed or not self.capacity.acquire(blocking=False):
                raise QueueFullError("The download queue is full. Wait for a download to finish and try again.")
            job_id = str(uuid.uuid4())
            now = time.time()
            try:
                task = {
                    "id": job_id, "url": url, "format": media_format, "quality": quality, "photo_index": photo_index,
                    "status": "queued", "progress": 0, "downloaded_bytes": 0, "total_bytes": 0,
                    "speed": "—", "eta": "—", "filename": None, "title": title, "thumbnail": "",
                    "error": None, "created_at": now, "updated_at": now, "completed_at": None,
                }
                if batch_id:
                    task["batch_id"] = batch_id
                self.store.create(task)
                cancel = threading.Event()
                future = self.executor.submit(self._run, job_id, url, media_format, quality, cancel, photo_index)
                self.running[job_id] = (future, cancel)
                future.add_done_callback(lambda _: self._release(job_id))
            except Exception:
                self.capacity.release()
                raise
            return job_id

    def _release(self, job_id):
        with self.lock:
            self.running.pop(job_id, None)
            self.capacity.release()

    def _run(self, job_id, url, media_format, quality, cancel, photo_index):
        last_write, last_status = 0, None

        def progress(**changes):
            nonlocal last_write, last_status
            if cancel.is_set():
                raise DownloadCancelled()
            now = time.monotonic()
            status = changes.get("status")
            if now - last_write >= 0.5 or status != last_status:
                changes.setdefault("error", None)
                self.store.update(job_id, **changes)
                last_write, last_status = now, status

        try:
            progress(status="fetching_info")
            options = {"photo_index": photo_index} if media_format in {"photo", "png"} else {}
            result = self.worker(job_id, url, media_format, quality, self.downloads_dir, progress, cancel, **options)
            resolve_media_file(self.downloads_dir, result["filename"])
            # A finished, published file wins over a late cancellation request.
            self.store.update(job_id, **result, status="completed", progress=100,
                              speed="Done", eta="0s", error=None, completed_at=time.time())
        except DownloadCancelled:
            self.store.update(job_id, status="cancelled", speed="—", eta="—", completed_at=time.time())
        except Exception as exc:
            logger.exception("Download %s failed", job_id)
            try:
                from app.downloader import sanitize_error_message
                clean_err = sanitize_error_message(exc, url)
            except Exception:
                clean_err = str(exc)
            self.store.update(job_id, status="cancelled" if cancel.is_set() else "error",
                              error=None if cancel.is_set() else clean_err, speed="—", eta="—", completed_at=time.time())

    def cancel(self, job_id):
        with self.lock:
            task = self.store.get(job_id)
            if not task:
                raise KeyError(job_id)
            if task["status"] in TERMINAL_STATUSES:
                return task
            entry = self.running.get(job_id)
            if entry:
                future, cancel = entry
                cancel.set()
                if future.cancel():
                    return self.store.update(job_id, status="cancelled", completed_at=time.time())
                # The worker may have finished while cancellation was requested.
                with self.store.lock:
                    task = self.store.get(job_id)
                    if task["status"] not in TERMINAL_STATUSES:
                        task = self.store.update(job_id, status="cancelling")
            return task

    def shutdown(self):
        with self.lock:
            self.closed = True
            for job_id in list(self.running):
                self.cancel(job_id)
        self.executor.shutdown(wait=True, cancel_futures=True)
