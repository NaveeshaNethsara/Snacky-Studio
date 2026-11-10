"""Prometheus metrics instrumentation and exposition for Snacky Studio."""
from __future__ import annotations

import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Global metrics registry
REGISTRY = CollectorRegistry(auto_describe=True)

# -----------------------------------------------------------------------------
# Metric Definitions
# -----------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "snacky_http_requests_total",
    "Total HTTP requests received by API replicas",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "snacky_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

QUEUE_DEPTH = Gauge(
    "snacky_queue_depth",
    "Current number of pending/queued jobs in the outbox",
    ["tenant_id"],
    registry=REGISTRY,
)

JOBS_TOTAL = Counter(
    "snacky_jobs_total",
    "Total media download jobs processed",
    ["status", "format", "tenant_id"],
    registry=REGISTRY,
)

JOB_LATENCY_SECONDS = Histogram(
    "snacky_job_latency_seconds",
    "End-to-end execution latency for media download jobs in seconds",
    ["format", "status"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
    registry=REGISTRY,
)

SSE_ACTIVE_CONNECTIONS = Gauge(
    "snacky_sse_connections_active",
    "Current active Server-Sent Events (SSE) progress streams",
    ["tenant_id"],
    registry=REGISTRY,
)

QUOTA_REJECTIONS_TOTAL = Counter(
    "snacky_quota_rejections_total",
    "Total requests rejected due to rate limits or tier quotas",
    ["tenant_id", "reason"],
    registry=REGISTRY,
)

WEBHOOK_DELIVERIES_TOTAL = Counter(
    "snacky_webhook_deliveries_total",
    "Total outbound webhook delivery attempts",
    ["status", "tenant_id"],
    registry=REGISTRY,
)

WORKER_ACTIVE_JOBS = Gauge(
    "snacky_worker_active_jobs",
    "Number of media jobs actively being processed by workers",
    registry=REGISTRY,
)


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Measures latency and throughput across API endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Exclude /metrics itself and static assets from skewing API latency histograms
        path = request.url.path
        if path == "/metrics" or path.startswith("/static") or path.startswith("/assets"):
            return await call_next(request)

        start_time = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.monotonic() - start_time
            # Normalize path to avoid high-cardinality endpoint explosions
            normalized_path = _normalize_path(path)
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                endpoint=normalized_path,
                status_code=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                endpoint=normalized_path,
            ).observe(duration)


def _normalize_path(path: str) -> str:
    """Group parameter-based paths (UUIDs, filenames) into common endpoint templates."""
    parts = path.strip("/").split("/")
    if not parts or parts[0] == "":
        return "/"
    normalized = []
    for part in parts:
        # If looks like a UUID or numeric ID, replace with param placeholder
        if len(part) in (32, 36) and ("-" in part or all(c in "0123456789abcdefABCDEF-" for c in part)):
            normalized.append("{id}")
        elif part.startswith("job_") or part.startswith("snk_"):
            normalized.append("{id}")
        elif "." in part and not part.startswith("."):  # filename e.g. video.mp4
            normalized.append("{filename}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


def get_metrics_exposition() -> tuple[bytes, str]:
    """Render metrics in Prometheus text exposition format."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

