"""Validate input before it reaches yt-dlp or the filesystem."""
import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class InfoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = str(HttpUrl(value.strip()))
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".").lower()
        if parsed.username or parsed.password:
            raise ValueError("Links containing login credentials are not supported.")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError("Use a public media link.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("Use a public media link.")
        return value


class DownloadRequest(InfoRequest):
    format: Literal["mp4", "mp3", "photos", "slideshow", "photo", "png"] = "mp4"
    quality: str = Field(default="best", min_length=1, max_length=8)
    photo_index: int = Field(default=0, ge=0, le=199)
    title: str = Field(default="", max_length=200)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Use a valid Unicode media title.")
        return value

    @model_validator(mode="after")
    def validate_quality(self):
        if self.photo_index and self.format not in {"photo", "png"}:
            raise ValueError("Choose an individual photo to use a photo index.")
        if self.format in {"photos", "photo", "png"}:
            if self.quality != "best":
                raise ValueError("Photo downloads keep the original files; choose original quality.")
        elif self.format == "slideshow":
            if self.quality not in {"best", "720", "1080"}:
                raise ValueError("Choose 720p or 1080p for a slideshow.")
        elif self.format == "mp3":
            if self.quality == "best":
                self.quality = "320"
            if self.quality not in {"128", "192", "256", "320"}:
                raise ValueError("Choose an MP3 bitrate of 128, 192, 256, or 320 kbps.")
        elif self.quality != "best":
            if not self.quality.isascii() or not self.quality.isdigit() or not 1 <= int(self.quality) <= 4320:
                raise ValueError("Choose original quality or a video resolution up to 4320p.")
        return self


def is_ssrf_safe_url(url: str) -> bool:
    """Validate that the URL is a safe public media link."""
    try:
        InfoRequest.validate_url(url)
        return True
    except Exception:
        return False


def is_cloud_source_allowed(url: str) -> bool:
    """Check if the domain is supported and allowed in cloud mode."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    allowed_domains = (
        "youtube.com", "youtu.be",
        "instagram.com", "instagr.am",
        "tiktok.com",
        "facebook.com", "fb.watch", "fb.com",
        "twitter.com", "x.com",
    )
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    format: Literal["mp4", "mp3", "photos", "slideshow", "photo", "png"] = "mp4"
    quality: str = "best"
    title: str = ""
    photo_index: int = 0


class BatchDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    urls: list[str] = Field(default_factory=list, max_length=50)
    items: list[BatchItem] = Field(default_factory=list, max_length=50)
    format: Literal["mp4", "mp3", "photos", "slideshow", "photo", "png"] = "mp4"
    quality: str = "best"


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default_format: Literal["mp4", "mp3", "photos", "slideshow"] = "mp4"
    default_quality: str = "best"
    default_audio_bitrate: str = "320"
    theme: Literal["system", "dark", "light"] = "system"
    language: Literal["en", "es"] = "en"
    auto_download: bool = True

