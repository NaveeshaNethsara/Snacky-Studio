"""Isolated browser QA server. Does not read or modify the user's downloads.

python -m tests.ui_preview (http://127.0.0.1:8124)
Any public URL returns fixture metadata. /failure simulates a failed download.
"""
import tempfile
import threading
import zipfile
import shutil
import subprocess
from pathlib import Path

import uvicorn

from app import api
from app.config import Settings
from app.jobs import DownloadCancelled
from app.main import create_app
from app.downloader import ensure_ffmpeg

FIXTURE_MEDIA = {}
HELD = threading.Event()


def metadata(url):
    if "/photo" in url:
        return {
            "id": "photo-fixture", "url": url, "title": "Photo collection · සිංහල 🎵", "uploader": "Snacky Studio",
            "media_type": "photos", "photo_count": 1 if "facebook.com" in url else 8, "duration": "1 photo" if "facebook.com" in url else "8 photos", "duration_seconds": 21,
            "has_music": "silent" not in url and "facebook.com" not in url, "music": None if "silent" in url or "facebook.com" in url else {"title": "Original post soundtrack", "duration": 21},
            "thumbnail": "/static/favicon.png", "platform": {"name": "Photo preview fixture", "id": "generic"},
            "photos": [{"url": "http://127.0.0.1:8124/static/favicon.png"} for _ in range(1 if "facebook.com" in url else 8)],
            "qualities": [{"id": "best", "badge": "1080p", "label": "Full HD"}, {"id": "720", "badge": "720p", "label": "HD"}],
            "audio_qualities": [],
        }
    return {
        "id": "fixture", "url": url, "title": ("Another moment worth keeping" if "second" in url else "A moment worth keeping") + " · සිංහල 🎵",
        "uploader": "Snacky Studio", "duration": "00:42", "duration_seconds": 42,
        "views": "12,345 views", "thumbnail": None,
        "platform": {"name": "Preview fixture", "id": "generic"},
        "qualities": [{"id": "best", "badge": "Original", "label": "Original quality"},
                      {"id": "1080", "badge": "1080p", "label": "Full HD"},
                      {"id": "720", "badge": "720p", "label": "HD"}],
        "audio_qualities": [{"id": str(rate), "badge": f"{rate} kbps", "label": "Audio bitrate"} for rate in [320, 256, 192, 128]],
    }


def worker(job_id, url, media_format, quality, directory, progress, cancel, **options):
    if "failure" in url:
        raise ValueError("Preview fixture: download failed. Try another public media link.")
    data = FIXTURE_MEDIA.get("mp3" if media_format == "mp3" else "mp4", b"Fixture")
    if "/hold/" in url:
        progress(status="downloading", progress=35, title=metadata(url)["title"], downloaded_bytes=int(len(data) * .35),
                 total_bytes=len(data), speed="2.4 MB/s", eta="20s")
        while not HELD.wait(.05):
            if cancel.is_set():
                raise DownloadCancelled()
    for percent in range(0, 100, 10):
        if cancel.wait(2):
            raise DownloadCancelled()
        progress(status="downloading", progress=percent, title=metadata(url)["title"], speed="2.4 MB/s", eta="20s",
                 downloaded_bytes=int(len(data) * percent / 100), total_bytes=len(data),
                 detail=f"Downloaded photo {min(8, percent // 10)} of 8" if media_format in {"photos", "slideshow"} else None)
    progress(status="processing", progress=99, speed="—", eta="Processing…")
    if cancel.wait(2):
        raise DownloadCancelled()
    suffix = "zip" if media_format == "photos" else "mp4" if media_format == "slideshow" else "png" if media_format == "photo" else media_format
    filename = f"Snacky browser QA · සිංහල 🎵 [{job_id}].{suffix}"
    if media_format == "photos":
        image = (Path(__file__).resolve().parent.parent / "app/static/favicon.png").read_bytes()
        with zipfile.ZipFile(directory / filename, "w") as archive:
            for number in range(1, 9):
                archive.writestr(f"{number:03d}.png", image)
    elif media_format in {"photo", "png"}:
        (directory / filename).write_bytes((Path(__file__).resolve().parent.parent / "app/static/favicon.png").read_bytes())
    else:
        (directory / filename).write_bytes(data)
    return {"filename": filename, "title": metadata(url)["title"]}


if __name__ == "__main__":
    api.extract_video_info = metadata
    with tempfile.TemporaryDirectory(prefix="snacky-ui-qa-") as directory:
        root = Path(directory)
        ensure_ffmpeg()
        source = root / "source.mp4"
        audio = root / "source.mp3"
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x7856ab:s=320x180:r=15",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-b:a", "320k", str(audio)], check=True)
        FIXTURE_MEDIA.update(mp4=source.read_bytes(), mp3=audio.read_bytes())
        settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data")
        settings.prepare()
        (settings.downloads_dir / "Golden hour · සිංහල 🎵.mp4").write_bytes(b"Video fixture")
        (settings.downloads_dir / "Soundtrack & 'summer'.mp3").write_bytes(b"Audio fixture")
        with zipfile.ZipFile(settings.downloads_dir / "Eight memories.zip", "w") as archive:
            archive.writestr("fixture.txt", "Photo library fixture")
        preview = create_app(settings, worker=worker)

        @preview.post("/qa/release")
        async def release():
            HELD.set()
            return {"success": True}

        uvicorn.run(preview, host="127.0.0.1", port=8124, log_level="warning")
