"""Granular Liveness, Readiness, and Dependency Health Probes for Kubernetes and SRE."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["Health & Probes"])

START_TIME = time.time()


@router.get("/health/live")
@router.get("/api/health/live")
async def liveness_probe():
    """Kubernetes liveness probe: indicates whether the process is alive and responsive."""
    uptime = time.time() - START_TIME
    return {
        "status": "ok",
        "service": "snacky-studio",
        "uptime_seconds": round(uptime, 2),
    }


@router.get("/health/ready")
@router.get("/api/health/ready")
async def readiness_probe(request: Request):
    """Kubernetes readiness probe: verifies database, Redis broker, and object storage connectivity."""
    settings = request.app.state.settings
    mode = getattr(settings, "mode", "local")

    checks: dict[str, Any] = {}
    is_healthy = True
    is_degraded = False

    # 1. Database Check
    db_start = time.monotonic()
    try:
        if mode == "cloud" and hasattr(request.app.state.jobs, "store"):
            store = request.app.state.jobs.store
            with store.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            latency_ms = round((time.monotonic() - db_start) * 1000, 2)
            checks["database"] = {"status": "ok", "latency_ms": latency_ms, "type": "postgresql"}
        else:
            # Local SQLite mode
            latency_ms = round((time.monotonic() - db_start) * 1000, 2)
            checks["database"] = {"status": "ok", "latency_ms": latency_ms, "type": "sqlite"}
    except Exception as exc:
        is_healthy = False
        checks["database"] = {"status": "error", "error": str(exc), "type": "database"}

    # 2. Redis Broker Check (Cloud mode only)
    if mode == "cloud":
        redis_start = time.monotonic()
        try:
            import redis.asyncio as aioredis
            client = aioredis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
            pong = await asyncio.wait_for(client.ping(), timeout=2.0)
            latency_ms = round((time.monotonic() - redis_start) * 1000, 2)
            await client.aclose()
            checks["redis"] = {"status": "ok", "latency_ms": latency_ms, "type": "broker"}
        except Exception as exc:
            # Redis loss is degraded rather than complete outage because SQL polling fallback exists
            is_degraded = True
            checks["redis"] = {
                "status": "degraded",
                "error": str(exc),
                "type": "broker",
                "fallback": "authoritative_sql_snapshots",
            }

    # 3. Storage Check
    storage_start = time.monotonic()
    try:
        if mode == "cloud":
            # Check S3 client
            storage = getattr(request.app.state, "storage", None)
            if storage and hasattr(storage, "client"):
                # Run head_bucket in thread to avoid blocking event loop
                await asyncio.to_thread(
                    storage.client.head_bucket, Bucket=settings.s3_bucket
                )
            latency_ms = round((time.monotonic() - storage_start) * 1000, 2)
            checks["storage"] = {"status": "ok", "latency_ms": latency_ms, "type": "s3"}
        else:
            downloads_dir = getattr(settings, "downloads_dir", None)
            is_writable = downloads_dir and downloads_dir.is_dir()
            latency_ms = round((time.monotonic() - storage_start) * 1000, 2)
            checks["storage"] = {"status": "ok" if is_writable else "error", "latency_ms": latency_ms, "type": "local_disk"}
    except Exception as exc:
        checks["storage"] = {"status": "warning", "error": str(exc), "type": "storage"}

    # Determine overall status code
    if not is_healthy:
        overall_status = "unhealthy"
        status_code = 503
    elif is_degraded:
        overall_status = "degraded"
        status_code = 200
    else:
        overall_status = "ready"
        status_code = 200

    payload = {
        "status": overall_status,
        "mode": mode,
        "dependencies": checks,
        "timestamp": time.time(),
    }
    return JSONResponse(status_code=status_code, content=payload)
