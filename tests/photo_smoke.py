"""Real FFmpeg proof: ordered mixed-format photos, music, complete ZIP."""
import json
import math
import shutil
import struct
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.downloader import download_media, ensure_ffmpeg


def main():
    ensure_ffmpeg()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="snacky-photo-smoke-") as directory:
        root = Path(directory)
        outputs = root / "downloads"
        outputs.mkdir()
        sources = {}
        for index, (color, size, extension) in enumerate([("red", "320x180", "jpg"), ("green", "180x320", "png"), ("blue", "200x200", "webp")], 1):
            path = root / f"{index}.{extension}"
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"color={color}:s={size}", "-frames:v", "1", str(path)], check=True)
            sources[f"https://images.example.com/{index}"] = path
        audio = root / "music.m4a"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:a", "aac", str(audio)], check=True)
        sources["https://audio.example.com/original"] = audio
        post = {"id": "test", "title": "සිංහල 🎵 ordered photos", "uploader": "Fixture",
                "photos": [{"url": url} for url in sources if "images" in url],
                "music": {"url": "https://audio.example.com/original", "title": "880 Hz original fixture"}}

        def fetch(url, path, source, cancel, max_bytes):
            shutil.copyfile(sources[url], path)
            return path.stat().st_size

        with patch("app.photos.extract_photo_post", return_value=post), patch("app.photos.download_asset", side_effect=fetch):
            result = download_media(str(uuid4()), "https://www.tiktok.com/@fixture/photo/123", "photos", "best", outputs, lambda **data: None, threading.Event())
            with zipfile.ZipFile(outputs / result["filename"]) as archive:
                assert archive.namelist() == ["001.jpg", "002.png", "003.webp", "post.json"], archive.namelist()
                for index, path in enumerate(list(sources.values())[:3], 1):
                    assert archive.read(f"{index:03d}{path.suffix}") == path.read_bytes()
            print("PASS: complete ordered ZIP preserves every original image byte")
            result = download_media(str(uuid4()), "https://www.facebook.com/photo?fbid=123", "photo", "best", outputs, lambda **data: None, threading.Event(), photo_index=2)
            assert (outputs / result["filename"]).read_bytes() == sources["https://images.example.com/3"].read_bytes()
            result = download_media(str(uuid4()), "https://www.facebook.com/photo?fbid=123", "png", "best", outputs, lambda **data: None, threading.Event())
            png = outputs / result["filename"]
            source = sources["https://images.example.com/1"]
            def pixels(path):
                return subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True).stdout
            assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            assert pixels(png) == pixels(source)
            print("PASS: selected original photo preserves its bytes; JPEG-to-PNG preserves decoded pixels and dimensions")
            result = download_media(str(uuid4()), "https://www.tiktok.com/@fixture/photo/123", "slideshow", "720", outputs, lambda **data: None, threading.Event())
            video = outputs / result["filename"]
            probe = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)], check=True, capture_output=True).stdout)
            assert {stream["codec_type"] for stream in probe["streams"]} == {"video", "audio"}
            assert abs(float(probe["format"]["duration"]) - 3) < .15
            video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
            assert video_stream["height"] == 720
            for second, channel in ((.4, 0), (1.4, 1), (2.4, 2)):
                pixel = subprocess.run([ffmpeg, "-v", "error", "-ss", str(second), "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True).stdout
                assert pixel[channel] > max(pixel[(channel + 1) % 3], pixel[(channel + 2) % 3]) + 20, (second, list(pixel))
            pcm = subprocess.run([ffmpeg, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"], check=True, capture_output=True).stdout
            samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
            crossings = sum(a < 0 <= b for a, b in zip(samples, samples[1:]))
            frequency = crossings / (len(samples) / 8000)
            assert 870 <= frequency <= 890, frequency
            assert not list((outputs / ".work").iterdir())
            print("PASS: real MP4 preserves photo order, fits mixed orientations, and uses original 880 Hz audio for its full duration")


if __name__ == "__main__":
    main()
