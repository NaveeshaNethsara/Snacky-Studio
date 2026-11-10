"""Thin HTTP routes; filesystem, media operations, RBAC, and multi-tenant boundaries."""
import asyncio
import inspect
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.auth import get_client_ip, get_current_user, require_role
from app.browser_downloads import browser_response
from app.downloader import extract_video_info, sanitize_error_message
from app.files import build_content_disposition, list_download_history, media_type, resolve_media_file
from app.jobs import QueueFullError, TERMINAL_STATUSES
from app.quotas import check_tenant_quota, get_quota_summary, get_today_utc
from app.schemas import BatchDownloadRequest, BatchItem, DownloadRequest, InfoRequest, UserPreferences

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


async def get_task(request: Request, job_id: UUID | str, *, tenant_id: str | None = None):
    manager = request.app.state.jobs
    sig = inspect.signature(manager.store.get)
    if "tenant_id" in sig.parameters:
        task = await asyncio.to_thread(manager.store.get, str(job_id), tenant_id=tenant_id)
    else:
        task = await asyncio.to_thread(manager.store.get, str(job_id))
    if not task:
        raise HTTPException(404, "Download task not found")
    return with_ownership(manager, task)


def with_ownership(manager, task):
    return {**task, "managed_here": task["status"] in TERMINAL_STATUSES or manager.owns(task["id"])}


def file_response(settings, filename):
    try:
        path = resolve_media_file(settings.downloads_dir, filename)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "File not found or has been moved")
    return FileResponse(path, media_type=media_type(path), headers={"Content-Disposition": build_content_disposition(path.name)})


@router.get("/health")
async def health(request: Request):
    settings = request.app.state.settings
    return {
        "status": "ok",
        "application": "snacky-studio",
        "version": "3.0.0",
        "mode": settings.mode,
        "max_workers": settings.max_workers,
        "max_queued": settings.max_cloud_jobs if settings.mode == "cloud" else settings.max_queued,
    }


def validate_source(settings, url):
    if settings.mode != "cloud":
        return
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    allowed = (
        "youtube.com", "youtu.be", "instagram.com", "instagr.am",
        "tiktok.com", "facebook.com", "fb.com", "fb.watch", "twitter.com", "x.com"
    )
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise HTTPException(400, "Cloud mode accepts YouTube, Instagram, TikTok, Facebook, and X links.")


@router.post("/info")
async def get_info(body: InfoRequest, request: Request):
    validate_source(request.app.state.settings, body.url)
    try:
        async with request.app.state.analysis_slots:
            work = asyncio.create_task(asyncio.to_thread(extract_video_info, body.url))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await work
                raise
    except Exception as exc:
        clean_msg = sanitize_error_message(exc, body.url)
        logger.info("Media analysis failed: %s", clean_msg)
        raise HTTPException(400, clean_msg)


@router.post("/download")
async def start_download(body: DownloadRequest, request: Request):
    validate_source(request.app.state.settings, body.url)
    user = get_current_user(request)
    if user.get("role") == "viewer":
        raise HTTPException(403, "Viewers are not permitted to submit download jobs.")

    tenant_id = user.get("tenant_id", "default-tenant")
    user_id = user.get("user_id")

    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    redis_client = getattr(manager, "redis", None)
    if store and hasattr(store, "get_tenant"):
        check_tenant_quota(store, redis_client, tenant_id, user, target_url=body.url)

    try:
        sig = inspect.signature(request.app.state.jobs.start)
        if "tenant_id" in sig.parameters:
            job_id = await asyncio.to_thread(
                request.app.state.jobs.start,
                body.url,
                body.format,
                body.quality,
                body.photo_index,
                body.title,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        else:
            job_id = await asyncio.to_thread(
                request.app.state.jobs.start,
                body.url,
                body.format,
                body.quality,
                body.photo_index,
                body.title,
            )

        if store and hasattr(store, "increment_tenant_job_count"):
            store.increment_tenant_job_count(tenant_id, get_today_utc())

        if hasattr(request.app.state.jobs, "store") and hasattr(request.app.state.jobs.store, "record_audit"):
            client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
            domain = (urlsplit(body.url).hostname or "").lower()
            request.app.state.jobs.store.record_audit(
                tenant_id,
                user_id,
                user.get("email"),
                "job.create",
                client_ip,
                "success",
                target_type="job",
                target_id=job_id,
                details={"format": body.format, "quality": body.quality, "domain": domain},
            )

        return {"download_id": job_id, "status": "started", "task": await get_task(request, job_id, tenant_id=tenant_id)}
    except QueueFullError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "5"})


