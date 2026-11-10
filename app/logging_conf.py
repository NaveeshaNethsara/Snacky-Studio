"""Structured JSON logging with correlation IDs and PII scrubbing for production SRE."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variables for tracing requests across async coroutines and threads
correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
tenant_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="")
user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")

# PII and Secret Scrubbing Regex Patterns
SENSITIVE_PATTERNS = [
    (re.compile(r'(password["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE), r'\1***\3'),
    (re.compile(r'(secret["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE), r'\1***\3'),
    (re.compile(r'(authorization["\']?\s*[:=]\s*["\']?\s*Bearer\s+)([A-Za-z0-9\-._~+/]+=*)', re.IGNORECASE), r'\1***'),
    (re.compile(r'(X-Amz-Signature=)[A-Za-z0-9]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(X-Amz-Credential=)[^&]+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(snk_live_)[a-f0-9]{32}', re.IGNORECASE), r'\1***'),
    (re.compile(r'(postgres(?:ql)?(?:\+[a-z0-9]+)?://[^:]+:)(.+)(@[^/@:]+(?::\d+)?(?:/[^?]*)?)', re.IGNORECASE), r'\1***\3'),
]


def scrub_pii(text: str) -> str:
    """Scrub sensitive credentials, passwords, tokens, and query signatures from log strings."""
    if not isinstance(text, str):
        return text
    result = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class JSONFormatter(logging.Formatter):
    """Formats log records as structured, machine-parseable JSON."""

    def format(self, record: logging.LogRecord) -> str:
        # Format the core message
        message = record.getMessage()
        message = scrub_pii(message)

        now_utc = datetime.now(timezone.utc).isoformat()

        log_data: dict[str, Any] = {
            "timestamp": now_utc,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "correlation_id": getattr(record, "correlation_id", None) or correlation_id_ctx.get(),
            "request_id": getattr(record, "request_id", None) or request_id_ctx.get(),
            "tenant_id": getattr(record, "tenant_id", None) or tenant_id_ctx.get(),
            "user_id": getattr(record, "user_id", None) or user_id_ctx.get(),
            "process": record.process,
            "thread": record.threadName,
        }

        # Filter out empty tracing fields
        log_data = {k: v for k, v in log_data.items() if v}

        if record.exc_info:
            log_data["exception"] = scrub_pii(self.formatException(record.exc_info))

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_output: bool = True):
    """Configure application logging handler and formatter."""
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
        )

    root_logger.addHandler(handler)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware propagating correlation and request IDs across contexts."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID
        correlation_id = (
            request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
            or str(uuid4())
        )
        request_id = str(uuid4())

        # Bind to async context
        c_token = correlation_id_ctx.set(correlation_id)
        r_token = request_id_ctx.set(request_id)

        # Extract tenant or user if present in session/headers
        tenant_id = request.headers.get("x-tenant-id", "")
        t_token = tenant_id_ctx.set(tenant_id)

        try:
            response = await call_next(request)
            response.headers["x-correlation-id"] = correlation_id
            response.headers["x-request-id"] = request_id
            return response
        finally:
            correlation_id_ctx.reset(c_token)
            request_id_ctx.reset(r_token)
            tenant_id_ctx.reset(t_token)
