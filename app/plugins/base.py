"""Base media source plugin interface for platform-specific extractors and downloaders."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


class BaseMediaPlugin(ABC):
    """Abstract base class for all platform media plugins."""
    name: str = "Unknown"
    platform_id: str = "unknown"
    badge: str = "Unknown"
    supported_domains: tuple[str, ...] = ()

    def matches_url(self, url: str) -> bool:
        """Check if this plugin handles the given URL based on hostname."""
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self.supported_domains)

    def get_platform_info(self) -> dict[str, str]:
        """Return standardized platform metadata."""
        return {
            "name": self.name,
            "id": self.platform_id,
            "badge": self.badge,
            "type": self.platform_id,
        }

    @abstractmethod
    def extract_info(self, url: str) -> dict[str, Any]:
        """Extract media metadata, streams, qualities, and thumbnails."""
        pass

    @abstractmethod
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
        """Download and convert the requested media."""
        pass

