"""One boundary for library paths and Unicode-safe HTTP filenames."""
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import quote

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
MEDIA_EXTENSIONS = {".mp4", ".mp3", ".m4a", ".webm", ".zip"} | PHOTO_EXTENSIONS


def format_bytes(size: float | None) -> str:
    size = size or 0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_content_disposition(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9 ._-]", "_", Path(filename).stem).strip(" ._")
    suffix = re.sub(r"[^A-Za-z0-9.]", "_", Path(filename).suffix)
    fallback = (stem or "download") + suffix
    encoded = quote(filename, safe="", encoding="utf-8")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def resolve_media_file(directory: Path, filename: str) -> Path:
    # Reject path components instead of silently mapping them to another file.
    safe_name = os.path.basename(filename)
    if safe_name != filename or "\\" in filename or ":" in filename or "\x00" in filename:
        raise FileNotFoundError("File not found")
    root = directory.resolve()
    target = root / safe_name
    if target.suffix.lower() not in MEDIA_EXTENSIONS or target.is_symlink():
        raise FileNotFoundError("File not found")
    if target.resolve().parent != root or not target.is_file():
        raise FileNotFoundError("File not found")
    return target


def media_type(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        return "application/zip"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def list_download_history(directory: Path) -> list[dict]:
    files = []
    for path in directory.iterdir():
        try:
            path = resolve_media_file(directory, path.name)
            stat = path.stat()
        except (FileNotFoundError, OSError):
            continue
        files.append({
            "filename": path.name,
            "size": format_bytes(stat.st_size),
            "size_bytes": stat.st_size,
            "created_at": stat.st_mtime,
            "format": path.suffix[1:].upper(),
            "kind": "photos" if path.suffix.lower() in PHOTO_EXTENSIONS | {".zip"} else "video" if path.suffix.lower() in {".mp4", ".webm"} else "audio",
        })
    return sorted(files, key=lambda file: file["created_at"], reverse=True)

