"""Deterministic regression tests; no external services or test packages needed."""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import quote, unquote
from uuid import uuid4

from pydantic import ValidationError

from app.config import Settings
from app.downloader import detect_platform, download_media, extract_video_info, format_selector
from app.files import build_content_disposition, resolve_media_file
from app.jobs import DownloadCancelled, DownloadManager, JobStore, QueueFullError
from app.main import create_app
from app.schemas import DownloadRequest, InfoRequest


async def http(app, path, method="GET", body=None, headers=None):
    from urllib.parse import urlsplit
    parsed = urlsplit(path)
    payload = json.dumps(body).encode() if body is not None else b""
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": unquote(parsed.path), "raw_path": parsed.path.encode(),
             "query_string": parsed.query.encode(), "root_path": "", "client": ("127.0.0.1", 1234),
             "server": ("127.0.0.1", 8000),
             "headers": [(b"host", b"127.0.0.1:8000"), (b"content-type", b"application/json")] + (headers or [])}
    sent = False
    messages = []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    head = next(item for item in messages if item["type"] == "http.response.start")
    content = b"".join(item.get("body", b"") for item in messages)
    return head["status"], dict(head["headers"]), content


class BoundaryTests(unittest.TestCase):
    def test_unicode_header_is_ascii_and_preserves_utf8(self):
        name = 'සිංහල தமிழ் العربية 日本語 🎵 "track".mp3'
        header = build_content_disposition(name)
        header.encode("ascii")
        self.assertEqual(unquote(header.split("UTF-8''")[1]), name)
        self.assertNotIn('\r', header)
        self.assertNotIn('\n', header)

    def test_traversal_and_nonmedia_files_cannot_be_served(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "song.mp3").write_bytes(b"audio")
            (root / "secret.txt").write_text("secret")
            self.assertEqual(resolve_media_file(root, "song.mp3"), root / "song.mp3")
            for filename in ["../song.mp3", "..\\song.mp3", "song.mp3:stream", "secret.txt", ".", ""]:
                with self.subTest(filename=filename), self.assertRaises(FileNotFoundError):
                    resolve_media_file(root, filename)

    def test_url_validation_and_format_validation(self):
        for url in ["file:///secret", "ftp://example.com/test", "http://localhost/test", "http://127.0.0.1/test", "http://[::1]/test", "https://name:pass@example.com/test"]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                InfoRequest(url=url)
        for fields in [{"format": "exe"}, {"quality": "720]/best"}, {"format": "mp3", "quality": "720"}]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                DownloadRequest(url="https://youtu.be/example", **fields)
        self.assertEqual(DownloadRequest(url="https://youtu.be/example", format="mp3").quality, "320")

    def test_platform_detection_uses_hostname(self):
        self.assertEqual(detect_platform("https://www.youtube.com/watch?v=test")["id"], "youtube")
        self.assertEqual(detect_platform("https://example.com/?url=youtube.com")["id"], "generic")
        self.assertEqual(detect_platform("https://notyoutube.com/test")["id"], "generic")

    def test_quality_options_only_offer_actual_resolutions(self):
        fake = MagicMock()
        fake.__enter__.return_value.extract_info.return_value = {"title": "Example", "formats": [{"height": 1080, "vcodec": "h264"}]}
        with patch("app.downloader.yt_dlp.YoutubeDL", return_value=fake):
            info = extract_video_info("https://youtu.be/test")
        self.assertEqual([option["id"] for option in info["qualities"]], ["best", "1080"])

    def test_resolution_fallback_never_uses_unrestricted_best(self):
        choices = format_selector("720").split("/")
        self.assertTrue(all("[height<=?720]" in choice for choice in choices))

    def test_missing_conversion_output_is_an_error(self):
        fake = MagicMock()
        fake.__enter__.return_value.extract_info.return_value = {"title": "No output"}
        with tempfile.TemporaryDirectory() as directory, patch("app.downloader.ensure_ffmpeg"), patch("app.downloader.yt_dlp.YoutubeDL", return_value=fake):
            job_id = str(uuid4())
            with self.assertRaisesRegex(RuntimeError, "complete file"):
                download_media(job_id, "https://youtu.be/test", "mp4", "best", Path(directory), lambda **changes: None, threading.Event())
            self.assertFalse((Path(directory) / ".work" / job_id).exists())

    def test_cancelled_conversion_cleans_its_temporary_directory(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as directory, patch("app.downloader.ensure_ffmpeg"):
            job_id = str(uuid4())
            with self.assertRaises(DownloadCancelled):
                download_media(job_id, "https://youtu.be/test", "mp3", "320", Path(directory), lambda **changes: None, cancel)
            self.assertFalse((Path(directory) / ".work" / job_id).exists())


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root / "jobs.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def wait_status(self, job_id, status):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            task = self.store.get(job_id)
            if task["status"] == status:
                return task
            time.sleep(.01)
        self.fail(f"Did not reach {status}: {task}")

    def test_queue_limit_and_cancel_queued_job(self):
        gate = threading.Event()
        entered = threading.Event()

        def worker(job_id, url, media_format, quality, directory, progress, cancel):
            entered.set()
            gate.wait(3)
            if cancel.is_set():
                raise DownloadCancelled()
            name = f"{job_id}.mp4"
            (directory / name).write_bytes(b"media")
            return {"filename": name}

        manager = DownloadManager(self.store, self.root, worker, max_workers=1, max_queued=1)
        try:
            first = manager.start("https://example.com/1", "mp4", "best")
            self.assertTrue(entered.wait(1))
            second = manager.start("https://example.com/2", "mp4", "best")
            with self.assertRaises(QueueFullError):
                manager.start("https://example.com/3", "mp4", "best")
            self.assertEqual(manager.cancel(second)["status"], "cancelled")
            gate.set()
            completed = self.wait_status(first, "completed")
            reopened = JobStore(self.root / "jobs.sqlite3")
            self.assertEqual(reopened.get(first)["filename"], completed["filename"])
        finally:
            gate.set()
            manager.shutdown()

    def test_restart_marks_pending_jobs_interrupted(self):
        self.store.create({"id": "pending", "status": "downloading", "created_at": time.time()})
        self.store.create({"id": "finished", "status": "completed", "created_at": time.time(), "filename": "song.mp3"})
        self.store.recover()
        self.assertEqual(self.store.get("pending")["status"], "interrupted")
        self.assertEqual(self.store.get("finished")["status"], "completed")

    def test_task_list_keeps_active_downloads_after_many_newer_completions(self):
        self.store.create({"id": "active", "status": "downloading", "created_at": 0})
        for number in range(60):
            self.store.create({"id": str(number), "status": "completed", "created_at": number + 1})
        tasks = self.store.list()
        self.assertEqual(len(tasks), 50)
        self.assertEqual(tasks[0]["id"], "active")

    def test_active_cancellation_stops_worker_and_does_not_create_file(self):
        entered = threading.Event()

        def worker(job_id, url, media_format, quality, directory, progress, cancel):
            entered.set()
            cancel.wait(3)
            raise DownloadCancelled()

        manager = DownloadManager(self.store, self.root, worker, max_workers=1, max_queued=0)
        try:
            job_id = manager.start("https://example.com/test", "mp4", "best")
            self.assertTrue(entered.wait(1))
            manager.cancel(job_id)
            self.wait_status(job_id, "cancelled")
            self.assertEqual(list(self.root.glob("*.mp4")), [])
        finally:
            manager.shutdown()

    def test_snapshot_updates_are_thread_safe(self):
        self.store.create({"id": "test", "created_at": time.time(), "status": "queued"})
        threads = [threading.Thread(target=self.store.update, args=("test",), kwargs={f"field_{index}": index}) for index in range(10)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        task = self.store.get("test")
        self.assertTrue(all(task[f"field_{index}"] == index for index in range(10)))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data", mode="local")

        def worker(job_id, url, media_format, quality, directory, progress, cancel):
            name = f"සිංහල 🎵 [{job_id}].{media_format}"
            (directory / name).write_bytes(b"test media bytes")
            return {"filename": name, "title": "සිංහල 🎵"}

        self.ffmpeg_patch = patch("app.main.ensure_ffmpeg")
        self.ffmpeg_patch.start()
        self.app = create_app(self.settings, worker=worker)
        self.lifecycle = self.app.router.lifespan_context(self.app)
        await self.lifecycle.__aenter__()

    async def asyncTearDown(self):
        await self.lifecycle.__aexit__(None, None, None)
        self.ffmpeg_patch.stop()
        self.temp.cleanup()

    async def test_api_rejects_invalid_input_before_creating_task(self):
        status, _, _ = await http(self.app, "/api/download", "POST", {"url": "https://youtu.be/test", "format": "mp3", "quality": "999"})
        self.assertEqual(status, 422)
        self.assertEqual(self.app.state.jobs.store.list(), [])

    async def test_cross_origin_mutation_is_rejected(self):
        status, _, _ = await http(self.app, "/api/download", "POST", {"url": "https://youtu.be/test"}, [(b"origin", b"https://example.com")])
        self.assertEqual(status, 403)
        self.assertEqual(self.app.state.jobs.store.list(), [])

    async def test_health_and_html(self):
        status, _, body = await http(self.app, "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["max_workers"], 2)
        status, headers, body = await http(self.app, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Snacky", body)
        self.assertEqual(headers[b"cache-control"], b"no-store")

    async def test_unknown_task_never_falls_back_to_filename_prefix(self):
        (self.settings.downloads_dir / "song [123456].mp3").write_bytes(b"test")
        status, _, _ = await http(self.app, "/api/file/12345600-0000-0000-0000-000000000000")
        self.assertEqual(status, 404)

    async def test_completed_file_remains_available_after_app_restart(self):
        job_id = str(uuid4())
        (self.settings.downloads_dir / "persistent.mp3").write_bytes(b"persisted audio")
        self.app.state.jobs.store.create({"id": job_id, "status": "completed", "filename": "persistent.mp3", "created_at": time.time()})
        second = create_app(self.settings)
        async with second.router.lifespan_context(second):
            status, _, body = await http(second, f"/api/file/{job_id}")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"persisted audio")

    async def test_end_to_end_task_stream_unicode_file_and_library(self):
        status, _, body = await http(self.app, "/api/download", "POST", {"url": "https://youtu.be/test", "format": "mp3", "quality": "320"})
        self.assertEqual(status, 200)
        job_id = json.loads(body)["download_id"]
        for _ in range(100):
            status, _, body = await http(self.app, f"/api/progress/{job_id}")
            task = json.loads(body)
            if task["status"] == "completed": break
            await asyncio.sleep(.01)
        self.assertEqual(task["status"], "completed")
        status, headers, body = await http(self.app, f"/api/file/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"test media bytes")
        self.assertEqual(headers[b"content-type"], b"audio/mpeg")
        self.assertIn(b"filename*=UTF-8''", headers[b"content-disposition"])
        status, _, body = await http(self.app, f"/api/stream-progress/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode()[6:].strip())["status"], "completed")
        status, _, body = await http(self.app, "/api/history")
        files = json.loads(body)["files"]
        self.assertEqual(files[0]["filename"], task["filename"])
        self.assertNotIn("path", files[0])
        status, _, _ = await http(self.app, f"/api/download-file?filename={quote(task['filename'])}")
        self.assertEqual(status, 200)
        status, _, _ = await http(self.app, f"/api/history/{quote(task['filename'])}", "DELETE")
        self.assertEqual(status, 200)
        status, _, _ = await http(self.app, f"/api/file/{job_id}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
