"""Sentry error tracking integration with automated PII and secret scrubbing."""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from app.logging_conf import scrub_pii

logger = logging.getLogger(__name__)


def init_sentry(settings: Any = None):
    """Initialize Sentry SDK with strict PII scrubbing and environment tagging."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        logger.info("SENTRY_DSN not configured; continuing with local structured JSON observability.")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
            """Scrub sensitive headers, cookies, query parameters, and passwords from error events."""
            # Scrub request headers and cookies
            if "request" in event:
                req = event["request"]
                if "headers" in req:
                    headers = dict(req["headers"])
                    for sensitive_header in ["authorization", "cookie", "set-cookie", "x-api-key"]:
                        if sensitive_header in headers:
                            headers[sensitive_header] = "***"
                    req["headers"] = headers

                if "query_string" in req and isinstance(req["query_string"], str):
                    req["query_string"] = scrub_pii(req["query_string"])

                if "data" in req and isinstance(req["data"], str):
                    req["data"] = scrub_pii(req["data"])

            # Scrub exception messages
            if "exception" in event and "values" in event["exception"]:
                for exc in event["exception"]["values"]:
                    if "value" in exc:
                        exc["value"] = scrub_pii(exc["value"])

            return event

        environment = os.getenv("SNACKY_ENVIRONMENT", "production")
        release = os.getenv("SNACKY_RELEASE", "3.0.0")

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
            integrations=[
                FastApiIntegration(),
                CeleryIntegration(),
            ],
            before_send=before_send,
            send_default_pii=False,
        )
        logger.info("Sentry error tracking successfully initialized (env=%s, release=%s)", environment, release)
    except ImportError:
        logger.warning("sentry-sdk not installed; skipping Sentry error tracking initialization.")
    except Exception as exc:
        logger.error("Failed to initialize Sentry: %s", exc)

