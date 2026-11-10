"""Media extraction and conversion; scheduling lives in jobs.py."""
import logging
import os
import re
import shutil
import threading
from functools import lru_cache
from urllib.parse import urlsplit

import static_ffmpeg
import yt_dlp

from app.config import ROOT_DIR, get_cookie_file
from app.files import format_bytes
from app.jobs import DownloadCancelled
from app.photo_sources import extract_photo_post, is_photo_candidate, is_explicit_photo_url

logger = logging.getLogger(__name__)
_ffmpeg_lock = threading.Lock()


@lru_cache(maxsize=1)
def ensure_ffmpeg():
    with _ffmpeg_lock:
        static_ffmpeg.add_paths()


def format_duration(seconds):
    if seconds is None:
        return "—"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def detect_platform(url):
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    platforms = [
        (("youtube.com", "youtu.be"), "YouTube", "youtube"),
        (("instagram.com", "instagr.am"), "Instagram", "instagram"),
        (("tiktok.com",), "TikTok", "tiktok"),
        (("facebook.com", "fb.watch", "fb.com"), "Facebook", "facebook"),
        (("twitter.com", "x.com"), "X / Twitter", "twitter"),
    ]
    for domains, name, key in platforms:
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return {"name": name, "id": key, "badge": name, "type": key}
    return {"name": "Web media", "id": "generic", "badge": "Web media", "type": "generic"}


def sanitize_error_message(exc, url=None):
    msg = str(exc or "")
    # Strip terminal ANSI escape codes and UI artifacts like ||[0;31m ... ||[0m
    msg = re.sub(r'(\x1b\[|\b\|\|\[)[0-9;]*[a-zA-Z]|\b\|\|\[0m', '', msg).strip()

    if url and any(domain in url.lower() for domain in ("facebook.com", "fb.watch", "fb.com")):
        is_reel = "/reel/" in url.lower() or "/share/r/" in url.lower()
        target = "reel" if is_reel else "video"
        if any(needle in msg for needle in ("Cannot parse data", "This video is only available for registered users", "login_form", "loginbutton")) or "login" in msg.lower():
            return (
                f"This Facebook {target} could not be retrieved. "
                "It appears to be private, age-restricted, or requires logging into Facebook. "
                "If this content is restricted, add a cookies.txt file to the application directory to download it."
            )
        if "HTTP Error 404" in msg or "404 Not Found" in msg:
            return f"This Facebook {target} was not found (HTTP 404). Check that the link is correct and publicly available."
        if "HTTP Error 400" in msg or "400 Bad Request" in msg:
            return "Facebook rejected the request (HTTP 400). Please verify the link or try again."

    if url and any(domain in url.lower() for domain in ("instagram.com", "instagr.am")):
        is_reel = "/reel/" in url.lower() or "/reels/" in url.lower()
        target = "reel" if is_reel else "post"
        if "No video formats found" in msg:
            return (
                f"This Instagram {target} contains photos rather than video streams. "
                "If this is a photo post or carousel, it may require login or cookies to download."
            )
        if any(needle in msg for needle in ("Cannot parse data", "This content is only available for registered users", "login", "cookies", "checkpoint", "empty media response", "restricted", "rate-limit")) or "login" in msg.lower():
            return (
                f"This Instagram {target} could not be retrieved. "
                "It appears to be private, age-restricted, or requires logging into Instagram. "
                "If this content is restricted, add a cookies.txt file to the application directory to download it."
            )
        if "HTTP Error 404" in msg or "404 Not Found" in msg:
            return f"This Instagram {target} was not found (HTTP 404). Check that the link is correct and publicly available."
        if "HTTP Error 400" in msg or "400 Bad Request" in msg:
            return "Instagram rejected the request (HTTP 400). Please verify the link or try again."

    if "; please report this issue on https://github.com/yt-dlp/yt-dlp/issues" in msg:
        msg = msg.split("; please report this issue")[0]
    msg = re.sub(r'Confirm you are on the latest version using\s+yt-dlp\s+-U', '', msg).strip()
    msg = re.sub(r'please report this issue on\s+https://github.com/yt-dlp/yt-dlp/issues[^\s]*', '', msg).strip()
    msg = msg.strip().rstrip(";, :")

    return msg or "Could not retrieve media. Check that the link is public and available."


def common_options():
    options = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "playlist_items": "1",
        "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
        "remote_components": ["ejs:github"], "js_runtimes": {"node": {}},
        # Stay below YouTube's 10 MB request threshold, including yt-dlp's jitter.
        "http_chunk_size": 5 * 1024 * 1024,
        "concurrent_fragment_downloads": 4,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate",
        },
    }
    if cookies := get_cookie_file():
        options["cookiefile"] = cookies
    return options


