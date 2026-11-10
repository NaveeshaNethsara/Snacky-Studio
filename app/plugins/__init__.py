"""Media source plugin architecture for Snacky Studio."""
from app.plugins.base import BaseMediaPlugin
from app.plugins.facebook import FacebookPlugin
from app.plugins.generic import GenericWebMediaPlugin
from app.plugins.instagram import InstagramPlugin
from app.plugins.registry import MediaPluginRegistry, get_default_registry
from app.plugins.tiktok import TikTokPlugin
from app.plugins.twitter import TwitterPlugin
from app.plugins.youtube import YouTubePlugin

# Pre-populate default registry
registry = get_default_registry()
registry.register(YouTubePlugin())
registry.register(InstagramPlugin())
registry.register(TikTokPlugin())
registry.register(FacebookPlugin())
registry.register(TwitterPlugin())
registry.register(GenericWebMediaPlugin(), fallback=True)

__all__ = [
    "BaseMediaPlugin",
    "MediaPluginRegistry",
    "get_default_registry",
    "YouTubePlugin",
    "InstagramPlugin",
    "TikTokPlugin",
    "FacebookPlugin",
    "TwitterPlugin",
    "GenericWebMediaPlugin",
]

