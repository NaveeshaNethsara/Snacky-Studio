"""Single-post gallery-dl adapter, run in its own process to isolate config."""
import html
import json
import logging
import os
import re
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urljoin, urlsplit

from gallery_dl import config, exception, output
from gallery_dl.extractor.facebook import FacebookPhotoExtractor, FacebookSetExtractor
from gallery_dl.extractor.tiktok import TiktokPostExtractor
from gallery_dl.extractor.instagram import InstagramPostExtractor
from gallery_dl.extractor.message import Message
import requests

from app.config import get_cookie_file
from app.schemas import InfoRequest
from app.youtube_photos import extract_youtube_post
from app.facebook_photos import extract_facebook_photo, facebook_asset, photo_id, walk
from app.instagram_photos import extract_instagram_post

MAX_PHOTOS = 200


def get_post_photo_ids(html):
    photo_ids = []
    for s in re.findall(r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, flags=re.DOTALL):
        if "album" in s and "media" in s:
            try:
                data = json.loads(s)
                for node in walk(data):
                    if isinstance(node, dict) and "album" in node:
                        album = node["album"]
                        if isinstance(album, dict) and "media" in album:
                            media = album["media"]
                            if isinstance(media, dict) and "edges" in media:
                                for edge in media["edges"]:
                                    if isinstance(edge, dict) and "node" in edge:
                                        nid = edge["node"].get("id")
                                        if nid and str(nid) not in photo_ids:
                                            photo_ids.append(str(nid))
            except Exception:
                pass
    return photo_ids


def extract_image_dimensions(html, target_url):
    for s in re.findall(r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, flags=re.DOTALL):
        if "image" in s and "uri" in s:
            try:
                data = json.loads(s)
                for node in walk(data):
                    if isinstance(node, dict) and "image" in node and isinstance(node["image"], dict):
                        img = node["image"]
                        if img.get("uri") and img.get("width") and img.get("height"):
                            fn = target_url.split("/")[-1].split("?")[0]
                            if fn in img["uri"]:
                                return int(img["width"]), int(img["height"])
            except Exception:
                pass
    return 0, 0


def extract_meta_photo(html_text):
    og_img = re.search(r'property="og:image"\s+content="([^"]+)"', html_text)
    if not og_img:
        return None
    img_url = og_img.group(1).replace("&amp;", "&")
    if not facebook_asset(img_url):
        return None
    dim_match = re.search(r'cstp=mx(\d+)x(\d+)', img_url)
    width, height = (int(dim_match.group(1)), int(dim_match.group(2))) if dim_match else (0, 0)
    if width and height and "ctp=p" in img_url:
        img_url = re.sub(r"ctp=p\d+x\d+", f"ctp=s{width}x{height}", img_url)

    og_title = re.search(r'property="og:title"\s+content="([^"]+)"', html_text)
    og_desc = re.search(r'property="og:description"\s+content="([^"]+)"', html_text)

    title = html.unescape(og_desc.group(1) if og_desc else (og_title.group(1) if og_title else "Photo post"))
    uploader = html.unescape(og_title.group(1) if og_title else "Facebook")
    pid_match = re.search(r'_(\d{10,25})_', img_url)
    pid = pid_match.group(1) if pid_match else "photo"

    return {
        "id": pid,
        "url": img_url,
        "width": width,
        "height": height,
        "caption": title,
        "title": title,
        "post_text": title,
        "user": uploader,
        "username": uploader,
        "num": 1,
    }


def safe_facebook_photo_items(self):
    photo_id = self.groups[0]
    photo_url = f"{self.root}/photo/?fbid={photo_id}&set="
    photo_page = self.photo_page_request_wrapper(photo_url).text

    photo = self.parse_photo_page(photo_page)
    photo["num"] = 1

    if photo.get("set_id"):
        set_url = f"{self.root}/media/set/?set={photo['set_id']}"
        try:
            set_page = self.request(set_url).text
            directory = self.parse_set_page(set_page)
            for key in ("set_id", "title", "user_id", "user_pfbid", "username"):
                if not directory.get(key):
                    directory[key] = photo.get(key)
            photo.update(directory)
        except Exception:
            pass

    if photo.get("url"):
        yield Message.Directory, "", photo
        yield Message.Url, photo["url"], photo