def first_media(info):
    if not info:
        raise ValueError("Could not retrieve media. Check that the link is public and available.")
    if "entries" in info:
        info = next((entry for entry in info["entries"] or [] if entry), None)
        if not info:
            raise ValueError("No downloadable media was found at this link.")
    if info.get("is_live"):
        raise ValueError("Live streams are not supported. Try again after the broadcast ends.")
    return info


def extract_video_info(url):
    photo_err = None
    if is_photo_candidate(url):
        try:
            post = extract_photo_post(url)
        except ValueError as err:
            if is_explicit_photo_url(url):
                raise
            photo_err = err
            post = None  # A Facebook/Instagram post can contain video instead of photos.
        if post:
            music = post.get("music")
            return {
                "id": post["id"], "title": post["title"], "uploader": post["uploader"],
                "media_type": "photos", "photo_count": len(post["photos"]),
                "photos": post["photos"], "music": {key: value for key, value in (music or {}).items() if key != "url"},
                "has_music": bool(music and music.get("url")), "thumbnail": post["photos"][0]["url"],
                "duration": f"{len(post['photos'])} photo{'s' if len(post['photos']) != 1 else ''}", "duration_seconds": (music or {}).get("duration") or 0,
                "qualities": [{"id": "best", "badge": "1080p", "label": "1080p slideshow"},
                              {"id": "720", "badge": "720p", "label": "720p slideshow"}],
                "audio_qualities": [], "platform": detect_platform(url), "url": url,
            }
    info = None
    last_exc = None
    try:
        with yt_dlp.YoutubeDL(common_options() | {"skip_download": True}) as ydl:
            info = first_media(ydl.extract_info(url, download=False))
    except Exception as exc:
        last_exc = exc
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if any(host == d or host.endswith("." + d) for d in ("facebook.com", "fb.com")):
            reel_match = re.search(r'/reel/(\d+)', parsed.path)
            if reel_match:
                video_id = reel_match.group(1)
                for fallback_url in (f"https://www.facebook.com/watch/?v={video_id}", f"https://www.facebook.com/video.php?v={video_id}"):
                    try:
                        with yt_dlp.YoutubeDL(common_options() | {"skip_download": True}) as ydl:
                            info = first_media(ydl.extract_info(fallback_url, download=False))
                            if info:
                                break
                    except Exception:
                        pass
        if not info:
            if photo_err:
                raise photo_err
            raise ValueError(sanitize_error_message(last_exc, url)) from last_exc
    platform = detect_platform(url)
    formats = info.get("formats") or [info]
    heights = sorted({int(fmt["height"]) for fmt in formats
                      if fmt.get("height") and fmt.get("vcodec") != "none" and 0 < fmt["height"] <= 4320}, reverse=True)
    qualities = [{"id": "best", "label": "Original quality", "badge": "Original"}]
    labels = {2160: "4K Ultra HD", 1440: "Quad HD", 1080: "Full HD", 720: "HD", 480: "Standard", 360: "Compact"}
    qualities.extend({"id": str(height), "label": labels.get(height, "Source resolution"), "badge": f"{height}p"}
                     for height in heights)
    audio = [{"id": str(rate), "label": label, "badge": f"{rate} kbps"} for rate, label in
             [(320, "Highest bitrate"), (256, "High bitrate"), (192, "Balanced"), (128, "Smaller file")]]
    title = info.get("title")
    if not title or title.lower() in {"video", "instagram post", "post", "tiktok", "facebook reel"}:
        description = (info.get("description") or "").strip()
        title = description.split("\n")[0][:120] if description else f"{platform['name']} video"
    uploader = next((info.get(key) for key in ("uploader", "channel", "creator", "uploader_id") if info.get(key)), platform["name"])
    views = info.get("view_count")
    return {
        "id": info.get("id", ""), "title": title, "uploader": uploader,
        "duration": format_duration(info.get("duration")), "duration_seconds": info.get("duration") or 0,
        "views": f"{views:,} views" if views is not None else "Views unavailable",
        "thumbnail": info.get("thumbnail"), "qualities": qualities, "audio_qualities": audio,
        "platform": platform, "url": url,
        "media_type": "video",
    }


def format_selector(quality):
    limit = "" if quality == "best" else f"[height<=?{int(quality)}]"
    return (
        f"bestvideo{limit}[ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo{limit}+bestaudio/best{limit}[ext=mp4]/best{limit}/bestvideo{limit}"
    )


