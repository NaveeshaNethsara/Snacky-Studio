"""Generic fallback media plugin powered by yt-dlp and ffmpeg."""
from pathlib import Path
from typing import Any, Callable

from app.plugins.base import BaseMediaPlugin


class GenericWebMediaPlugin(BaseMediaPlugin):
    name = "Web media"
    platform_id = "generic"
    badge = "Web media"
    supported_domains = ()

    def matches_url(self, url: str) -> bool:
        return True

    def extract_info(self, url: str) -> dict[str, Any]:
        from app.downloader import extract_video_info
        return extract_video_info(url)

    def download(
        self,
        job_id: str,
        url: str,
        media_format: str,
        quality: str,
        downloads_dir: Path,
        progress: Callable[..., None],
        cancel: Any,
        *,
        photo_index: int = 0,
    ) -> dict[str, Any]:
        from app.downloader import download_media
        return download_media(
            job_id,
            url,
            media_format,
            quality,
            downloads_dir,
            progress,
            cancel,
            photo_index=photo_index,
        )