@router.post("/batch")
async def start_batch_download(body: BatchDownloadRequest, request: Request):
    user = get_current_user(request)
    if user.get("role") == "viewer":
        raise HTTPException(403, "Viewers are not permitted to submit download jobs.")

    items_to_process: list[BatchItem] = []
    if body.items:
        items_to_process = body.items
    elif body.urls:
        items_to_process = [
            BatchItem(url=u.strip(), format=body.format, quality=body.quality)
            for u in body.urls
            if u.strip()
        ]

    if not items_to_process:
        raise HTTPException(400, "Provide at least one valid media URL for batch download.")

    tenant_id = user.get("tenant_id", "default-tenant")
    user_id = user.get("user_id")
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    redis_client = getattr(manager, "redis", None)

    batch_id = str(uuid.uuid4())
    created_tasks = []
    errors = []

    for item in items_to_process:
        url_str = item.url.strip()
        try:
            validate_source(request.app.state.settings, url_str)
            if store and hasattr(store, "get_tenant"):
                check_tenant_quota(store, redis_client, tenant_id, user, target_url=url_str)

            sig = inspect.signature(manager.start)
            kwargs = {}
            if "batch_id" in sig.parameters:
                kwargs["batch_id"] = batch_id
            if "tenant_id" in sig.parameters:
                kwargs["tenant_id"] = tenant_id
            if "user_id" in sig.parameters:
                kwargs["user_id"] = user_id

            job_id = await asyncio.to_thread(
                manager.start,
                url_str,
                item.format,
                item.quality,
                item.photo_index,
                item.title or "",
                **kwargs,
            )

            if store and hasattr(store, "increment_tenant_job_count"):
                store.increment_tenant_job_count(tenant_id, get_today_utc())

            if hasattr(manager, "store") and hasattr(manager.store, "record_audit"):
                client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
                domain = (urlsplit(url_str).hostname or "").lower()
                manager.store.record_audit(
                    tenant_id,
                    user_id,
                    user.get("email"),
                    "job.batch_item",
                    client_ip,
                    "success",
                    target_type="job",
                    target_id=job_id,
                    details={"format": item.format, "quality": item.quality, "domain": domain, "batch_id": batch_id},
                )

            created_tasks.append(await get_task(request, job_id, tenant_id=tenant_id))
        except Exception as exc:
            logger.warning("Batch item failed: %s -> %s", url_str, exc)
            errors.append({"url": url_str, "error": str(exc)})

    if not created_tasks and errors:
        raise HTTPException(400, f"All batch items failed submission: {', '.join(e['error'] for e in errors)}")

    return {
        "batch_id": batch_id,
        "total": len(items_to_process),
        "submitted": len(created_tasks),
        "failed": len(errors),
        "tasks": created_tasks,
        "errors": errors,
    }


@router.get("/batch/{batch_id}")
async def get_batch_status(batch_id: str, request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)

    if store and hasattr(store, "list_jobs_by_batch"):
        raw_tasks = await asyncio.to_thread(store.list_jobs_by_batch, batch_id, tenant_id=tenant_id)
    else:
        all_tasks = await asyncio.to_thread(manager.store.list)
        raw_tasks = [t for t in all_tasks if t.get("batch_id") == batch_id]

    tasks_with_owner = [with_ownership(manager, t) for t in raw_tasks]
    completed = sum(1 for t in tasks_with_owner if t.get("status") == "completed")
    in_progress = sum(1 for t in tasks_with_owner if t.get("status") in {"downloading", "processing", "finishing"})
    queued = sum(1 for t in tasks_with_owner if t.get("status") == "queued")
    failed = sum(1 for t in tasks_with_owner if t.get("status") in {"error", "interrupted", "cancelled"})

    return {
        "batch_id": batch_id,
        "total": len(tasks_with_owner),
        "completed": completed,
        "in_progress": in_progress,
        "queued": queued,
        "failed": failed,
        "tasks": tasks_with_owner,
    }


