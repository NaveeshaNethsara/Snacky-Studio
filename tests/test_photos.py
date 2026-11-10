"""Photo-post, archive, cancellation, and API regression tests without internet."""
import asyncio
from http.client import RemoteDisconnected
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from gallery_dl.extractor.message import Message
from pydantic import ValidationError

from app.config import Settings
from app.downloader import download_media, extract_video_info, sanitize_error_message
from app.jobs import DownloadCancelled
from app.main import create_app
from app.photo_probe import collect_post, resolve_post_url
from app.photo_sources import extract_photo_post, is_photo_candidate
from app.photos import download_asset, image_extension
from app.instagram_photos import find_instagram_audio, instagram_shortcode
from app.processes import run_process
from app.schemas import DownloadRequest
from app.youtube_photos import parse_post
from tests.test_backend import http

PHOTO_POST = {
    "id": "123", "title": "සිංහල 🎵 photo post", "uploader": "Creator",
    "photos": [{"url": "https://images.example.com/first.jpg", "width": 600, "height": 800},
               {"url": "https://images.example.com/second.jpg", "width": 600, "height": 800}],
    "music": {"url": "https://audio.example.com/music.mp3", "title": "Original track", "duration": 12},
}


class FakeExtractor:
    category = "tiktok"

    def __init__(self, count=2, video=False):
        self.count, self.video = count, video

    def __iter__(self):
        data = {"id": "123", "post_type": "video" if self.video else "image", "desc": "Post", "user": "Creator"}
        yield Message.Directory, "", data
        for index in range(self.count):
            data.update(type="image", title="Post", num=index + 1)
            yield Message.Url, f"https://images.example.com/{index}.jpg", data
        data.update(type="audio", duration=12, music={"title": "Original track", "authorName": "Artist"})
        yield Message.Url, "https://audio.example.com/music.mp3", data