FacebookPhotoExtractor.items = safe_facebook_photo_items


def safe_facebook_set_items(self):
    set_id, path, first_pid, set_id2, pcb1, pcb2, pcb3 = self.groups
    if not set_id:
        set_id = set_id2

    post = None
    post_page = ""
    if path:
        post_url = f"{self.root}/{path}"
        try:
            post_page = self.request(post_url).text
            post = self.parse_post_page(post_page)
            set_id = post.get("set_id")
        except Exception:
            pass

        if not set_id:
            parts = path.strip("/").split("/")
            last_part = parts[-1] if parts else ""
            if last_part.startswith("pfbid") or last_part.isdigit():
                set_id = f"pcb.{last_part}"

    elif not set_id:
        set_id = "pcb." + (pcb1 or pcb2 or pcb3)

    set_page = ""
    set_data = {}
    if set_id and set_id != "pcb.":
        set_url = f"{self.root}/media/set/?set={set_id}"
        try:
            set_page = self.request(set_url).text
            set_data = self.parse_set_page(set_page)
        except Exception:
            pass

    if first_pid:
        set_data["first_photo_id"] = first_pid
    if post:
        set_data.update(post)

    if set_id and set_id.startswith("pcb."):
        # A Facebook post container (pcb.) is a single post, not an album.
        # Facebook's photo viewer 'nextMedia' links to the next post on the user's feed,
        # which causes an unbounded crawl across the user's entire history.
        # Restrict extraction strictly to the photo(s) belonging to this post container.
        pids = get_post_photo_ids(set_page) or get_post_photo_ids(post_page)
        if not pids and set_data.get("first_photo_id"):
            pids = [set_data["first_photo_id"]]

        if pids:
            def extract_post_photos():
                for i, pid in enumerate(pids):
                    photo_url = f"{self.root}/photo/?fbid={pid}&set={set_id}"
                    try:
                        photo_page = self.photo_page_request_wrapper(photo_url).text
                        photo = self.parse_photo_page(photo_page)
                    except Exception:
                        continue
                    photo["num"] = i + 1
                    w, h = extract_image_dimensions(photo_page, photo.get("url") or "")
                    if w and h:
                        photo["width"] = w
                        photo["height"] = h
                    if photo.get("url"):
                        photo.update(set_data)
                        yield Message.Directory, "", photo
                        yield Message.Url, photo["url"], photo

            return extract_post_photos()

    # Fallback to meta tags if set extraction returned no photos
    meta_photo = extract_meta_photo(post_page) or extract_meta_photo(set_page)
    if meta_photo:
        def yield_meta():
            for k, v in set_data.items():
                if v and k not in ("width", "height"):
                    meta_photo[k] = v
            yield Message.Directory, "", meta_photo
            yield Message.Url, meta_photo["url"], meta_photo

        return yield_meta()

    if set_id and not set_id.startswith("pcb."):
        return self.extract_set(set_data)

    def empty_gen():
        if False:
            yield

    return empty_gen()


FacebookSetExtractor.items = safe_facebook_set_items


