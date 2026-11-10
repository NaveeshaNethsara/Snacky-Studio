"""Detect photo-post candidates and isolate gallery-dl extraction."""
import json
import sys
import copy
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config import ROOT_DIR, get_cookie_file
from app.processes import run_process

_cache = {}
_cache_lock = threading.Lock()


def canonical_post_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host.endswith("tiktok.com") or host in {"instagram.com", "www.instagram.com", "youtube.com", "www.youtube.com", "m.youtube.com"}:
        return urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def cache_key(url):
    cookies = get_cookie_file() or ""
    try:
        modified = Path(cookies).stat().st_mtime_ns if cookies else 0
    except OSError:
        modified = 0
    return canonical_post_url(url), cookies, modified


def invalidate_photo_cache(url):
    with _cache_lock:
        _cache.pop(cache_key(url), None)


def is_photo_candidate(url):
    parsed = urlsplit(url)
    host, path = (parsed.hostname or "").lower(), parsed.path.lower()
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return True
    if host == "facebook.com" or host.endswith(".facebook.com"):
        return any(part in path for part in ("/photo", "/posts/", "/permalink", "/share/p/", "/media/set", "/story.php"))
    if host in {"instagram.com", "www.instagram.com"}:
        return path.startswith(("/p/", "/share/p/"))
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return path.startswith("/post/")
    return False


def is_explicit_photo_url(url):
    parsed = urlsplit(url)
    return "/photo" in parsed.path.lower() or "fbid=" in parsed.query or (
        (parsed.hostname or "").endswith("youtube.com") and parsed.path.startswith("/post/"))


def extract_photo_post(url, cancel=None):
    key = cache_key(url)
    with _cache_lock:
        saved = _cache.get(key)
        if saved and time.monotonic() - saved[0] < 300:
            return copy.deepcopy(saved[1])
    # One retry handles intermittent empty public-page responses from TikTok.
    for attempt in range(2):
        code, output, _ = run_process([sys.executable, "-m", "app.photo_probe"], cancel=cancel,
                                      timeout=100, cwd=ROOT_DIR,
                                      input_data=json.dumps({"url": key[0]}).encode("utf-8"))
        if code:
            raise ValueError("Photo support could not start. Install the project requirements and try again.")
        try:
            payload = json.loads(output)
        except (ValueError, UnicodeError):
            raise ValueError("The photo extractor returned an unreadable response. Please retry.")
        if payload.get("error"):
            if attempt == 0 and "tiktok.com" in (urlsplit(url).hostname or "") and payload["error"].startswith("No accessible photos"):
                continue
            raise ValueError(payload["error"])
        post = payload.get("post")
        if post:
            with _cache_lock:
                if len(_cache) >= 16:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = (time.monotonic(), copy.deepcopy(post))
        return post
