"""X / Twitter platform media plugin."""
from pathlib import Path
from typing import Any, Callable

from app.plugins.base import BaseMediaPlugin


class TwitterPlugin(BaseMediaPlugin):
    name = "X / Twitter"
    platform_id = "twitter"
    badge = "X / Twitter"
    supported_domains = ("twitter.com", "x.com")

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