def resolve_post_url(url):
    parsed = urlsplit(url)
    if parsed.path == "/story.php" and parsed.hostname and parsed.hostname.endswith("facebook.com"):
        params = parse_qs(parsed.query)
        if params.get("story_fbid") and params.get("id"):
            return f"https://www.facebook.com/{params['id'][0]}/posts/{params['story_fbid'][0]}"
    host = (urlsplit(url).hostname or "").lower()
    short = host in {"vm.tiktok.com", "vt.tiktok.com"} or "/share/" in urlsplit(url).path
    if not short:
        return url
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        for _ in range(6):
            InfoRequest(url=url)
            current_host = (urlsplit(url).hostname or "").lower()
            if not any(current_host == domain or current_host.endswith("." + domain)
                       for domain in ("tiktok.com", "facebook.com", "instagram.com")):
                raise ValueError("The shared link did not resolve to a supported post.")
            response = session.get(url, allow_redirects=False, timeout=15, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                response.raise_for_status()
                return url
            finally:
                response.close()
    raise ValueError("The shared link redirected too many times. Paste its full post URL.")


def collect_post(extractor):
    photos, seen, music, metadata = [], set(), None, {}
    for message in extractor:
        if message[0] == Message.Directory:
            metadata = dict(message[2])
            if metadata.get("post_type") == "video":
                return None
        elif message[0] == Message.Url:
            url, data = message[1], message[2]
            kind = data.get("type") or ("audio" if data.get("audio_url") else "video" if data.get("video_url") else None)
            if kind == "video":
                continue  # A mixed Facebook set's videos are not photos.
            if kind == "audio":
                if extractor.category == "tiktok":
                    music_data = data.get("music") or {}
                    music = {"url": url, "title": music_data.get("title") or "Original music",
                             "author": music_data.get("authorName") or "", "duration": data.get("duration") or 0}
                elif extractor.category == "instagram":
                    music = {
                        "url": url,
                        "title": data.get("audio_title") or metadata.get("audio_title") or "Original audio",
                        "author": data.get("audio_artist") or data.get("audio_user") or metadata.get("audio_artist") or "",
                        "duration": data.get("audio_duration") or metadata.get("audio_duration") or 0,
                    }
                continue
            if kind not in {None, "image", "photo"}:
                continue
            identity = str(data.get("id") or url) if extractor.category == "facebook" else url
            if identity in seen:
                continue
            if len(photos) >= MAX_PHOTOS:
                raise ValueError(f"This post exceeds the {MAX_PHOTOS}-photo limit. No partial collection was saved.")
            InfoRequest(url=url)
            seen.add(identity)
            photos.append({"url": url, "width": data.get("width") or 0, "height": data.get("height") or 0})
            metadata.update({key: data[key] for key in ("title", "caption", "post_text", "description", "user", "username", "id", "post_id") if data.get(key)})
    if not photos:
        raise ValueError("No accessible photos were found. Use a public photo/post link, or an authorized cookies file if login is required.")
    user = metadata.get("user") or metadata.get("username") or extractor.category
    if isinstance(user, dict):
        user = user.get("username") or user.get("full_name") or extractor.category
    return {"id": str(metadata.get("post_id") or metadata.get("id") or metadata.get("set_id") or ""),
            "title": str(metadata.get("post_text") or metadata.get("caption") or metadata.get("description") or metadata.get("title") or "Photo post")[:500],
            "uploader": str(user),
            "photos": photos, "music": music}


def probe(url):
    # Do not load personal gallery-dl config, browser cookies, or persistent cache.
    config.set(("cache",), "file", ":memory:")
    for key, value in {"timeout": 15, "retries": 1, "fallback-retries": 0,
                       "cookies-update": False, "author-followups": False, "audio": True,
                       "photos": True, "covers": False, "subtitles": False}.items():
        config.set(("extractor",), key, value)
    cookies = get_cookie_file()
    if cookies:
        config.set(("extractor",), "cookies", cookies)
    url = resolve_post_url(url)
    if photo_id(url):
        return extract_facebook_photo(url)
    if (urlsplit(url).hostname or "").rstrip(".") in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return extract_youtube_post(url)
    host = (urlsplit(url).hostname or "").rstrip(".")
    if host in {"instagram.com", "www.instagram.com", "instagr.am"}:
        return extract_instagram_post(url)
    extractor = next((found for cls in (TiktokPostExtractor, FacebookPhotoExtractor, FacebookSetExtractor, InstagramPostExtractor)
                      if (found := cls.from_url(url))), None)
    if extractor is None:
        return None
    extractor.log = output.LoggerAdapter(extractor.log, SimpleNamespace(_logger_extra={}))
    try:
        return collect_post(extractor)
    finally:
        if extractor.session is not None:
            extractor.session.close()


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    try:
        data = json.loads(sys.stdin.read())
        result = {"post": probe(InfoRequest(url=data["url"]).url)}
    except exception.AuthorizationError:
        result = {"error": "This post requires login or is private. Only an account authorized to view it can download it."}
    except requests.exceptions.RequestException:
        result = {"error": "The connection was interrupted while reading this photo post. Please retry."}
    except Exception as exc:
        logging.error("Photo extraction failed: %s", type(exc).__name__)
        result = {"error": str(exc) if isinstance(exc, ValueError) else
                  "Could not read this photo post. It may be unavailable, require login, or be blocked by the platform."}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
