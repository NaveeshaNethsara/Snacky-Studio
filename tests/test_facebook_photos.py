"""Public Facebook photo matching and single-image downloads, without network."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.downloader import download_media
from app.facebook_photos import extract_facebook_photo, parse_photo, photo_id
from app.schemas import DownloadRequest

URL = "https://web.facebook.com/photo?fbid=123&set=a.456"
EMBED = '''<a href="https://www.facebook.com/Creator"><img src="https://scontent.fbcdn.net/avatar.jpg" aria-label="Creator"></a>
<a href="https://www.facebook.com/photo.php?fbid=999"><img src="https://scontent.fbcdn.net/other.jpg"></a>
<div class="userContent">A public photo <img src="https://static.xx.fbcdn.net/emoji.png"/>worth saving</div>
<a href="https://www.facebook.com/photo.php?fbid=123&amp;set=a.456"><img src="https://scontent.fbcdn.net/photo.jpg"
srcset="https://scontent.fbcdn.net/photo-500.jpg 500w, https://scontent.fbcdn.net/photo-1000.jpg 1000w"></a>
<a href="https://www.facebook.com/Creator/posts/789">Comment</a>'''


class FacebookPhotoTests(unittest.TestCase):
    def test_common_photo_urls_and_host_boundary(self):
        for url in [URL, "https://www.facebook.com/photo.php?fbid=123", "https://m.facebook.com/photo/?fbid=123", "https://www.facebook.com/creator/photos/a.456/123/"]:
            self.assertEqual(photo_id(url), "123")
        for url in ["https://facebook.com.evil.example/photo?fbid=123", "https://www.facebook.com/creator/posts/123", "https://www.facebook.com/photo?fbid=not-a-photo-id"]:
            self.assertIsNone(photo_id(url))

    def test_embed_saves_only_requested_photo_and_reads_creator(self):
        post = parse_photo(EMBED, "123")
        self.assertEqual(post["title"], "A public photo worth saving")
        self.assertEqual(post["uploader"], "Creator")
        self.assertEqual([photo["url"] for photo in post["photos"]], ["https://scontent.fbcdn.net/photo-1000.jpg"])

    def test_structured_photo_chooses_largest_image_without_avatar(self):
        data = {"photo": {"__typename": "Photo", "id": "123", "owner": {"name": "Creator", "image": {"uri": "https://scontent.fbcdn.net/avatar.jpg", "width": 9999, "height": 9999}},
            "creation_story": {"message": {"text": "Photo caption"}},
            "image": {"uri": "https://scontent.fbcdn.net/small.jpg", "width": 500, "height": 500},
            "image_fullscreen": {"uri": "https://scontent.fbcdn.net/large.jpg", "width": 1500, "height": 1000}}}
        post = parse_photo('<script type="application/json">' + json.dumps(data) + '</script>', "123")
        self.assertEqual(post["photos"][0]["url"], "https://scontent.fbcdn.net/large.jpg")
        self.assertEqual(post["title"], "Photo caption")

    def test_open_graph_image_requires_matching_photo_canonical_url(self):
        meta = '<meta property="og:image" content="https://scontent.fbcdn.net/photo.jpg"><meta property="og:url" content="https://www.facebook.com/photo?fbid=123">'
        self.assertEqual(len(parse_photo(meta, "123")["photos"]), 1)
        self.assertIsNone(parse_photo(meta, "999"))
        self.assertIsNone(parse_photo(meta.replace("scontent.fbcdn.net", "images.evil.example"), "123"))

    def test_login_shell_falls_back_to_official_public_embed(self):
        with patch("app.facebook_photos.read_page", side_effect=["<html>Log in to Facebook</html>", EMBED]) as pages:
            post = extract_facebook_photo(URL)
        self.assertEqual(post["id"], "123")
        self.assertEqual(pages.call_args_list[1].args[1], "https://www.facebook.com/plugins/post.php")

    def test_private_or_unavailable_post_never_saves_an_avatar(self):
        denied = '<a href="https://www.facebook.com/Creator"><img src="https://scontent.fbcdn.net/avatar.jpg" aria-label="Creator"></a>'
        with patch("app.facebook_photos.read_page", return_value=denied):
            with self.assertRaisesRegex(ValueError, "did not expose this photo"):
                extract_facebook_photo(URL)

    def test_selected_photo_keeps_source_bytes_and_uses_content_extension(self):
        post = {"id": "123", "title": "සිංහල 🎵 photo", "uploader": "Creator", "photos": [{"url": "https://scontent.fbcdn.net/first"}, {"url": "https://scontent.fbcdn.net/second"}], "music": None}
        original = b"\xff\xd8\xfforiginal jpeg bytes"
        def fetch(url, path, source, cancel, limit):
            self.assertEqual(url, post["photos"][1]["url"])
            path.write_bytes(original)
            return len(original)
        with tempfile.TemporaryDirectory() as directory, patch("app.photos.extract_photo_post", return_value=post), patch("app.photos.download_asset", side_effect=fetch) as transfer:
            root = Path(directory)
            result = download_media(str(uuid4()), URL, "photo", "best", root, lambda **data: None, threading.Event(), photo_index=1)
            self.assertTrue(result["filename"].endswith(".jpg"))
            self.assertEqual((root / result["filename"]).read_bytes(), original)
            self.assertEqual(result["photo_count"], 1)
            self.assertEqual(transfer.call_count, 1)
            self.assertFalse(list((root / ".work").iterdir()))
            with self.assertRaisesRegex(ValueError, "no longer available"):
                download_media(str(uuid4()), URL, "photo", "best", root, lambda **data: None, threading.Event(), photo_index=2)
            self.assertEqual(transfer.call_count, 1)

    def test_image_request_validates_index_and_quality(self):
        for media_format in ("photo", "png"):
            self.assertEqual(DownloadRequest(url=URL, format=media_format, photo_index=1).photo_index, 1)
            for values in ({"quality": "720"}, {"photo_index": -1}, {"photo_index": 200}):
                with self.assertRaises(ValidationError):
                    DownloadRequest(url=URL, format=media_format, **values)
        with self.assertRaises(ValidationError):
            DownloadRequest(url=URL, format="mp4", photo_index=1)

    def test_facebook_pcb_post_extractor_stops_at_post_photos(self):
        from app.photo_probe import get_post_photo_ids
        html = '<script type="application/json">{"data":{"album":{"media":{"edges":[{"node":{"id":"122243051564836239"}}]}}}}</script>'
        pids = get_post_photo_ids(html)
        self.assertEqual(pids, ["122243051564836239"])

    def test_sanitize_error_message_strips_ansi_and_formats_facebook_errors(self):
        from app.downloader import sanitize_error_message
        raw_ansi_err = "\x1b[0;31mERROR:\x1b[0m [facebook] 1143355341355451: Cannot parse data; please report this issue on https://github.com/yt-dlp/yt-dlp/issues?q="
        clean = sanitize_error_message(raw_ansi_err, "https://web.facebook.com/reel/1143355341355451")
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("ERROR:", clean)
        self.assertIn("private, age-restricted, or requires logging into Facebook", clean)
        self.assertIn("cookies.txt", clean)

    def test_sanitize_error_message_ui_escape_sequence(self):
        from app.downloader import sanitize_error_message
        ui_escaped = "||[0;31mERROR:||[0m [facebook] 12345: Cannot parse data"
        clean = sanitize_error_message(ui_escaped, "https://www.facebook.com/watch/?v=12345")
        self.assertNotIn("||[", clean)
        self.assertIn("private, age-restricted, or requires logging into Facebook", clean)

    def test_get_cookie_file_fallback(self):
        from app.config import get_cookie_file, ROOT_DIR
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("# Netscape HTTP Cookie File\n")
            temp_path = tf.name
        try:
            with patch.dict(os.environ, {"SNACKY_COOKIES_FILE": temp_path}):
                self.assertEqual(get_cookie_file(), temp_path)
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
