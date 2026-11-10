"""Public Versioned API (v1) with RFC 9457 error details, scoped API keys, idempotency, and webhooks."""
import hashlib
import json
import logging
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.auth import COOKIE, get_client_ip, get_session_data
from app.config import Settings
from app.errors import ProblemDetail
from app.plugins import get_default_registry
from app.quotas import check_tenant_quota, get_today_utc
from app.schemas import BatchDownloadRequest, BatchItem, UserPreferences, is_cloud_source_allowed, is_ssrf_safe_url
from app.webhooks import validate_webhook_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


# -----------------------------------------------------------------------------
# Dependency: Scoped API Key or Session Authentication
# -----------------------------------------------------------------------------
async def authenticate_v1(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Authenticate via API key (Bearer or X-API-Key) or session cookie."""
    settings = getattr(request.app.state, "settings", None) or Settings()
    if settings.mode == "local":
        return {
            "user_id": "local-user",
            "tenant_id": "default-tenant",
            "role": "owner",
            "scopes": ["*"],
            "auth_type": "local",
        }

    raw_token = None
    if x_api_key:
        raw_token = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token_candidate = authorization[7:].strip()
        if token_candidate.startswith("snk_"):
            raw_token = token_candidate

    manager = getattr(request.app.state, "jobs", None)
    store = getattr(manager, "store", None)

    # 1. API Key Auth
    if raw_token:
        key_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        if hasattr(store, "get_api_key_by_hash"):
            key_record = store.get_api_key_by_hash(key_hash)
            if key_record:
                if hasattr(store, "touch_api_key"):
                    store.touch_api_key(key_record["id"])
                return {
                    "user_id": key_record["user_id"],
                    "tenant_id": key_record["tenant_id"],
                    "role": "api_key",
                    "scopes": key_record.get("scopes", []),
                    "api_key_id": key_record["id"],
                    "auth_type": "api_key",
                }
        raise ProblemDetail(
            status_code=401,
            title="Unauthorized",
            detail="The provided API key is invalid, expired, or has been revoked.",
        )

    # 2. Session Auth (Fallback)
    cookie_token = request.cookies.get(COOKIE, "")
    if not cookie_token and authorization and authorization.lower().startswith("bearer "):
        cookie_token = authorization[7:].strip()

    if cookie_token:
        redis_inst = getattr(manager, "redis", None)
        session_data = get_session_data(cookie_token, settings.session_secret, redis_client=redis_inst)
        if session_data:
            role = session_data.get("role", "member")
            scopes = ["jobs:read", "jobs:write"] if role in ("owner", "admin", "member") else ["jobs:read"]
            if role in ("owner", "admin"):
                scopes.append("admin")
            return {
                "user_id": session_data.get("user_id"),
                "tenant_id": session_data.get("tenant_id", "default-tenant"),
                "role": role,
                "scopes": scopes,
                "auth_type": "session",
            }

    raise ProblemDetail(
        status_code=401,
        title="Unauthorized",
        detail="Missing or invalid authentication credentials. Provide a valid Bearer token or API key.",
    )


def require_v1_scope(required_scope: str):
    """Factory creating dependency to check API scope."""
    async def _scope_checker(auth: dict = Depends(authenticate_v1)):
        scopes = auth.get("scopes", [])
        if "*" in scopes or "admin" in scopes or required_scope in scopes:
            return auth
        raise ProblemDetail(
            status_code=403,
            title="Forbidden",
            detail=f"This operation requires the '{required_scope}' scope.",
        )
    return _scope_checker


# -----------------------------------------------------------------------------
# Pydantic Schemas for v1
# -----------------------------------------------------------------------------
class CreateJobRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    format: str = Field(default="mp4", pattern="^(mp4|mp3|photo|slideshow|png)$")
    quality: str = Field(default="best", max_length=16)
    photo_index: int = Field(default=0, ge=0)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default=["jobs:read", "jobs:write"])
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)


class CreateWebhookRequest(BaseModel):
    target_url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(default=["*"])
    secret: Optional[str] = Field(default=None, max_length=64)


# -----------------------------------------------------------------------------
# Endpoints: Jobs & Media
# -----------------------------------------------------------------------------
@router.post("/jobs", status_code=201)
async def create_job(
    req: CreateJobRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    auth: dict = Depends(require_v1_scope("jobs:write")),
):
    """Submit a media download job with optional Idempotency-Key deduplication."""
    tenant_id = auth["tenant_id"]
    user_id = auth.get("user_id")

    # SSRF & Source check
    if not is_ssrf_safe_url(req.url):
        raise ProblemDetail(
            status_code=400,
            title="Invalid URL",
            detail="The provided URL is not allowed or targets a restricted host.",
        )
    if not is_cloud_source_allowed(req.url):
        raise ProblemDetail(
            status_code=400,
            title="Unsupported Host",
            detail="Downloads from this domain are not permitted by workspace policy.",
        )

    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    redis_client = getattr(manager, "redis", None)

    # Quota, tier, rate limit & abuse check (unlimited for owner)
    if store and hasattr(store, "get_tenant"):
        check_tenant_quota(store, redis_client, tenant_id, auth, target_url=req.url)

    # 1. Idempotency Check
    request_sig = hashlib.sha256(
        f"{tenant_id}:{req.url}:{req.format}:{req.quality}:{req.photo_index}".encode()
    ).hexdigest()

    if idempotency_key and hasattr(store, "get_idempotency_key"):
        cached = store.get_idempotency_key(tenant_id, idempotency_key)
        if cached:
            if cached["request_hash"] != request_sig:
                raise ProblemDetail(
                    status_code=409,
                    title="Idempotency Conflict",
                    detail="Idempotency-Key was previously used with different parameters.",
                )
            return JSONResponse(
                content=cached["response_body"],
                status_code=cached["response_code"],
                headers={"X-Cache": "HIT-IDEMPOTENT"},
            )

    try:
        job_id = manager.create(
            req.url,
            req.format,
            req.quality,
            req.photo_index,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if store and hasattr(store, "increment_tenant_job_count"):
            store.increment_tenant_job_count(tenant_id, get_today_utc())
        task = manager.get(job_id, tenant_id=tenant_id)
        if not task:
            task = {"id": job_id, "status": "queued", "url": req.url}

        # 2. Store Idempotency
        if idempotency_key and hasattr(store, "save_idempotency_key"):
            store.save_idempotency_key(
                tenant_id=tenant_id,
                key=idempotency_key,
                request_hash=request_sig,
                response_code=201,
                response_body=task,
            )

        # 3. Fire Webhook
        if hasattr(store, "enqueue_webhook_events"):
            store.enqueue_webhook_events(tenant_id, "job.created", task)

        return task
    except Exception as exc:
        logger.error("Job creation failed in v1 API: %s", exc)
        raise ProblemDetail(
            status_code=500,
            title="Job Creation Failed",
            detail=str(exc),
        )


@router.get("/jobs")
async def list_jobs(
    cursor: Optional[str] = Query(None, description="Cursor for next page"),
    limit: int = Query(20, ge=1, le=100),
    request: Request = None,
    auth: dict = Depends(require_v1_scope("jobs:read")),
):
    """List jobs using cursor-based pagination."""
    tenant_id = auth["tenant_id"]
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)

    if hasattr(store, "list_cursor"):
        return store.list_cursor(tenant_id=tenant_id, cursor=cursor, limit=limit)

    # Fallback for stores without cursor support
    items = manager.list(tenant_id=tenant_id) if hasattr(manager, "list") else []
    return {"items": items[:limit], "next_cursor": None, "has_more": len(items) > limit}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("jobs:read")),
):
    """Retrieve status and metadata of a single download job."""
    tenant_id = auth["tenant_id"]
    manager = request.app.state.jobs
    task = manager.get(job_id, tenant_id=tenant_id)
    if not task:
        raise ProblemDetail(
            status_code=404,
            title="Job Not Found",
            detail=f"Job '{job_id}' does not exist or belongs to another tenant.",
        )
    return task


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("jobs:write")),
):
    """Cancel a running or queued job."""
    tenant_id = auth["tenant_id"]
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    task = manager.cancel(job_id, tenant_id=tenant_id)
    if not task:
        raise ProblemDetail(
            status_code=404,
            title="Job Not Found",
            detail=f"Job '{job_id}' was not found.",
        )
    if hasattr(store, "enqueue_webhook_events"):
        store.enqueue_webhook_events(tenant_id, "job.cancelled", task)
    return task


@router.post("/info")
async def get_media_info(
    req: CreateJobRequest,
    auth: dict = Depends(require_v1_scope("jobs:read")),
):
    """Inspect and extract formats for a media URL via the source plugin registry."""
    if not is_ssrf_safe_url(req.url) or not is_cloud_source_allowed(req.url):
        raise ProblemDetail(
            status_code=400,
            title="Invalid URL",
            detail="The URL is forbidden or from an unsupported domain.",
        )
    registry = get_default_registry()
    try:
        plugin = registry.get_plugin(req.url)
        info = plugin.extract_info(req.url)
        return info
    except Exception as exc:
        raise ProblemDetail(
            status_code=422,
            title="Media Extraction Error",
            detail=str(exc),
        )


@router.get("/media/{job_id}")
async def get_media_download(
    job_id: str,
    request: Request,
    redirect: bool = Query(True, description="Redirect to presigned URL or direct download"),
    auth: dict = Depends(require_v1_scope("jobs:read")),
):
    """Retrieve download link or stream for a completed job."""
    tenant_id = auth["tenant_id"]
    manager = request.app.state.jobs
    task = manager.get(job_id, tenant_id=tenant_id)
    if not task or task.get("status") != "completed":
        raise ProblemDetail(
            status_code=404,
            title="Media Not Available",
            detail=f"Job '{job_id}' is not completed or does not exist.",
        )

    storage = getattr(request.app.state, "storage", None)
    if storage and hasattr(storage, "get_download_url"):
        url = storage.get_download_url(task["filename"], tenant_id=tenant_id)
        if redirect:
            return RedirectResponse(url=url, status_code=307)
        return {"download_url": url, "filename": task["filename"]}

    # Local mode direct file stream
    file_path = manager.downloads_dir / task["filename"]
    if not file_path.is_file():
        raise ProblemDetail(
            status_code=404,
            title="File Missing",
            detail="The downloaded file was not found on disk.",
        )
    return FileResponse(file_path, filename=task["filename"])


# -----------------------------------------------------------------------------
# Endpoints: API Keys Management
# -----------------------------------------------------------------------------
@router.post("/api-keys", status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """Generate a new scoped API key for automation and external integrations."""
    tenant_id = auth["tenant_id"]
    user_id = auth.get("user_id") or "admin"
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)

    if not hasattr(store, "create_api_key"):
        raise ProblemDetail(status_code=501, title="Not Implemented", detail="API keys require cloud database store.")

    expires_at = None
    if req.expires_in_days:
        expires_at = time.time() + (req.expires_in_days * 86400)

    result = store.create_api_key(
        tenant_id=tenant_id,
        user_id=user_id,
        name=req.name,
        scopes=req.scopes,
        expires_at=expires_at,
    )
    if hasattr(store, "log_audit"):
        store.log_audit(
            tenant_id=tenant_id,
            user_id=user_id,
            action="api_key.create",
            client_ip=get_client_ip(request, getattr(request.app.state, "settings", None)),
            status="success",
            details={"key_id": result["id"], "name": req.name, "scopes": req.scopes},
        )
    return result


@router.get("/api-keys")
async def list_api_keys(
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """List all API keys issued for this tenant (hashed keys only)."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "list_api_keys"):
        return store.list_api_keys(tenant_id)
    return []


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """Revoke an active API key immediately."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "revoke_api_key"):
        revoked = store.revoke_api_key(tenant_id, key_id)
        if revoked:
            if hasattr(store, "log_audit"):
                store.log_audit(
                    tenant_id=tenant_id,
                    user_id=auth.get("user_id"),
                    action="api_key.revoke",
                    client_ip=get_client_ip(request, getattr(request.app.state, "settings", None)),
                    status="success",
                    details={"key_id": key_id},
                )
            return {"revoked": True, "key_id": key_id}
    raise ProblemDetail(status_code=404, title="Not Found", detail="API key not found.")


# -----------------------------------------------------------------------------
# Endpoints: Webhooks Management
# -----------------------------------------------------------------------------
@router.post("/webhooks", status_code=201)
async def create_webhook(
    req: CreateWebhookRequest,
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """Register an outbound webhook endpoint with SSRF verification."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)

    try:
        validate_webhook_url(req.target_url)
    except Exception as exc:
        raise ProblemDetail(
            status_code=400,
            title="SSRF Validation Failed",
            detail=str(exc),
        )

    secret = req.secret or secrets.token_hex(24)
    if hasattr(store, "create_webhook"):
        result = store.create_webhook(
            tenant_id=tenant_id,
            target_url=req.target_url,
            secret=secret,
            events=req.events,
        )
        result["secret"] = secret  # Displayed once upon registration
        return result
    raise ProblemDetail(status_code=501, title="Not Implemented", detail="Webhooks require cloud database store.")


@router.get("/webhooks")
async def list_webhooks(
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """List registered webhooks for the tenant."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "list_webhooks"):
        return store.list_webhooks(tenant_id)
    return []


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """Delete a registered webhook."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "delete_webhook"):
        deleted = store.delete_webhook(tenant_id, webhook_id)
        if deleted:
            return {"deleted": True, "webhook_id": webhook_id}
    raise ProblemDetail(status_code=404, title="Not Found", detail="Webhook not found.")


@router.get("/webhooks/deliveries")
async def list_webhook_deliveries(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    auth: dict = Depends(require_v1_scope("admin")),
):
    """List recent webhook delivery attempts and failure logs."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "list_webhook_deliveries"):
        return store.list_webhook_deliveries(tenant_id, limit=limit)
    return []


@router.post("/webhooks/deliveries/{delivery_id}/redeliver")
async def redeliver_webhook(
    delivery_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("admin")),
):
    """Manually retry delivery of a failed or dead-lettered webhook."""
    tenant_id = auth["tenant_id"]
    store = getattr(request.app.state.jobs, "store", None)
    if hasattr(store, "redeliver_webhook"):
        queued = store.redeliver_webhook(tenant_id, delivery_id)
        if queued:
            return {"queued": True, "delivery_id": delivery_id}
    raise ProblemDetail(status_code=404, title="Not Found", detail="Webhook delivery record not found.")


# -----------------------------------------------------------------------------
# Endpoints: Platform Plugins
# -----------------------------------------------------------------------------
@router.get("/plugins")
async def list_plugins():
    """List available media extractor plugins and their supported domains."""
    registry = get_default_registry()
    return {"plugins": registry.list_plugins()}


# -----------------------------------------------------------------------------
# Endpoints: Batch Processing (Phase 8)
# -----------------------------------------------------------------------------
@router.post("/batch")
async def create_batch_jobs(
    req: BatchDownloadRequest,
    request: Request,
    auth: dict = Depends(require_v1_scope("write")),
):
    """Submit a batch of URLs for parallel download processing."""
    tenant_id = auth["tenant_id"]
    user_id = auth.get("user_id")
    items_to_process = req.items or [
        BatchItem(url=u.strip(), format=req.format, quality=req.quality)
        for u in req.urls if u.strip()
    ]
    if not items_to_process:
        raise ProblemDetail(status_code=400, title="Bad Request", detail="No URLs provided in batch.")

    manager = request.app.state.jobs
    store = getattr(manager, "store", None)
    redis_client = getattr(manager, "redis", None)
    batch_id = secrets.token_hex(16)
    created_tasks = []
    errors = []

    for item in items_to_process:
        url_str = item.url.strip()
        if not is_ssrf_safe_url(url_str) or not is_cloud_source_allowed(url_str):
            errors.append({"url": url_str, "error": "Invalid URL or unsupported cloud domain."})
            continue

        try:
            if store and hasattr(store, "get_tenant"):
                check_tenant_quota(store, redis_client, tenant_id, auth, target_url=url_str)

            job_id = manager.create(
                url_str,
                item.format,
                item.quality,
                item.photo_index,
                tenant_id=tenant_id,
                user_id=user_id,
                batch_id=batch_id,
            )
            if store and hasattr(store, "increment_tenant_job_count"):
                store.increment_tenant_job_count(tenant_id, get_today_utc())

            task = manager.get(job_id, tenant_id=tenant_id) or {"id": job_id, "status": "queued", "url": url_str, "batch_id": batch_id}
            created_tasks.append(task)
        except Exception as exc:
            errors.append({"url": url_str, "error": str(exc)})

    if not created_tasks and errors:
        raise ProblemDetail(status_code=400, title="Batch Failed", detail=f"All batch URLs rejected: {errors[0]['error']}")

    return {
        "batch_id": batch_id,
        "total": len(items_to_process),
        "submitted": len(created_tasks),
        "failed": len(errors),
        "tasks": created_tasks,
        "errors": errors,
    }


@router.get("/batch/{batch_id}")
async def get_batch_v1(
    batch_id: str,
    request: Request,
    auth: dict = Depends(require_v1_scope("read")),
):
    """Get aggregate status and progress for a batch of jobs."""
    tenant_id = auth["tenant_id"]
    manager = request.app.state.jobs
    store = getattr(manager, "store", None)

    if store and hasattr(store, "list_jobs_by_batch"):
        raw_tasks = store.list_jobs_by_batch(batch_id, tenant_id=tenant_id)
    else:
        raw_tasks = [t for t in manager.store.list() if t.get("batch_id") == batch_id]

    completed = sum(1 for t in raw_tasks if t.get("status") == "completed")
    in_progress = sum(1 for t in raw_tasks if t.get("status") in {"downloading", "processing", "finishing"})
    queued = sum(1 for t in raw_tasks if t.get("status") == "queued")
    failed = sum(1 for t in raw_tasks if t.get("status") in {"error", "interrupted", "cancelled"})

    return {
        "batch_id": batch_id,
        "total": len(raw_tasks),
        "completed": completed,
        "in_progress": in_progress,
        "queued": queued,
        "failed": failed,
        "tasks": raw_tasks,
    }
