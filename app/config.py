"""Configuration for local desktop and shared private cloud workspaces."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def get_cookie_file() -> str | None:
    if cookies := os.getenv("SNACKY_COOKIES_FILE"):
        if Path(cookies).is_file():
            return cookies
    for candidate in (
        ROOT_DIR / ".snacky" / "cookies.txt",
        ROOT_DIR / "cookies.txt",
        ROOT_DIR / "downloads" / "cookies.txt",
    ):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate)
    return None


@dataclass(frozen=True)
class Settings:
    downloads_dir: Path = field(default_factory=lambda: Path(os.getenv("SNACKY_DOWNLOADS_DIR", str(ROOT_DIR / "downloads"))))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("SNACKY_DATA_DIR", str(ROOT_DIR / ".snacky"))))
    static_dir: Path = ROOT_DIR / "app" / "static"
    web_dir: Path = ROOT_DIR / "app" / "web"
    max_workers: int = 2
    max_queued: int = 8
    mode: str = field(default_factory=lambda: os.getenv("SNACKY_MODE", "local"))
    database_url: str = field(default_factory=lambda: os.getenv("SNACKY_DATABASE_URL", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("SNACKY_REDIS_URL", "redis://127.0.0.1:6379/0"))
    public_origin: str = field(default_factory=lambda: os.getenv("SNACKY_PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/"))
    cloud_password: str = field(default_factory=lambda: os.getenv("SNACKY_CLOUD_PASSWORD", ""))
    cloud_password_hash: str = field(default_factory=lambda: os.getenv("SNACKY_CLOUD_PASSWORD_HASH", ""))
    trusted_proxies: str = field(default_factory=lambda: os.getenv("SNACKY_TRUSTED_PROXIES", "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"))
    session_secret: str = field(default_factory=lambda: os.getenv("SNACKY_SESSION_SECRET", ""))
    s3_endpoint: str = field(default_factory=lambda: os.getenv("SNACKY_S3_ENDPOINT", ""))
    s3_public_endpoint: str = field(default_factory=lambda: os.getenv("SNACKY_S3_PUBLIC_ENDPOINT", ""))
    s3_bucket: str = field(default_factory=lambda: os.getenv("SNACKY_S3_BUCKET", "snacky-media"))
    s3_region: str = field(default_factory=lambda: os.getenv("SNACKY_S3_REGION", "us-east-1"))
    max_cloud_jobs: int = 100
    job_lease_seconds: int = 120
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")).rstrip("/"))
    supabase_publishable_key: str = field(default_factory=lambda: os.getenv("SUPABASE_PUBLISHABLE_KEY", os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")))
    supabase_jwt_secret: str = field(default_factory=lambda: os.getenv("SUPABASE_JWT_SECRET", ""))
    owner_email: str = field(default_factory=lambda: os.getenv("SNACKY_OWNER_EMAIL", "").strip().lower())

    def validate(self):
        if self.mode not in {"local", "cloud"}:
            raise ValueError("SNACKY_MODE must be local or cloud")
        if self.mode == "cloud":
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Cloud mode requires SNACKY_DATABASE_URL for PostgreSQL")
            has_password = bool(self.cloud_password and len(self.cloud_password) >= 16)
            has_hash = bool(self.cloud_password_hash and self.cloud_password_hash.startswith("$argon2"))
            if not (has_password or has_hash) or len(self.session_secret) < 32:
                raise ValueError("Cloud mode requires a password of at least 16 characters (or valid SNACKY_CLOUD_PASSWORD_HASH) and a session secret of at least 32 characters")
            from urllib.parse import urlsplit
            origin = urlsplit(self.public_origin)
            if origin.scheme not in {"http", "https"} or not origin.hostname or origin.path or origin.query or origin.fragment:
                raise ValueError("SNACKY_PUBLIC_ORIGIN must be an HTTP(S) origin without a path")
            if origin.scheme != "https" and origin.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("Remote cloud deployments require HTTPS")

    def prepare(self):
        self.validate()
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

