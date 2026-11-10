"""Read images attached to one public YouTube community post."""
import http.cookiejar
import json
import os
import re
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.config import get_cookie_file
from app.schemas import InfoRequest


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def parse_post(data, post_id):
    post = next((item for item in walk(data) if item.get("postId") == post_id and item.get("backstageAttachment")), None)
    if not post:
        raise ValueError("No accessible images were found in this YouTube post. Text, polls, and members-only posts are not photo downloads.")
    attachment = post["backstageAttachment"]
    multi = attachment.get("postMultiImageRenderer") or {}
    images = multi.get("images") or ([attachment] if attachment.get("backstageImageRenderer") else [])
    photos = []
    for image in images:
        renderer = image.get("backstageImageRenderer") or image
        thumbnails = (renderer.get("image") or {}).get("thumbnails") or []
        if not thumbnails:
            raise ValueError("One of this post's photos is unavailable. No partial collection was saved.")
        thumbnail = max(thumbnails, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
        url = thumbnail.get("url") or ""
        if url.startswith("//"):
            url = "https:" + url
        # Google's image service uses '=s0' for the uncropped original.
        host = (urlsplit(url).hostname or "").lower()
        if host == "yt3.ggpht.com" or host == "googleusercontent.com" or host.endswith(".googleusercontent.com"):
            url = url.split("=", 1)[0] + "=s0"
        photos.append({"url": url, "width": thumbnail.get("width") or 0, "height": thumbnail.get("height") or 0})
        InfoRequest(url=url)
        if len(photos) > 200:
            raise ValueError("This post exceeds the 200-photo limit. No partial collection was saved.")
    if not photos:
        raise ValueError("This community post does not contain downloadable photos.")
    content = post.get("contentText") or {}
    title = content.get("simpleText") or "".join(run.get("text", "") for run in content.get("runs", []))
    author = post.get("authorText") or {}
    uploader = author.get("simpleText") or "".join(run.get("text", "") for run in author.get("runs", []))
    return {"id": post_id, "title": title[:500] or "YouTube photo post", "uploader": uploader or "YouTube",
            "photos": photos, "music": None}


def extract_youtube_post(url):
    match = re.match(r"/post/([A-Za-z0-9_-]+)", urlsplit(url).path)
    if not match:
        return None
    post_id = match[1]
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=.5,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods={"GET"})))
        if cookie_file := get_cookie_file():
            jar = http.cookiejar.MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=False)
            session.cookies.update(jar)
        response = session.get(f"https://www.youtube.com/post/{post_id}?hl=en", timeout=20,
                               headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.5"})
        response.raise_for_status()
        html = response.text
    start = re.search(r'(?:var\s+ytInitialData|window\["ytInitialData"\]|ytInitialData)\s*=\s*', html)
    if not start:
        raise ValueError("YouTube did not return this post's data. It may require login or be unavailable.")
    try:
        data, _ = json.JSONDecoder().raw_decode(html[start.end():])
    except ValueError:
        raise ValueError("Could not read YouTube's post data. Please retry.")
    return parse_post(data, post_id)
