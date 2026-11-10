"""Download complete photo collections and render ordered slideshows."""
import http.client
import http.cookiejar
import json
import os
import re
import shutil
import urllib.error
import urllib.request
import zipfile

from app.config import get_cookie_file
from app.jobs import DownloadCancelled
from app.photo_sources import extract_photo_post, invalidate_photo_cache
from app.processes import run_process
from app.schemas import InfoRequest

MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_AUDIO_BYTES = 250 * 1024 * 1024
MAX_COLLECTION_BYTES = 2 * 1024 * 1024 * 1024


def check_cancel(cancel):
    if cancel.is_set():
        raise DownloadCancelled()


class ValidatedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        InfoRequest(url=new_url)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def download_asset(url, path, source_url, cancel, max_bytes):
    for attempt in range(3):
        check_cancel(cancel)
        try:
            return _download_asset(url, path, source_url, cancel, max_bytes)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code not in {429, 500, 502, 503, 504}:
                raise ValueError("The platform did not allow this media download. Retry the post, or use an authorized login session if required.") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            pass
        if attempt == 2:
            raise ValueError("The media connection was interrupted after three attempts. Please retry; no partial collection was saved.")
        if cancel.wait(.5 * (attempt + 1)):
            raise DownloadCancelled()


def _download_asset(url, path, source_url, cancel, max_bytes):
    InfoRequest(url=url)
    handlers = [ValidatedRedirect()]
    cookies_file = get_cookie_file()
    if cookies_file:
        jar = http.cookiejar.MozillaCookieJar(cookies_file)
        jar.load(ignore_discard=True, ignore_expires=False)
        handlers.append(urllib.request.HTTPCookieProcessor(jar))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
        "Referer": source_url,
    })
    size = 0
    with opener.open(request, timeout=20) as response, path.open("wb") as output:
        if int(response.headers.get("Content-Length") or 0) > max_bytes:
            raise ValueError("A media file exceeds the supported download size.")
        while chunk := response.read(64 * 1024):
            check_cancel(cancel)
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("A media file exceeds the supported download size.")
            output.write(chunk)
    check_cancel(cancel)
    if not size:
        raise ValueError("The platform returned an empty media file. Please retry.")
    return size


def image_extension(path):
    with path.open("rb") as file:
        header = file.read(64)
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header[4:8] == b"ftyp" and (b"avif" in header or b"avis" in header):
        return "avif"
    raise ValueError("The platform did not return a supported photo. No partial collection was saved.")