def _safe_retry_sleep(*args, **kwargs):
    n = kwargs.get("n", args[0] if args else 0)
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    return min(10, max(1, n * 2))


def download_media(job_id, url, media_format, quality, downloads_dir, progress, cancel, *, photo_index=0):
    """Publish only a converted file; partial files stay outside the library."""
    if media_format in {"photos", "slideshow", "photo", "png"}:
        from app.photos import download_photo_post
        return download_photo_post(job_id, url, media_format, quality, downloads_dir, progress, cancel, photo_index=photo_index)
    ensure_ffmpeg()
    work_root = (downloads_dir / ".work").resolve()
    work_dir = work_root / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    def check_cancel():
        if cancel.is_set():
            raise DownloadCancelled()

    def progress_hook(data):
        check_cancel()
        if data["status"] == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = min(99, round(downloaded / total * 100, 1)) if total else 0
            eta = data.get("eta")
            media_info = data.get("info_dict") or {}
            title = {"title": media_info["title"]} if media_info.get("title") else {}
            stream = "audio" if media_info.get("vcodec") == "none" else "video"
            progress(status="downloading", progress=percent, downloaded_bytes=downloaded, total_bytes=total,
                     **title, error=None, detail=f"Downloading {stream}",
                     speed=f"{format_bytes(data.get('speed'))}/s" if data.get("speed") else "Calculating…",
                     eta=f"{int(eta)}s" if eta is not None else "Calculating…")
        elif data["status"] == "finished":
            # Video and audio can download separately; merging starts in the PP hook.
            progress(status="downloading", progress=99, detail="Fetching next stream", speed="—", eta="Fetching next stream…")

    def postprocessor_hook(data):
        check_cancel()
        progress(status="processing" if data["status"] == "started" else "finishing", progress=99,
                 speed="—", eta="Processing…", detail="Merging audio and video" if "Merger" in data.get("postprocessor", "") else "Finalizing the file")

    def match_filter(info, *, incomplete=False):
        check_cancel()
        if info.get("is_live"):
            raise ValueError("Live streams are not supported. Try again after the broadcast ends.")

    options = common_options() | {
        "outtmpl": str(work_dir / "%(title).120B [%(id)s].%(ext)s"), "windowsfilenames": True,
        "progress_hooks": [progress_hook], "postprocessor_hooks": [postprocessor_hook],
        "match_filter": match_filter,
        # Long transfers need more tolerance than a short metadata lookup.
        "retries": 10, "fragment_retries": 10,
        "retry_sleep_functions": {
            "http": _safe_retry_sleep,
            "fragment": _safe_retry_sleep,
            "extractor": _safe_retry_sleep,
        },
    }
    if media_format == "mp3":
        options.update(format="bestaudio/best", postprocessors=[
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": quality},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ])
    else:
        options.update(format=format_selector(quality), merge_output_format="mp4", postprocessors=[
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ])
    try:
        check_cancel()
        info = None
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = first_media(ydl.extract_info(url, download=True))
        except Exception as exc:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            if any(host == d or host.endswith("." + d) for d in ("facebook.com", "fb.com")):
                reel_match = re.search(r'/reel/(\d+)', parsed.path)
                if reel_match:
                    video_id = reel_match.group(1)
                    for fallback_url in (f"https://www.facebook.com/watch/?v={video_id}", f"https://www.facebook.com/video.php?v={video_id}"):
                        try:
                            with yt_dlp.YoutubeDL(options) as ydl:
                                info = first_media(ydl.extract_info(fallback_url, download=True))
                                if info:
                                    break
                        except Exception:
                            pass
            if not info:
                raise ValueError(sanitize_error_message(exc, url)) from exc
        check_cancel()
        candidates = [path for path in work_dir.glob(f"*.{media_format}") if path.is_file() and path.stat().st_size > 0]
        if len(candidates) != 1:
            raise RuntimeError("Conversion did not produce a complete file. Please retry the download.")
        final = candidates[0]
        filename = f"{final.stem} [{job_id}].{media_format}"
        target = downloads_dir / filename
        os.replace(final, target)
        return {"filename": filename, "title": info.get("title") or "Downloaded media",
                "thumbnail": info.get("thumbnail") or "", "size_bytes": target.stat().st_size}
    finally:
        resolved = work_dir.resolve()
        if resolved.parent == work_root and not work_dir.is_symlink():
            try:
                shutil.rmtree(resolved)
            except OSError:
                logger.warning("Could not clean temporary files for %s", job_id)

