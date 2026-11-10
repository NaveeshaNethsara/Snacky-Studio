"""SEO route metadata, sitemap generation, and robots.txt for Snacky Studio."""

import datetime
from xml.sax.saxutils import escape

SEO_ROUTES: dict[str, dict[str, str]] = {
    "/": {
        "title": "Snacky Studio — Free Social Media Video, Audio & Photo Downloader",
        "description": "Download videos, audio, and photos from YouTube, TikTok, Instagram, Facebook & more. Free online video downloader with MP4, MP3, ZIP, and slideshow export. No watermark, no ads.",
        "keywords": "social media video downloader, all in one video downloader, online video downloader free, youtube video downloader, tiktok downloader, instagram downloader, facebook video downloader",
    },
    "/tiktok-slideshow-downloader": {
        "title": "TikTok Slideshow to MP4 Converter & No-Watermark Video Downloader — Snacky Studio",
        "description": "Convert TikTok photo slideshows to MP4 video with original music. Download TikTok videos without watermark in HD. Save TikTok carousel posts with audio.",
        "keywords": "tiktok video downloader without watermark, tiktok photo slideshow to mp4 converter, download tiktok slideshow with music, tiktok carousel downloader with audio, tiktok downloader hd, save tiktok video, convert tiktok photo post to video",
    },
    "/instagram-carousel-downloader": {
        "title": "Instagram Carousel to ZIP & Reels Video Downloader — Snacky Studio",
        "description": "Download all photos from Instagram carousels as a ZIP file. Save Instagram Reels in HD MP4. Extract Instagram photos as lossless PNG. Free IG photo and video saver.",
        "keywords": "instagram carousel downloader zip, download multiple photos from instagram at once, instagram reels video download, ig photo and video saver, instagram downloader, convert social media photo to lossless png",
    },
    "/youtube-video-mp3-downloader": {
        "title": "YouTube Video Downloader 4K MP4 & 320kbps MP3 Audio Extractor — Snacky Studio",
        "description": "Download YouTube videos in 4K, 1080p, 720p MP4. Extract high-quality 320kbps MP3 audio from YouTube. Download YouTube Shorts. Free HD video downloader.",
        "keywords": "youtube video downloader hd, download youtube video mp4, youtube shorts downloader, youtube to mp3 320kbps high quality, extract audio from video online free, download video in 4k 60fps mp4, batch youtube playlist downloader",
    },
    "/facebook-reels-video-downloader": {
        "title": "Facebook HD Video & Reels Downloader — Download FB Videos Free — Snacky Studio",
        "description": "Download Facebook videos in HD quality. Save Facebook Reels as MP4. Download public Facebook group videos. Free FB video downloader with no watermark or ads.",
        "keywords": "facebook video downloader hd, fb reels downloader, download private facebook video, facebook video downloader, fb video download, download facebook reels",
    },
    "/batch-media-downloader": {
        "title": "Batch Link Queue & Self-Hosted Media Downloader — yt-dlp Web UI — Snacky Studio",
        "description": "Download multiple videos at once with a batch queue. Self-hosted Docker media downloader with yt-dlp and gallery-dl web interface. Open-source desktop app with Tauri.",
        "keywords": "batch youtube playlist downloader, multi-link video downloader queue, yt-dlp web ui, gallery-dl web interface, self-hosted social media downloader docker, open source desktop video downloader app, tauri media downloader gui",
    },
}


def inject_seo_meta(html: str, path: str, origin: str) -> str:
    """Replace SEO placeholder tokens in *html* with route-specific metadata.

    Falls back to the ``"/"`` route metadata when *path* is not a known SEO route.
    """
    meta = SEO_ROUTES.get(path, SEO_ROUTES["/"])
    canonical_path = path if path in SEO_ROUTES else "/"

    origin = origin.rstrip("/")

    html = html.replace("__SEO_TITLE__", meta["title"])
    html = html.replace("__SEO_DESCRIPTION__", meta["description"])
    html = html.replace("__SEO_KEYWORDS__", meta["keywords"])
    html = html.replace("__SEO_CANONICAL__", origin + canonical_path)
    html = html.replace("__SEO_OG_URL__", origin + path)
    return html


def generate_sitemap(origin: str) -> str:
    """Return a valid XML sitemap string for all SEO routes."""
    origin = origin.rstrip("/")
    today = datetime.date.today().isoformat()

    urls: list[str] = []
    for path, _meta in SEO_ROUTES.items():
        priority = "1.0" if path == "/" else "0.8"
        urls.append(
            f"  <url>\n"
            f"    <loc>{escape(origin + path)}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            f"  </url>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


def generate_robots_txt(origin: str) -> str:
    """Return a robots.txt string with the sitemap URL derived from *origin*."""
    origin = origin.rstrip("/")
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /events/\n"
        "Disallow: /queue/\n"
        "Disallow: /library/\n"
        "Disallow: /docs\n"
        "Disallow: /openapi.json\n"
        "Disallow: /metrics\n"
        "Disallow: /legacy\n"
        "\n"
        f"Sitemap: {origin}/sitemap.xml\n"
    )