class PhotoTests(unittest.TestCase):
    def test_interrupted_asset_restarts_without_appending_partial_bytes(self):
        class InterruptedResponse(io.BytesIO):
            headers = {}
            def read(self, count):
                if self.tell():
                    raise RemoteDisconnected()
                return super().read(count)
        complete = io.BytesIO(b"complete photo")
        complete.headers = {}
        opener = Mock()
        opener.open.side_effect = [InterruptedResponse(b"partial"), complete]
        cancel = Mock()
        cancel.is_set.return_value = False
        cancel.wait.return_value = False
        with tempfile.TemporaryDirectory() as directory, patch("app.photos.urllib.request.build_opener", return_value=opener):
            path = Path(directory) / "asset.bin"
            self.assertEqual(download_asset("https://images.example.com/photo", path, "https://example.com/post", cancel, 100), 14)
            self.assertEqual(path.read_bytes(), b"complete photo")
            self.assertEqual(opener.open.call_count, 2)

    def test_network_retry_limit_and_cancellation(self):
        cancel = Mock()
        cancel.is_set.return_value = False
        cancel.wait.return_value = False
        with patch("app.photos._download_asset", side_effect=RemoteDisconnected()) as transfer:
            with self.assertRaisesRegex(ValueError, "three attempts"):
                download_asset("https://example.com/photo", None, "https://example.com/post", cancel, 100)
            self.assertEqual(transfer.call_count, 3)
            cancel.wait.return_value = True
            with self.assertRaises(DownloadCancelled):
                download_asset("https://example.com/photo", None, "https://example.com/post", cancel, 100)
            self.assertEqual(transfer.call_count, 4)

    def test_denied_asset_does_not_retry_access_restrictions(self):
        denied = urllib.error.HTTPError("https://example.com/photo", 403, "Denied", {}, None)
        with patch("app.photos._download_asset", side_effect=denied) as transfer:
            with self.assertRaisesRegex(ValueError, "authorized login"):
                download_asset("https://example.com/photo", None, "https://example.com/post", threading.Event(), 100)
            self.assertEqual(transfer.call_count, 1)

    def test_collects_every_photo_in_order_and_original_music(self):
        post = collect_post(FakeExtractor(5))
        self.assertEqual([photo["url"] for photo in post["photos"]], [f"https://images.example.com/{i}.jpg" for i in range(5)])
        self.assertEqual(post["music"]["title"], "Original track")
        self.assertEqual(post["music"]["author"], "Artist")
        self.assertEqual(post["uploader"], "Creator")

    def test_video_post_does_not_become_a_photo_post(self):
        self.assertIsNone(collect_post(FakeExtractor(video=True)))

    def test_over_limit_collection_is_rejected_instead_of_truncated(self):
        with self.assertRaisesRegex(ValueError, "No partial collection"):
            collect_post(FakeExtractor(201))

    def test_photo_formats_and_quality_validation(self):
        self.assertEqual(DownloadRequest(url="https://example.com/post", format="photos").quality, "best")
        self.assertEqual(DownloadRequest(url="https://example.com/post", format="slideshow", quality="720").quality, "720")
        for media_format, quality in [("photos", "720"), ("slideshow", "320"), ("slideshow", "2160")]:
            with self.assertRaises(ValidationError):
                DownloadRequest(url="https://example.com/post", format=media_format, quality=quality)

    def test_photo_detection_does_not_classify_unrelated_hosts(self):
        self.assertTrue(is_photo_candidate("https://vm.tiktok.com/test/"))
        self.assertTrue(is_photo_candidate("https://www.facebook.com/user/posts/123"))
        self.assertFalse(is_photo_candidate("https://tiktok.com.evil.example/photo/123"))
        self.assertFalse(is_photo_candidate("https://www.facebook.com/reel/123"))
        self.assertTrue(is_photo_candidate("https://www.instagram.com/p/example/"))
        self.assertTrue(is_photo_candidate("https://www.youtube.com/post/example"))
        self.assertFalse(is_photo_candidate("https://www.youtube.com/watch?v=example"))

    def test_youtube_community_photos_are_in_order_and_exclude_avatar(self):
        image = lambda name: {"backstageImageRenderer": {"image": {"thumbnails": [
            {"url": f"https://yt3.ggpht.com/{name}=s480", "width": 480, "height": 480},
            {"url": f"https://yt3.ggpht.com/{name}=s1080", "width": 1080, "height": 1080}]}}}
        data = {"avatar": image("avatar"), "post": {"postId": "target", "contentText": {"runs": [{"text": "Photo post"}]},
            "authorText": {"simpleText": "Creator"}, "backstageAttachment": {"postMultiImageRenderer": {"images": [image("first"), image("second")]}}}}
        result = parse_post(data, "target")
        self.assertEqual([photo["url"] for photo in result["photos"]], ["https://yt3.ggpht.com/first=s0", "https://yt3.ggpht.com/second=s0"])
        self.assertEqual(result["uploader"], "Creator")
        self.assertIsNone(result["music"])

    def test_youtube_text_and_private_posts_do_not_fall_back_to_unrelated_images(self):
        with self.assertRaisesRegex(ValueError, "No accessible images"):
            parse_post({"post": {"postId": "other", "backstageAttachment": {"backstageImageRenderer": {}}}}, "private")

    def test_instagram_carousel_skips_videos_and_reads_creator_name(self):
        class InstagramFixture:
            category = "instagram"
            def __iter__(self):
                yield Message.Directory, "", {"post_id": "123", "description": "Carousel", "user": {"username": "creator"}}
                yield Message.Url, "https://images.example.com/1.jpg", {"media_id": "1", "display_url": "https://images.example.com/1.jpg"}
                yield Message.Url, "https://videos.example.com/2.mp4", {"media_id": "2", "video_url": "https://videos.example.com/2.mp4"}
                yield Message.Url, "https://images.example.com/3.jpg", {"media_id": "3", "display_url": "https://images.example.com/3.jpg"}
        result = collect_post(InstagramFixture())
        self.assertEqual(len(result["photos"]), 2)
        self.assertEqual(result["uploader"], "creator")
        self.assertEqual(result["title"], "Carousel")

    def test_facebook_story_url_is_normalized_to_its_post(self):
        self.assertEqual(resolve_post_url("https://www.facebook.com/story.php?story_fbid=123&id=456"),
                         "https://www.facebook.com/456/posts/123")

    def test_photo_metadata_exposes_all_photos_without_audio_url(self):
        with patch("app.downloader.extract_photo_post", return_value=PHOTO_POST):
            result = extract_video_info("https://www.tiktok.com/@creator/photo/123")
        self.assertEqual(result["media_type"], "photos")
        self.assertEqual(result["photo_count"], 2)
        self.assertTrue(result["has_music"])
        self.assertNotIn("url", result["music"])

    def test_unavailable_explicit_photo_does_not_fall_back_to_video(self):
        with patch("app.downloader.extract_photo_post", side_effect=ValueError("Requires authorized login")), patch("app.downloader.yt_dlp.YoutubeDL") as video:
            with self.assertRaisesRegex(ValueError, "authorized"):
                extract_video_info("https://www.tiktok.com/@creator/photo/123")
            video.assert_not_called()

    def test_extractor_process_for_unsupported_host_does_not_use_network(self):
        self.assertIsNone(extract_photo_post("https://example.com/test"))

    def test_cancelled_subprocess_is_stopped_promptly(self):
        cancel = threading.Event()
        cancel.set()
        started = time.monotonic()
        with self.assertRaises(DownloadCancelled):
            run_process([sys.executable, "-c", "import time; time.sleep(20)"], cancel=cancel)
        self.assertLess(time.monotonic() - started, 2)

    def test_zip_contains_all_original_bytes_and_no_signed_urls_in_manifest(self):
        def asset(url, path, source, cancel, limit):
            data = b"\xff\xd8\xff" + url.encode()
            path.write_bytes(data)
            return len(data)
        with tempfile.TemporaryDirectory() as directory, patch("app.photos.extract_photo_post", return_value=PHOTO_POST), patch("app.photos.download_asset", side_effect=asset):
            root = Path(directory)
            result = download_media(str(uuid4()), "https://www.tiktok.com/@creator/photo/123", "photos", "best", root, lambda **data: None, threading.Event())
            with zipfile.ZipFile(root / result["filename"]) as archive:
                self.assertEqual(archive.namelist(), ["001.jpg", "002.jpg", "post.json"])
                self.assertEqual(archive.read("001.jpg"), b"\xff\xd8\xff" + PHOTO_POST["photos"][0]["url"].encode())
                manifest = json.loads(archive.read("post.json"))
                self.assertEqual(manifest["photo_count"], 2)
                self.assertEqual(manifest["title"], PHOTO_POST["title"])
                self.assertNotIn("images.example.com", archive.read("post.json").decode())
            self.assertFalse(list((root / ".work").iterdir()))

    def test_missing_photo_never_publishes_partial_archive(self):
        def asset(url, path, source, cancel, limit):
            data = b"\xff\xd8\xffok" if "first" in url else b"<html>login required</html>"
            path.write_bytes(data)
            return len(data)
        with tempfile.TemporaryDirectory() as directory, patch("app.photos.extract_photo_post", return_value=PHOTO_POST), patch("app.photos.download_asset", side_effect=asset):
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "No partial collection"):
                download_media(str(uuid4()), "https://www.tiktok.com/@creator/photo/123", "photos", "best", root, lambda **data: None, threading.Event())
            self.assertFalse(list(root.glob("*.zip")))
            self.assertFalse(list((root / ".work").iterdir()))

    def test_missing_music_cannot_silently_make_a_silent_slideshow(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.photos.extract_photo_post", return_value=PHOTO_POST | {"music": None}):
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "original music is unavailable"):
                download_media(str(uuid4()), "https://www.tiktok.com/@creator/photo/123", "slideshow", "best", root, lambda **data: None, threading.Event())
            self.assertFalse(list(root.glob("*.mp4")))

    def test_image_formats_are_detected_from_content_not_url_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.bin"
            path.write_bytes(b"RIFF1234WEBPdata")
            self.assertEqual(image_extension(path), "webp")
            path.write_bytes(b"<html>not an image</html>")
            with self.assertRaises(ValueError):
                image_extension(path)

    def test_instagram_find_audio_recursive(self):
        sample = {
            "clips_metadata": {
                "music_info": {
                    "music_asset_info": {
                        "progressive_download_url": "https://audio.cdn.example.com/sound.mp3",
                        "title": "Inspiring Tune",
                        "display_artist": "Gram Artist",
                        "duration_in_ms": 30000,
                    }
                }
            }
        }
        audio = find_instagram_audio(sample)
        self.assertIsNotNone(audio)
        self.assertEqual(audio["url"], "https://audio.cdn.example.com/sound.mp3")
        self.assertEqual(audio["title"], "Inspiring Tune")
        self.assertEqual(audio["author"], "Gram Artist")
        self.assertEqual(audio["duration"], 30.0)

    def test_instagram_shortcode_parsing(self):
        self.assertEqual(instagram_shortcode("https://www.instagram.com/p/DfH2aDBgLh1/?utm_source=ig"), "DfH2aDBgLh1")
        self.assertEqual(instagram_shortcode("https://instagram.com/share/p/DfH2aDBgLh1/"), "DfH2aDBgLh1")
        self.assertEqual(instagram_shortcode("https://www.instagram.com/reel/1143355341355451/"), "1143355341355451")
        self.assertIsNone(instagram_shortcode("https://facebook.com/reel/123"))

    def test_instagram_error_sanitization(self):
        err = "ERROR: [Instagram] DfH2WQoAal-: No video formats found!; please report this issue on https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"
        cleaned = sanitize_error_message(err, "https://www.instagram.com/p/DfH2aDBgLh1/")
        self.assertIn("contains photos rather than video streams", cleaned)
        self.assertNotIn("yt-dlp", cleaned)
        self.assertNotIn("||[0;31m", cleaned)

    def test_instagram_collect_post_audio(self):
        class FakeInstagramExtractor:
            category = "instagram"
            def __iter__(self):
                yield Message.Directory, "", {"id": "ig123", "post_text": "IG Carousel", "user": "ig_user"}
                yield Message.Url, "https://images.example.com/p1.jpg", {"type": "image", "width": 1080, "height": 1080}
                yield Message.Url, "https://audio.example.com/track.mp3", {"type": "audio", "audio_title": "Cool Song", "audio_artist": "Cool Artist", "audio_duration": 15}

        res = collect_post(FakeInstagramExtractor())
        self.assertIsNotNone(res)
        self.assertEqual(len(res["photos"]), 1)
        self.assertIsNotNone(res["music"])
        self.assertEqual(res["music"]["title"], "Cool Song")
        self.assertEqual(res["music"]["author"], "Cool Artist")
        self.assertEqual(res["music"]["duration"], 15)


class PhotoApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_job_zip_headers_library_and_existing_video_api(self):
        with tempfile.TemporaryDirectory() as directory, patch("app.main.ensure_ffmpeg"):
            root = Path(directory)
            settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data")

            received_indices = []
            def worker(job_id, url, media_format, quality, directory, progress, cancel, *, photo_index=0):
                if media_format in {"photo", "png"}:
                    received_indices.append(photo_index)
                suffix = "zip" if media_format == "photos" else "mp4" if media_format == "slideshow" else "jpg" if media_format == "photo" else media_format
                filename = f"සිංහල 🎵 [{job_id}].{suffix}"
                (directory / filename).write_bytes(b"test fixture only")
                return {"filename": filename}

            app = create_app(settings, worker=worker)
            async with app.router.lifespan_context(app):
                for media_format in ("photos", "slideshow", "mp4", "mp3", "photo", "png"):
                    status, _, body = await http(app, "/api/download", "POST", {"url": "https://example.com/post", "format": media_format, "photo_index": 1 if media_format in {"photo", "png"} else 0})
                    self.assertEqual(status, 200)
                    job_id = json.loads(body)["download_id"]
                    for _ in range(100):
                        _, _, body = await http(app, f"/api/progress/{job_id}")
                        if json.loads(body)["status"] == "completed":
                            break
                        await asyncio.sleep(.01)
                    status, headers, _ = await http(app, f"/api/file/{job_id}")
                    self.assertEqual(status, 200)
                    self.assertIn(b"filename*=UTF-8''", headers[b"content-disposition"])
                    if media_format == "photos":
                        self.assertEqual(headers[b"content-type"], b"application/zip")
                    elif media_format in {"photo", "png"}:
                        self.assertEqual(headers[b"content-type"], b"image/jpeg" if media_format == "photo" else b"image/png")
                self.assertEqual(received_indices, [1, 1])
                _, _, body = await http(app, "/api/history")
                self.assertEqual({file["kind"] for file in json.loads(body)["files"]}, {"photos", "video", "audio"})


if __name__ == "__main__":
    unittest.main()
