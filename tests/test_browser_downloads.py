"""Completed attachment handoff, independent preparations, and safe overlap."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.config import Settings
from app.jobs import DownloadCancelled
from app.main import create_app
from app.schemas import DownloadRequest
from tests.test_backend import http


class BrowserAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data")
        self.gates = {name: threading.Event() for name in ("first", "second", "failure")}
        self.content = b"\x00complete-media\xff" * 90000

        def worker(job_id, url, media_format, quality, directory, progress, cancel, **options):
            gate = self.gates[url.rsplit("/", 1)[-1]]
            progress(status="downloading", progress=10)
            while not gate.wait(.01):
                if cancel.is_set():
                    raise DownloadCancelled()
            if cancel.is_set():
                raise DownloadCancelled()
            if url.endswith("failure"):
                raise ValueError("Fixture conversion failed")
            suffix = "webp" if media_format == "photo" else media_format
            name = f"සිංහල 🎵 [{job_id}].{suffix}"
            (directory / name).write_bytes(self.content)
            return {"filename": name}

        self.ffmpeg = patch("app.main.ensure_ffmpeg")
        self.ffmpeg.start()
        self.app = create_app(self.settings, worker=worker)
        self.lifecycle = self.app.router.lifespan_context(self.app)
        await self.lifecycle.__aenter__()

    async def asyncTearDown(self):
        for gate in self.gates.values():
            gate.set()
        await self.lifecycle.__aexit__(None, None, None)
        self.ffmpeg.stop()
        self.temp.cleanup()

    async def start(self, name="first", media_format="mp4"):
        status, _, body = await http(self.app, "/api/download", "POST", {
            "url": "https://example.com/" + name, "format": media_format, "title": "සිංහල 🎵 favorite"})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["task"]["title"], "සිංහල 🎵 favorite")
        self.assertTrue(result["task"]["managed_here"])
        return result["download_id"]

    async def wait_status(self, job_id, wanted):
        for _ in range(150):
            task = self.app.state.jobs.store.get(job_id)
            if task["status"] == wanted:
                return task
            await asyncio.sleep(.01)
        self.fail(f"Task did not reach {wanted}: {task}")

    async def test_pending_jobs_do_not_create_a_zero_byte_browser_attachment_or_block_second_job(self):
        first = await self.start()
        status, headers, body = await http(self.app, f"/api/browser-download/{first}")
        self.assertEqual(status, 409)
        self.assertNotIn(b"content-disposition", headers)
        self.assertIn("still being prepared", json.loads(body)["detail"])
        second = await self.start("second")
        await self.wait_status(first, "downloading")
        await self.wait_status(second, "downloading")
        self.assertEqual(self.app.state.jobs.store.get(first)["status"], "downloading")
        status, _, _ = await http(self.app, "/api/health")
        self.assertEqual(status, 200)

    async def test_complete_file_has_known_length_unicode_filename_and_resumable_bytes(self):
        job_id = await self.start()
        self.gates["first"].set()
        await self.wait_status(job_id, "completed")
        status, headers, body = await http(self.app, f"/api/browser-download/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.content)
        self.assertEqual(int(headers[b"content-length"]), len(self.content))
        self.assertEqual(headers[b"accept-ranges"], b"bytes")
        self.assertIn(b"filename*=UTF-8''", headers[b"content-disposition"])
        self.assertEqual(headers[b"content-type"], b"video/mp4")
        status, headers, body = await http(self.app, f"/api/browser-download/{job_id}", headers=[(b"range", b"bytes=0-19")])
        self.assertEqual(status, 206)
        self.assertEqual(body, self.content[:20])
        self.assertEqual(headers[b"content-length"], b"20")

    async def test_cancellation_stops_only_selected_preparation(self):
        first = await self.start()
        second = await self.start("second")
        await self.wait_status(second, "downloading")
        status, _, _ = await http(self.app, f"/api/cancel/{first}", "POST")
        self.assertEqual(status, 200)
        await self.wait_status(first, "cancelled")
        self.assertEqual(self.app.state.jobs.store.get(second)["status"], "downloading")
        status, headers, _ = await http(self.app, f"/api/browser-download/{first}")
        self.assertEqual(status, 409)
        self.assertNotIn(b"content-disposition", headers)

    async def test_failed_preparation_does_not_publish_an_attachment(self):
        job_id = await self.start("failure")
        with self.assertLogs("app.jobs", level="ERROR"):
            self.gates["failure"].set()
            await self.wait_status(job_id, "error")
        status, headers, body = await http(self.app, f"/api/browser-download/{job_id}")
        self.assertEqual(status, 409)
        self.assertNotIn(b"content-disposition", headers)
        self.assertIn("Fixture conversion failed", json.loads(body)["detail"])
        self.assertEqual(list(self.settings.downloads_dir.iterdir()), [])

    async def test_source_photo_keeps_actual_extension(self):
        job_id = await self.start(media_format="photo")
        self.gates["first"].set()
        await self.wait_status(job_id, "completed")
        status, headers, content = await http(self.app, f"/api/browser-download/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(headers[b"content-type"], b"image/webp")
        self.assertTrue(headers[b"content-disposition"].endswith(b".webp"))
        self.assertEqual(content, self.content)

    async def test_unknown_task_and_cross_site_attachment_are_rejected(self):
        status, _, _ = await http(self.app, f"/api/browser-download/{uuid4()}")
        self.assertEqual(status, 404)
        job_id = await self.start()
        status, _, _ = await http(self.app, f"/api/browser-download/{job_id}", headers=[(b"sec-fetch-site", b"cross-site")])
        self.assertEqual(status, 403)

    async def test_upgrade_preserves_old_worker_and_keeps_cancellation_with_owner(self):
        job_id = await self.start()
        await self.wait_status(job_id, "downloading")
        second = create_app(self.settings, recover_jobs=False)
        async with second.router.lifespan_context(second):
            status, _, body = await http(second, "/api/tasks")
            task = next(item for item in json.loads(body)["tasks"] if item["id"] == job_id)
            self.assertEqual(task["status"], "downloading")
            self.assertFalse(task["managed_here"])
            status, _, _ = await http(second, f"/api/cancel/{job_id}", "POST")
            self.assertEqual(status, 409)
            status, _, _ = await http(second, f"/api/browser-download/{job_id}")
            self.assertEqual(status, 409)
            self.assertEqual(self.app.state.jobs.store.get(job_id)["status"], "downloading")
        self.gates["first"].set()
        await self.wait_status(job_id, "completed")


class BrowserFilenameTests(unittest.TestCase):
    def test_title_accepts_unicode_but_rejects_invalid_surrogates(self):
        self.assertEqual(DownloadRequest(url="https://example.com/video", title="සිංහල 🎵").title, "සිංහල 🎵")
        with self.assertRaises(ValidationError):
            DownloadRequest(url="https://example.com/video", title="\ud800")