@router.get("/tasks")
async def tasks(request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    manager = request.app.state.jobs
    sig = inspect.signature(manager.store.list)
    if "tenant_id" in sig.parameters:
        snapshots = await asyncio.to_thread(manager.store.list, tenant_id=tenant_id)
    else:
        snapshots = await asyncio.to_thread(manager.store.list)
    return {"tasks": [with_ownership(manager, task) for task in snapshots]}


@router.get("/progress/{download_id}")
async def get_progress(download_id: UUID, request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    return await get_task(request, download_id, tenant_id=tenant_id)


@router.get("/stream-tasks")
async def stream_tasks(request: Request):
    try:
        user = get_current_user(request)
    except HTTPException:
        user = {"tenant_id": "default-tenant"}
    tenant_id = user.get("tenant_id", "default-tenant")

    stream_fn = request.app.state.events.stream
    sig = inspect.signature(stream_fn)
    supports_tenant = "tenant_id" in sig.parameters

    async def events():
        source = stream_fn(request, tenant_id=tenant_id) if supports_tenant else stream_fn(request)
        async for event in source:
            if not stream_authorized(request):
                break
            yield event

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def stream_authorized(request):
    if request.app.state.settings.mode == "local":
        return True
    from app.auth import COOKIE, valid_session
    redis_client = getattr(getattr(request.app.state, "jobs", None), "redis", None)
    return valid_session(request.cookies.get(COOKIE, ""), request.app.state.settings.session_secret, redis_client=redis_client)


@router.post("/cancel/{download_id}")
async def cancel_download(download_id: UUID, request: Request):
    user = get_current_user(request)
    if user.get("role") == "viewer":
        raise HTTPException(403, "Viewers are not permitted to cancel download jobs.")

    tenant_id = user.get("tenant_id", "default-tenant")
    task = await get_task(request, download_id, tenant_id=tenant_id)
    if not task["managed_here"]:
        raise HTTPException(409, "This download is running in the previous app. Cancel it from its original window.")

    if user.get("role") == "member" and task.get("user_id") and task.get("user_id") != user.get("user_id"):
        raise HTTPException(403, "Members may only cancel downloads they submitted.")

    try:
        sig = inspect.signature(request.app.state.jobs.cancel)
        if "tenant_id" in sig.parameters:
            result = await asyncio.to_thread(request.app.state.jobs.cancel, str(download_id), tenant_id=tenant_id)
        else:
            result = await asyncio.to_thread(request.app.state.jobs.cancel, str(download_id))

        if hasattr(request.app.state.jobs, "store") and hasattr(request.app.state.jobs.store, "record_audit"):
            client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
            request.app.state.jobs.store.record_audit(
                tenant_id,
                user.get("user_id"),
                user.get("email"),
                "job.cancel",
                client_ip,
                "success",
                target_type="job",
                target_id=str(download_id),
            )
        return result
    except KeyError:
        raise HTTPException(404, "Download task not found")


@router.get("/stream-progress/{download_id}")
async def stream_progress(download_id: UUID, request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    await get_task(request, download_id, tenant_id=tenant_id)

    async def events():
        while not await request.is_disconnected() and stream_authorized(request):
            task = await get_task(request, download_id, tenant_id=tenant_id)
            yield f"data: {json.dumps(task, ensure_ascii=False)}\n\n"
            if task["status"] in TERMINAL_STATUSES:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/file/{download_id}")
async def get_file(download_id: UUID, request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    task = await get_task(request, download_id, tenant_id=tenant_id)
    if task["status"] != "completed" or not task.get("filename"):
        raise HTTPException(409, "This download does not have a completed file yet")

    if hasattr(request.app.state.jobs, "store") and hasattr(request.app.state.jobs.store, "record_audit"):
        client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
        request.app.state.jobs.store.record_audit(
            tenant_id,
            user.get("user_id"),
            user.get("email"),
            "media.download",
            client_ip,
            "success",
            target_type="job",
            target_id=str(download_id),
        )

    return await asyncio.to_thread(request.app.state.storage.response, task)


@router.get("/browser-download/{download_id}")
async def browser_download(download_id: UUID, request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    origin = request.headers.get("origin")
    expected_origin = request.app.state.settings.public_origin if request.app.state.settings.mode == "cloud" else str(request.base_url).rstrip("/")
    if (origin and origin != expected_origin) or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Open Snacky Studio locally to download this file.")

    task = await get_task(request, download_id, tenant_id=tenant_id)

    if hasattr(request.app.state.jobs, "store") and hasattr(request.app.state.jobs.store, "record_audit"):
        client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
        request.app.state.jobs.store.record_audit(
            tenant_id,
            user.get("user_id"),
            user.get("email"),
            "media.download",
            client_ip,
            "success",
            target_type="job",
            target_id=str(download_id),
        )

    return await browser_response(request, task)


@router.get("/download-file")
async def get_file_by_name(request: Request, filename: str = Query(..., max_length=255)):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    sig = inspect.signature(request.app.state.storage.response_by_name)
    if "tenant_id" in sig.parameters:
        return await asyncio.to_thread(request.app.state.storage.response_by_name, filename, tenant_id=tenant_id)
    return await asyncio.to_thread(request.app.state.storage.response_by_name, filename)


@router.get("/history")
async def get_history(request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    sig = inspect.signature(request.app.state.storage.history)
    if "tenant_id" in sig.parameters:
        files = await asyncio.to_thread(request.app.state.storage.history, tenant_id=tenant_id)
    else:
        files = await asyncio.to_thread(request.app.state.storage.history)
    return {"files": files}


@router.delete("/history/{filename}")
async def delete_history(filename: str, request: Request):
    user = get_current_user(request)
    if user.get("role") == "viewer":
        raise HTTPException(403, "Viewers are not permitted to delete media files.")

    tenant_id = user.get("tenant_id", "default-tenant")
    sig = inspect.signature(request.app.state.storage.delete)
    if "tenant_id" in sig.parameters:
        await asyncio.to_thread(request.app.state.storage.delete, filename, tenant_id=tenant_id)
    else:
        await asyncio.to_thread(request.app.state.storage.delete, filename)

    if hasattr(request.app.state.jobs, "store") and hasattr(request.app.state.jobs.store, "record_audit"):
        client_ip = get_client_ip(request, request.app.state.settings.trusted_proxies)
        request.app.state.jobs.store.record_audit(
            tenant_id,
            user.get("user_id"),
            user.get("email"),
            "media.delete",
            client_ip,
            "success",
            target_type="file",
            target_id=filename,
        )

    return {"success": True}


@router.post("/open-folder")
async def open_folder(request: Request):
    if request.app.state.settings.mode == "cloud":
        raise HTTPException(400, "Open folder is available in the local desktop app.")
    path = str(request.app.state.settings.downloads_dir)

    def open_native():
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
    try:
        await asyncio.to_thread(open_native)
    except OSError:
        raise HTTPException(500, "Could not open the downloads folder on this computer.")
    return {"success": True, "path": path}


# -----------------------------------------------------------------------------
# Quotas, Tiers & Abuse Prevention Endpoints
# -----------------------------------------------------------------------------
@router.get("/quotas/usage")
async def get_usage(request: Request):
    user = get_current_user(request)
    tenant_id = user.get("tenant_id", "default-tenant")
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    return get_quota_summary(store, tenant_id, user)


@router.post("/admin/kill-switch")
async def toggle_kill_switch(request: Request, body: dict):
    user = require_role("owner", "admin")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    active = bool(body.get("active", False))
    if hasattr(store, "update_abuse_controls"):
        return store.update_abuse_controls(kill_switch_active=active)
    return {"kill_switch_active": active}


@router.post("/admin/tenants/{tenant_id}/tier")
async def set_tenant_tier(tenant_id: str, body: dict, request: Request):
    user = require_role("owner")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    tier = body.get("tier", "free")
    if hasattr(store, "update_tenant_tier"):
        store.update_tenant_tier(
            tenant_id,
            tier,
            max_concurrent=body.get("max_concurrent_jobs"),
            max_daily_jobs=body.get("max_daily_jobs"),
            max_daily_bytes=body.get("max_daily_bytes"),
        )
        return {"updated": True, "tenant_id": tenant_id, "tier": tier}
    return {"updated": False}


@router.post("/admin/tenants/{tenant_id}/suspend")
async def suspend_tenant_endpoint(tenant_id: str, body: dict, request: Request):
    user = require_role("owner", "admin")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    reason = body.get("reason", "Suspended by admin")
    if hasattr(store, "suspend_tenant"):
        store.suspend_tenant(tenant_id, reason)
        return {"suspended": True, "tenant_id": tenant_id}
    return {"suspended": False}


@router.post("/admin/tenants/{tenant_id}/unsuspend")
async def unsuspend_tenant_endpoint(tenant_id: str, request: Request):
    user = require_role("owner", "admin")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    if hasattr(store, "unsuspend_tenant"):
        store.unsuspend_tenant(tenant_id)
        return {"suspended": False, "tenant_id": tenant_id}
    return {"suspended": False}


@router.get("/admin/abuse-controls")
async def get_abuse_controls_endpoint(request: Request):
    user = require_role("owner", "admin")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    if hasattr(store, "get_abuse_controls"):
        return store.get_abuse_controls()
    return {"kill_switch_active": False, "blocked_domains": [], "allowed_domains": []}


@router.put("/admin/abuse-controls")
async def update_abuse_controls_endpoint(request: Request, body: dict):
    user = require_role("owner", "admin")(user=get_current_user(request))
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    if hasattr(store, "update_abuse_controls"):
        return store.update_abuse_controls(
            kill_switch_active=body.get("kill_switch_active"),
            blocked_domains=body.get("blocked_domains"),
            allowed_domains=body.get("allowed_domains"),
        )
    return body


# -----------------------------------------------------------------------------
# User Preferences (Phase 8)
# -----------------------------------------------------------------------------
DEFAULT_PREFERENCES = {
    "default_format": "mp4",
    "default_quality": "best",
    "default_audio_bitrate": "320",
    "theme": "system",
    "language": "en",
    "auto_download": True,
}


@router.get("/preferences")
async def get_preferences(request: Request):
    user = get_current_user(request)
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    user_id = user.get("user_id")
    tenant_id = user.get("tenant_id", "default-tenant")

    if request.app.state.settings.mode == "cloud" and store and user_id:
        if hasattr(store, "get_user_preferences"):
            prefs = store.get_user_preferences(user_id, tenant_id)
            if prefs:
                return {**DEFAULT_PREFERENCES, **prefs}

    local_file = Path(request.app.state.settings.data_dir) / "preferences.json"
    if local_file.is_file():
        try:
            return {**DEFAULT_PREFERENCES, **json.loads(local_file.read_text(encoding="utf-8"))}
        except Exception:
            pass

    return DEFAULT_PREFERENCES


@router.put("/preferences")
async def update_preferences(prefs: UserPreferences, request: Request):
    user = get_current_user(request)
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    user_id = user.get("user_id")
    tenant_id = user.get("tenant_id", "default-tenant")
    data = prefs.model_dump()

    if request.app.state.settings.mode == "cloud" and store and user_id:
        if hasattr(store, "set_user_preferences"):
            store.set_user_preferences(user_id, tenant_id, data)
            return data

    local_dir = Path(request.app.state.settings.data_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_file = local_dir / "preferences.json"
    local_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
