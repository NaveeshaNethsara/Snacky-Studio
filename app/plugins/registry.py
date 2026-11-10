"""Media plugin registry and dispatcher."""
from typing import Optional
from app.plugins.base import BaseMediaPlugin


class MediaPluginRegistry:
    def __init__(self):
        self._plugins: list[BaseMediaPlugin] = []
        self._fallback: Optional[BaseMediaPlugin] = None

    def register(self, plugin: BaseMediaPlugin, *, fallback: bool = False):
        if fallback:
            self._fallback = plugin
        else:
            self._plugins.append(plugin)

    def get_plugin(self, url: str) -> BaseMediaPlugin:
        for plugin in self._plugins:
            if plugin.matches_url(url):
                return plugin
        if self._fallback:
            return self._fallback
        raise ValueError(f"No media plugin registered to handle: {url}")

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "id": p.platform_id,
                "domains": list(p.supported_domains),
            }
            for p in self._plugins
        ]


_registry = MediaPluginRegistry()


def get_default_registry() -> MediaPluginRegistry:
    return _registry

