"""Read photos and music from an Instagram post or carousel."""
import json
import re
from urllib.parse import urlsplit

import yt_dlp
from app.config import get_cookie_file
from app.schemas import InfoRequest


def instagram_shortcode(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in {"instagram.com", "www.instagram.com", "instagr.am"}:
        return None
    match = re.search(r'/(?:p|share/p|reel|reels|tv)/([A-Za-z0-9_-]+)', parsed.path)
    return match.group(1) if match else None


def find_instagram_audio(obj):
    if not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        # Look for audio asset with progressive_download_url
        url = obj.get("progressive_download_url")
        if url and isinstance(url, str) and url.startswith("http"):
            title = obj.get("title") or obj.get("original_audio_title") or "Original audio"
            author = obj.get("display_artist") or obj.get("ig_artist") or obj.get("artist_name") or ""
            duration = float(obj.get("duration_in_ms") or 0) / 1000.0 if obj.get("duration_in_ms") else float(obj.get("duration") or 0)
            return {"url": url, "title": str(title), "author": str(author), "duration": duration}

        for key in ("music_asset_info", "original_sound_info", "music_info", "clips_metadata", "music_metadata", "audio"):
            if key in obj and isinstance(obj[key], (dict, list)):
                found = find_instagram_audio(obj[key])
                if found:
                    return found
        for val in obj.values():
            if isinstance(val, (dict, list)):
                found = find_instagram_audio(val)
                if found:
                    return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_instagram_audio(item)
            if found:
                return found
    return None


def extract_instagram_post(url):
    shortcode = instagram_shortcode(url)
    if not shortcode:
        return None

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    cookie_file = get_cookie_file()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    ydl = yt_dlp.YoutubeDL(ydl_opts)
    ie = yt_dlp.extractor.instagram.InstagramIE(ydl)
    ie.initialize()

    captured = {}
    orig_extract_product = ie._extract_product

    def hook_extract_product(product_info, *args, **kwargs):
        captured["product_info"] = product_info
        return orig_extract_product(product_info, *args, **kwargs)

    ie._extract_product = hook_extract_product

    canonical_url = f"https://www.instagram.com/p/{shortcode}/"
    res = None
    try:
        res = ie.extract(canonical_url)
    except Exception as exc:
        msg = str(exc)
        if any(term in msg.lower() for term in ("login", "cookies", "checkpoint", "rate-limit")):
            raise ValueError("This Instagram post requires login or is private. If you have access, add a cookies.txt file to the application directory to download it.") from exc
        # If extraction failed because of something else, re-raise as ValueError
        raise ValueError("Could not read this Instagram photo post. It may be unavailable or restricted.") from exc

    product_info = captured.get("product_info") or {}

    # Check if this is a video-only post (e.g. single video/reel) without any photos
    media_type = product_info.get("media_type")
    is_carousel = bool(product_info.get("carousel_media"))
    if media_type == 2 and not is_carousel:
        # Single video post / reel: return None so downloader.py processes it as video
        return None

    photos = []
    seen_urls = set()

    items = product_info.get("carousel_media") or ([product_info] if product_info else [])
    for item in items:
        # If item has video_versions and no image candidates, skip video items in mixed carousel
        item_type = item.get("media_type")
        if item_type == 2 and not item.get("image_versions2") and not item.get("display_uri"):
            continue

        candidates = (item.get("image_versions2") or {}).get("candidates") or []
        display_uri = item.get("display_uri")

        best_url = None
        best_w = int(item.get("original_width") or 0)
        best_h = int(item.get("original_height") or 0)

        if candidates:
            # First candidate is typically the highest quality
            best_url = candidates[0].get("url")
            if candidates[0].get("width") and candidates[0].get("height"):
                best_w = int(candidates[0]["width"])
                best_h = int(candidates[0]["height"])
        elif display_uri:
            best_url = display_uri

        if best_url and best_url not in seen_urls:
            seen_urls.add(best_url)
            InfoRequest(url=best_url)
            photos.append({"url": best_url, "width": best_w, "height": best_h})

    if not photos and res:
        # Fallback to thumbnails from yt-dlp extracted entries
        entries = res.get("entries") or ([res] if res else [])
        for entry in entries:
            # If entry has formats (video), check if it's purely a video
            if entry.get("formats") and not entry.get("thumbnails"):
                continue
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                best_thumb = max(thumbs, key=lambda t: int(t.get("width") or 0) * int(t.get("height") or 0) if t.get("width") else len(t.get("url", "")))
                url_t = best_thumb.get("url")
                if url_t and url_t not in seen_urls:
                    seen_urls.add(url_t)
                    InfoRequest(url=url_t)
                    photos.append({"url": url_t, "width": best_thumb.get("width") or 0, "height": best_thumb.get("height") or 0})

    if not photos:
        # If no photos found, it's either a video post or has no media
        if res and (res.get("formats") or any(e.get("formats") for e in (res.get("entries") or []))):
            return None
        raise ValueError("No accessible photos were found in this Instagram post.")

    # Extract audio/music if present
    music = find_instagram_audio(product_info) or (find_instagram_audio(res) if res else None)
    if music and music.get("url"):
        InfoRequest(url=music["url"])

    caption = product_info.get("caption")
    title = ""
    if isinstance(caption, dict):
        title = caption.get("text") or ""
    elif isinstance(caption, str):
        title = caption
    elif res:
        title = res.get("description") or res.get("title") or ""
    title = (title or "Instagram photo post").strip()

    uploader = (
        (product_info.get("user") or {}).get("username")
        or (product_info.get("user") or {}).get("full_name")
        or (res.get("channel") if res else None)
        or (res.get("uploader") if res else None)
        or "Instagram"
    )

    return {
        "id": shortcode,
        "title": title[:500],
        "uploader": str(uploader),
        "photos": photos,
        "music": music,
    }

