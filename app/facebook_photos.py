"""Read one Facebook photo, with the official public embed as a fallback."""
import http.cookiejar
import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import get_cookie_file
from app.schemas import InfoRequest


def photo_id(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return None
    value = None
    if parsed.path.rstrip("/") in {"/photo", "/photo.php"}:
        value = (parse_qs(parsed.query).get("fbid") or [None])[0]
    elif "/photos/" in parsed.path:
        value = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return value if value and re.fullmatch(r"\d{1,30}", value) else None


def facebook_asset(url):
    if not isinstance(url, str):
        return False
    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != "https" or not host.endswith(".fbcdn.net") or "static" in host:
        return False
    InfoRequest(url=url)
    return True


class PhotoPage(HTMLParser):
    def __init__(self, target):
        super().__init__(convert_charrefs=True)
        self.target = target
        self.meta, self.blocks, self.images = {}, [], []
        self.anchor, self.author, self.caption = None, "", []
        self.script, self.parts, self.caption_depth = False, [], 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "meta":
            self.meta[attrs.get("property") or attrs.get("name")] = attrs.get("content", "")
        elif tag == "script":
            self.script = attrs.get("type") == "application/json"
            self.parts = []
        elif tag == "a":
            self.anchor = {"href": attrs.get("href", ""), "text": []}
        elif tag == "img" and self.anchor and photo_id(self.anchor["href"]) == self.target:
            # The photo's own link distinguishes it from avatars and related images.
            sources = [(attrs.get("src", ""), 0)]
            for item in attrs.get("srcset", "").split(","):
                parts = item.strip().split()
                if len(parts) == 2 and parts[1].endswith("w") and parts[1][:-1].isdigit():
                    sources.append((parts[0], int(parts[1][:-1])))
            for url, width in sources:
                if facebook_asset(url):
                    self.images.append({"url": url, "width": width or int(attrs.get("width") or 0),
                                        "height": int(attrs.get("height") or 0)})
        elif tag == "img" and self.anchor and not self.author:
            parsed = urlsplit(self.anchor["href"])
            host = (parsed.hostname or "").lower()
            if (host == "facebook.com" or host.endswith(".facebook.com")) and parsed.path.strip("/").count("/") == 0:
                self.author = attrs.get("aria-label") or attrs.get("alt") or ""
        if self.caption_depth:
            if tag not in {"br", "img", "input", "meta", "link", "hr"}:
                self.caption_depth += 1
        elif attrs.get("data-testid") == "post_message" or "userContent" in attrs.get("class", "").split():
            self.caption_depth = 1

    def handle_data(self, data):
        if self.script:
            self.parts.append(data)
        elif self.anchor:
            self.anchor["text"].append(data)
        if self.caption_depth and not self.script:
            self.caption.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script:
            self.script = False
            try:
                self.blocks.append(json.loads("".join(self.parts)))
            except ValueError:
                pass
        elif tag == "a" and self.anchor:
            host = (urlsplit(self.anchor["href"]).hostname or "").lower()
            label = " ".join("".join(self.anchor["text"]).split())
            profile_path = urlsplit(self.anchor["href"]).path.strip("/")
            if not self.author and label and profile_path and "/" not in profile_path and (host == "facebook.com" or host.endswith(".facebook.com")) and not photo_id(self.anchor["href"]):
                self.author = label
            self.anchor = None
        if self.caption_depth and tag not in {"br", "img", "input", "meta", "link", "hr"}:
            self.caption_depth -= 1


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def parse_photo(html, target):
    page = PhotoPage(target)
    page.feed(html)
    images, author, title = [], page.author, " ".join("".join(page.caption).split())
    for block in page.blocks:
        for node in walk(block):
            if str(node.get("id")) != target or node.get("__typename", node.get("__isNode")) != "Photo":
                continue
            owner = node.get("owner") or {}
            author = owner.get("name") or owner.get("username") or author
            story = node.get("creation_story") or {}
            title = (story.get("message") or {}).get("text") or title
            for key in ("image", "photo_image", "viewer_image", "display_image", "image_fullscreen", "images"):
                for image in walk(node.get(key)):
                    url = image.get("uri") or image.get("url")
                    if facebook_asset(url):
                        images.append({"url": url, "width": int(image.get("width") or 0), "height": int(image.get("height") or 0)})
    if not images:
        images = page.images
    if not images and photo_id(page.meta.get("og:url", "")) == target and facebook_asset(page.meta.get("og:image")):
        images = [{"url": page.meta["og:image"], "width": int(page.meta.get("og:image:width") or 0),
                   "height": int(page.meta.get("og:image:height") or 0)}]
        title = page.meta.get("og:title") or title
    if not images:
        return None
    best = max(images, key=lambda item: item["width"] * (item["height"] or 1))
    return {"id": target, "title": (title or f"{author or 'Facebook'} photo")[:500],
            "uploader": author or "Facebook", "photos": [best], "music": None}


def read_page(session, url, params=None):
    with session.get(url, params=params, timeout=15, stream=True) as response:
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                raise ValueError("Facebook returned an oversized page. Please try another photo link.")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")


def extract_facebook_photo(url):
    target = photo_id(url)
    if not target:
        return None
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                                "Accept-Language": "en-US,en;q=0.5"})
        session.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=.5, status_forcelist=[429, 500, 502, 503, 504])))
        if cookies := get_cookie_file():
            jar = http.cookiejar.MozillaCookieJar(cookies)
            jar.load(ignore_discard=True, ignore_expires=False)
            session.cookies.update(jar)
        try:
            post = parse_photo(read_page(session, url), target)
        except requests.RequestException:
            post = None
        if post:
            return post
        # Facebook exposes public photo posts through its official embed without login.
    # Keep the public embed independent of cookies set by a login-shell response.
    with requests.Session() as public_session:
        public_session.headers["User-Agent"] = "Mozilla/5.0"
        public_session.mount("https://", HTTPAdapter(max_retries=Retry(total=1, backoff_factor=.5,
            status_forcelist=[429, 500, 502, 503, 504])))
        post = parse_photo(read_page(public_session, "https://www.facebook.com/plugins/post.php",
                                     {"href": url, "show_text": "true", "width": "500"}), target)
        if post:
            return post
    raise ValueError("Facebook did not expose this photo. Check that it is public and available, or use an authorized login session.")
