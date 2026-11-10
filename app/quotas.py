"""Quotas, sliding-window rate limiting, fair scheduling, and abuse controls."""
import datetime
import logging
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from app.errors import ProblemDetail

logger = logging.getLogger(__name__)


def get_today_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def check_rate_limit(
    redis_client,
    key: str,
    max_requests: int = 60,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """Sliding-window rate limiter using Redis sorted set.
    Returns (allowed, retry_after_seconds).
    """
    if not redis_client:
        return True, 0

    now = time.time()
    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {f"{now}:{time.time_ns()}": now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 5)
    results = pipe.execute()
    count = results[2]

    if count > max_requests:
        return False, window_seconds
    return True, 0


def check_tenant_quota(
    store,
    redis_client,
    tenant_id: str,
    user: dict,
    target_url: Optional[str] = None,
) -> dict:
    """Enforce tenant tiers, concurrent/daily quotas, domain blocklists, and emergency kill switches.
    Bypasses all quotas unconditionally if user is owner or tenant tier is 'unlimited'.
    """
    # 1. Abuse Controls: Global Kill Switch & Blocked Domains
    if hasattr(store, "get_abuse_controls"):
        controls = store.get_abuse_controls()
        if controls.get("kill_switch_active"):
            if user.get("role") != "owner":
                raise ProblemDetail(
                    status_code=503,
                    title="Service Unavailable",
                    detail="Emergency maintenance kill switch is active. Downloads are temporarily paused.",
                    headers={"Retry-After": "60"},
                )

        if target_url:
            hostname = (urlsplit(target_url).hostname or "").lower()
            blocked = controls.get("blocked_domains") or []
            if any(hostname == b.lower() or hostname.endswith("." + b.lower()) for b in blocked):
                raise ProblemDetail(
                    status_code=403,
                    title="Domain Blocked",
                    detail=f"Downloads from '{hostname}' are blocked by administrator abuse policy.",
                )

    # 2. Tenant Suspension & Tier Checks
    tenant = store.get_tenant(tenant_id) if hasattr(store, "get_tenant") else None
    if not tenant:
        return {"tier": "unlimited", "is_unlimited": True}

    if tenant.get("is_suspended"):
        reason = tenant.get("suspension_reason") or "Suspended by administrator."
        raise ProblemDetail(
            status_code=403,
            title="Tenant Suspended",
            detail=f"Your workspace is suspended: {reason}",
        )

    is_unlimited = (
        user.get("role") == "owner"
        or tenant.get("tier") == "unlimited"
        or user.get("auth_type") == "local"
    )
    if is_unlimited:
        return {
            "tier": "unlimited",
            "is_unlimited": True,
            "max_concurrent_jobs": -1,
            "max_daily_jobs": -1,
            "max_daily_bytes": -1,
            "storage_quota_bytes": -1,
        }

    # 3. Sliding Window Rate Limiting (API abuse prevention)
    if redis_client:
        rl_key = f"snacky:ratelimit:{tenant_id}"
        allowed, retry_after = check_rate_limit(redis_client, rl_key, max_requests=60, window_seconds=60)
        if not allowed:
            raise ProblemDetail(
                status_code=429,
                title="Too Many Requests",
                detail="Request rate limit exceeded (60 requests/minute). Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )

    # 4. Concurrent Active Jobs Quota
    max_concurrent = tenant.get("max_concurrent_jobs", 5)
    if max_concurrent > 0 and hasattr(store, "engine"):
        from sqlalchemy import select, func
        from app.cloud_store import jobs, TERMINAL_STATUSES
        with store.engine.connect() as db:
            active_count = db.execute(
                select(func.count())
                .select_from(jobs)
                .where(jobs.c.tenant_id == tenant_id, ~jobs.c.status.in_(TERMINAL_STATUSES))
            ).scalar_one()

            if active_count >= max_concurrent:
                raise ProblemDetail(
                    status_code=429,
                    title="Concurrent Quota Reached",
                    detail=f"Active job limit reached ({active_count}/{max_concurrent}). Wait for current downloads to complete.",
                    headers={"Retry-After": "30"},
                )

    # 5. Daily Job Count & Bandwidth Quotas
    today = get_today_utc()
    usage = store.get_tenant_usage_today(tenant_id, today) if hasattr(store, "get_tenant_usage_today") else {}
    max_daily_jobs = tenant.get("max_daily_jobs", 50)
    if max_daily_jobs > 0 and usage.get("job_count", 0) >= max_daily_jobs:
        raise ProblemDetail(
            status_code=429,
            title="Daily Job Limit Reached",
            detail=f"Daily quota of {max_daily_jobs} download jobs reached for today. Resets at 00:00 UTC.",
            headers={"Retry-After": "3600"},
        )

    max_daily_bytes = tenant.get("max_daily_bytes", 5368709120)  # 5 GB
    if max_daily_bytes > 0 and usage.get("bytes_downloaded", 0) >= max_daily_bytes:
        raise ProblemDetail(
            status_code=429,
            title="Daily Bandwidth Limit Reached",
            detail="Daily bandwidth quota reached. Resets at 00:00 UTC.",
            headers={"Retry-After": "3600"},
        )

    return {
        "tier": tenant.get("tier", "free"),
        "is_unlimited": False,
        "max_concurrent_jobs": max_concurrent,
        "max_daily_jobs": max_daily_jobs,
        "max_daily_bytes": max_daily_bytes,
        "storage_quota_bytes": tenant.get("storage_quota_bytes", 21474836480),
    }


def get_quota_summary(store, tenant_id: str, user: dict) -> dict:
    """Return live quota allowance and current usage for the tenant."""
    is_owner = user.get("role") == "owner" or user.get("auth_type") == "local"
    tenant = store.get_tenant(tenant_id) if hasattr(store, "get_tenant") else None
    tier = "unlimited" if is_owner or not tenant else tenant.get("tier", "free")

    if is_owner or tier == "unlimited":
        return {
            "tier": "unlimited",
            "is_unlimited": True,
            "active_jobs": 0,
            "max_concurrent_jobs": -1,
            "daily_jobs_used": 0,
            "max_daily_jobs": -1,
            "daily_bytes_used": 0,
            "max_daily_bytes": -1,
            "storage_quota_bytes": -1,
        }

    today = get_today_utc()
    usage = store.get_tenant_usage_today(tenant_id, today) if hasattr(store, "get_tenant_usage_today") else {}

    from sqlalchemy import select, func
    from app.cloud_store import jobs, TERMINAL_STATUSES
    with store.engine.connect() as db:
        active_count = db.execute(
            select(func.count())
            .select_from(jobs)
            .where(jobs.c.tenant_id == tenant_id, ~jobs.c.status.in_(TERMINAL_STATUSES))
        ).scalar_one()

    return {
        "tier": tier,
        "is_unlimited": False,
        "active_jobs": active_count,
        "max_concurrent_jobs": tenant.get("max_concurrent_jobs", 5),
        "daily_jobs_used": usage.get("job_count", 0),
        "max_daily_jobs": tenant.get("max_daily_jobs", 50),
        "daily_bytes_used": usage.get("bytes_downloaded", 0),
        "max_daily_bytes": tenant.get("max_daily_bytes", 5368709120),
        "storage_quota_bytes": tenant.get("storage_quota_bytes", 21474836480),
    }

