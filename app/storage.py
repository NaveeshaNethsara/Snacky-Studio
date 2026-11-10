"""Completed-file storage boundary. Cloud APIs never depend on worker disks."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.files import build_content_disposition, resolve_media_file, media_type, list_download_history, format_bytes, PHOTO_EXTENSIONS


class LocalMediaStorage:
    def __init__(self, settings):
        self.directory = settings.downloads_dir

    def response(self, task):
        return self.response_by_name(task["filename"])

    def response_by_name(self, filename):
        try:
            path = resolve_media_file(self.directory, filename)
            return FileResponse(path, stat_result=path.stat(), media_type=media_type(path), headers={
                "Content-Disposition": build_content_disposition(path.name), "Cache-Control": "no-store"})
        except (FileNotFoundError, OSError):
            raise HTTPException(404, "File not found or has been moved")

    def history(self):
        return list_download_history(self.directory)

    def delete(self, filename):
        try:
            resolve_media_file(self.directory, filename).unlink()
        except FileNotFoundError:
            raise HTTPException(404, "File not found")
        except OSError:
            raise HTTPException(409, "The file is in use. Close it and try again.")


class S3MediaStorage:
    def __init__(self, settings, store):
        import boto3
        from botocore.config import Config
        self.settings, self.store = settings, store
        options = {"region_name": settings.s3_region, "config": Config(signature_version="s3v4", s3={"addressing_style": "path"},
                   connect_timeout=5, read_timeout=60, retries={"max_attempts": 3})}
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint or None, **options)
        self.signer = boto3.client("s3", endpoint_url=settings.s3_public_endpoint or settings.s3_endpoint or None, **options)

    def publish(self, task, path: Path):
        tenant = task.get("tenant_id", "default-tenant")
        key = f"media/{tenant}/{task['id']}/{task.get('storage_attempt', task['id'])}/{path.name}"
        self.client.upload_file(str(path), self.settings.s3_bucket, key, ExtraArgs={
            "ContentType": media_type(path), "ContentDisposition": build_content_disposition(path.name)})
        return {"storage_key": key, "size_bytes": path.stat().st_size}

    def remove_object(self, key):
        try:
            self.client.delete_object(Bucket=self.settings.s3_bucket, Key=key)
        except Exception:
            pass

    def response(self, task):
        if not task.get("storage_key") or task.get("deleted_at"):
            raise HTTPException(404, "File not found or has been moved")
        url = self.signer.generate_presigned_url("get_object", Params={"Bucket": self.settings.s3_bucket,
            "Key": task["storage_key"], "ResponseContentDisposition": build_content_disposition(task["filename"])}, ExpiresIn=300)
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})

    def response_by_name(self, filename, *, tenant_id="default-tenant"):
        task = self.store.find_file(filename, tenant_id=tenant_id)
        if not task:
            raise HTTPException(404, "File not found")
        return self.response(task)

    def history(self, *, tenant_id="default-tenant"):
        rows = []
        for task in self.store.completed(tenant_id=tenant_id):
            suffix = Path(task["filename"]).suffix.lower()
            rows.append({"filename": task["filename"], "size_bytes": task.get("size_bytes", 0),
                         "size": format_bytes(task.get("size_bytes", 0)), "created_at": task["completed_at"],
                         "format": suffix[1:].upper(), "kind": "photos" if suffix in PHOTO_EXTENSIONS | {".zip"}
                         else "video" if suffix in {".mp4", ".webm"} else "audio"})
        return rows

    def delete(self, filename, *, tenant_id="default-tenant"):
        task = self.store.find_file(filename, tenant_id=tenant_id)
        if not task:
            raise HTTPException(404, "File not found")
        if hasattr(self.store, "soft_delete_by_filename"):
            self.store.soft_delete_by_filename(filename, tenant_id=tenant_id)
        elif hasattr(self.store, "soft_delete_job"):
            self.store.soft_delete_job(task["id"], tenant_id=tenant_id)
        else:
            self.remove_object(task.get("storage_key", ""))
            import time
            self.store.update(task["id"], tenant_id=tenant_id, deleted_at=time.time())