def ffmpeg(arguments, cancel, timeout=600):
    code, _, _ = run_process([shutil.which("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *arguments],
                                  cancel=cancel, timeout=timeout)
    if code:
        # Raw FFmpeg errors can contain signed URLs or machine-specific paths.
        raise ValueError("Could not convert the post's photos or music into a slideshow.")


def probe_file(path, cancel):
    code, output, _ = run_process([shutil.which("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                  cancel=cancel, timeout=30)
    if code:
        raise ValueError("The source media could not be read. Try downloading the photos instead.")
    return json.loads(output)


def render_slideshow(images, audio, destination, work_dir, quality, progress, cancel):
    probe = probe_file(audio, cancel)
    if not any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])):
        raise ValueError("The original music is unavailable. You can still download the photos.")
    duration = float(probe.get("format", {}).get("duration") or 0)
    if not 0 < duration <= 600:
        raise ValueError("Slideshow music must be a readable clip up to 10 minutes long.")
    first = probe_file(images[0], cancel).get("streams", [{}])[0]
    width, height = int(first.get("width") or 0), int(first.get("height") or 0)
    if not width or not height:
        raise ValueError("Could not read the post's first photo.")
    size = 1080 if quality == "best" else int(quality)
    # Preserve portrait, landscape, or square orientation. Pad instead of cropping.
    frame = (size * 16 // 9 // 2 * 2, size) if width > height else (size, size * 16 // 9 // 2 * 2)
    if width == height:
        frame = (size, size)
    normalized = []
    for index, image in enumerate(images, 1):
        check_cancel(cancel)
        target = work_dir / f"slide-{index:03d}.png"
        w, h = frame
        ffmpeg(["-i", str(image), "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-frames:v", "1", str(target)], cancel, timeout=60)
        normalized.append(target)
        progress(status="processing", progress=65 + 20 * index / len(images), detail=f"Preparing photo {index} of {len(images)}")
    seconds = duration / len(images)
    playlist = work_dir / "slides.txt"
    playlist.write_text("".join(f"file '{image.name}'\nduration {seconds:.9f}\n" for image in normalized)
                        + f"file '{normalized[-1].name}'\n", encoding="ascii")
    progress(status="processing", progress=90, detail="Rendering slideshow with the original music")
    ffmpeg(["-f", "concat", "-safe", "1", "-i", str(playlist), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-vf", "fps=30", "-t", f"{duration:.9f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination)], cancel)
    result = probe_file(destination, cancel)
    if {stream.get("codec_type") for stream in result.get("streams", [])} != {"video", "audio"}:
        raise ValueError("The slideshow did not contain both photos and music.")
    return duration


def safe_stem(title):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return stem.encode("utf-8")[:120].decode("utf-8", errors="ignore") or "Photo post"


def download_photo_post(job_id, url, media_format, quality, downloads_dir, progress, cancel, *, photo_index=0):
    from app.downloader import ensure_ffmpeg
    work_root = (downloads_dir / ".work").resolve()
    work_dir = work_root / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        check_cancel(cancel)
        post = extract_photo_post(url, cancel)
        if not post or not post.get("photos"):
            raise ValueError("This link is not an accessible photo post. Use the video download option for videos.")
        photos, music = post["photos"], post.get("music")
        if media_format in {"photo", "png"}:
            if photo_index >= len(photos):
                raise ValueError("That photo is no longer available in this post. Analyze the link again.")
            photos = [photos[photo_index]]
        if media_format == "slideshow" and not (music and music.get("url")):
            raise ValueError("The original music is unavailable. You can still download all photos.")
        progress(status="downloading", progress=0, title=post["title"], photo_count=len(photos), media_type="photos",
                 music_title=(music or {}).get("title"), detail=f"Downloading {len(photos)} photo{'s' if len(photos) != 1 else ''}")
        images, total = [], 0
        for index, photo in enumerate(photos, 1):
            check_cancel(cancel)
            temp = work_dir / f"photo-{index:03d}.bin"
            total += download_asset(photo["url"], temp, url, cancel, MAX_IMAGE_BYTES)
            if total > MAX_COLLECTION_BYTES:
                raise ValueError("The photo collection exceeds 2 GB. No partial collection was saved.")
            extension = image_extension(temp)
            image = work_dir / f"{index:03d}.{extension}"
            temp.rename(image)
            images.append(image)
            progress(status="downloading", progress=65 * index / len(photos), downloaded_bytes=total,
                     detail=f"Downloaded photo {index} of {len(photos)}")
        duration = None
        if media_format == "photo":
            output = images[0]
            suffix = output.suffix[1:]
        elif media_format == "png":
            ensure_ffmpeg()
            output = work_dir / "photo.png"
            progress(status="processing", progress=85, detail="Converting the photo to PNG")
            ffmpeg(["-i", str(images[0]), "-frames:v", "1", str(output)], cancel, timeout=60)
            if image_extension(output) != "png":
                raise ValueError("The photo could not be converted to PNG.")
            suffix = "png"
        elif media_format == "photos":
            output = work_dir / "photos.zip"
            progress(status="processing", progress=90, detail="Packing all photos into one ZIP")
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                for image in images:
                    check_cancel(cancel)
                    archive.write(image, image.name)
                archive.writestr("post.json", json.dumps({"title": post["title"], "uploader": post["uploader"],
                    "source_url": url, "photo_count": len(images), "music_title": (music or {}).get("title"),
                    "photos": [image.name for image in images]}, ensure_ascii=False, indent=2))
            suffix = "zip"
        else:
            ensure_ffmpeg()
            audio = work_dir / "music.bin"
            progress(status="downloading", progress=65, detail="Downloading the post's original music")
            download_asset(music["url"], audio, url, cancel, MAX_AUDIO_BYTES)
            output = work_dir / "slideshow.mp4"
            duration = render_slideshow(images, audio, output, work_dir, quality, progress, cancel)
            suffix = "mp4"
        check_cancel(cancel)
        if not output.is_file() or not output.stat().st_size:
            raise ValueError("The photo download did not produce a complete file.")
        filename = f"{safe_stem(post['title'])} [{job_id}].{suffix}"
        target = downloads_dir / filename
        progress(status="finishing", progress=99, detail="Saving your file")
        os.replace(output, target)
        return {"filename": filename, "title": post["title"], "thumbnail": photos[0]["url"],
                "size_bytes": target.stat().st_size, "photo_count": len(images), "media_type": "photos",
                "music_title": (music or {}).get("title"), "duration_seconds": duration,
                "detail": {"photos": "All photos saved in a ZIP", "slideshow": "Slideshow saved with the original music",
                           "photo": "Photo saved in its source format", "png": "Photo saved as PNG"}[media_format]}
    except Exception:
        invalidate_photo_cache(url)
        raise
    finally:
        resolved = work_dir.resolve()
        if resolved.parent == work_root and not work_dir.is_symlink():
            shutil.rmtree(resolved, ignore_errors=True)
