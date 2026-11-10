"""Phase 6 Tests: Structured JSON logging, PII scrubbing, correlation IDs,
Prometheus metrics exposition, and granular health/readiness probes.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.health import router as health_router
from app.logging_conf import (
    JSONFormatter,
    correlation_id_ctx,
    scrub_pii,
)
from app.main import create_app
from app.metrics import (
    HTTP_REQUESTS_TOTAL,
    REGISTRY,
    get_metrics_exposition,
)


def test_structured_json_logging_and_correlation_id():
    formatter = JSONFormatter()
    logger = logging.getLogger("test.sre")

    # 1. Test basic log formatting without context
    record1 = logger.makeRecord(
        name="test.sre",
        level=logging.INFO,
        fn="test_file.py",
        lno=10,
        msg="Service boot initialization complete",
        args=(),
        exc_info=None,
    )
    output1 = formatter.format(record1)
    parsed1 = json.loads(output1)

    assert parsed1["level"] == "INFO"
    assert parsed1["logger"] == "test.sre"
    assert parsed1["message"] == "Service boot initialization complete"
    assert "timestamp" in parsed1

    # 2. Test log formatting with correlation ID context
    token = correlation_id_ctx.set("corr-trace-12345")
    try:
        record2 = logger.makeRecord(
            name="test.sre",
            level=logging.WARNING,
            fn="test_file.py",
            lno=25,
            msg="Task queue delay detected",
            args=(),
            exc_info=None,
        )
        output2 = formatter.format(record2)
        parsed2 = json.loads(output2)
        assert parsed2["correlation_id"] == "corr-trace-12345"
        assert parsed2["level"] == "WARNING"
    finally:
        correlation_id_ctx.reset(token)


def test_pii_and_secret_scrubbing():
    # 1. Passwords in strings
    dirty_log = 'User login failed for {"email": "user@example.com", "password": "SuperSecretPassword123"}'
    cleaned = scrub_pii(dirty_log)
    assert "SuperSecretPassword123" not in cleaned
    assert '***' in cleaned

    # 2. Bearer Authorization tokens
    dirty_auth = "Request header Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123"
    cleaned_auth = scrub_pii(dirty_auth)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in cleaned_auth
    assert "Authorization: Bearer ***" in cleaned_auth

    # 3. API Keys
    dirty_key = "Access verified with key snk_live_a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    cleaned_key = scrub_pii(dirty_key)
    assert "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4" not in cleaned_key
    assert "snk_live_***" in cleaned_key

    # 4. Database URIs with credentials
    dirty_db = "Connecting to postgresql://snacky:P@ssw0rd123!@db.host.internal:5432/snacky"
    cleaned_db = scrub_pii(dirty_db)
    assert "P@ssw0rd123!" not in cleaned_db
    assert "postgresql://snacky:***@db.host.internal" in cleaned_db

    # 5. S3 Presigned signatures
    dirty_s3 = "Generated download URL https://s3.amazonaws.com/media/file.mp4?X-Amz-Signature=abcdef1234567890&other=param"
    cleaned_s3 = scrub_pii(dirty_s3)
    assert "abcdef1234567890" not in cleaned_s3
    assert "X-Amz-Signature=***" in cleaned_s3


def test_correlation_id_middleware():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data", mode="local")
        app = create_app(settings)
        client = TestClient(app)

        # 1. Request without Correlation-ID header should generate one
        resp1 = client.get("/api/health")
        assert resp1.status_code == 200
        assert "x-correlation-id" in resp1.headers
        assert "x-request-id" in resp1.headers
        assert len(resp1.headers["x-correlation-id"]) > 10

        # 2. Request with explicit Correlation-ID header should preserve it
        custom_id = "trace-e2e-client-998877"
        resp2 = client.get("/api/health", headers={"X-Correlation-ID": custom_id})
        assert resp2.status_code == 200
        assert resp2.headers["x-correlation-id"] == custom_id


def test_granular_liveness_and_readiness_probes():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data", mode="local")
        app = create_app(settings)
        client = TestClient(app)

        # 1. Liveness probe
        live_resp = client.get("/health/live")
        assert live_resp.status_code == 200
        live_data = live_resp.json()
        assert live_data["status"] == "ok"
        assert "uptime_seconds" in live_data

        # 2. Readiness probe
        ready_resp = client.get("/health/ready")
        assert ready_resp.status_code == 200
        ready_data = ready_resp.json()
        assert ready_data["status"] in ("ready", "degraded")
        assert "dependencies" in ready_data
        assert "database" in ready_data["dependencies"]
        assert "storage" in ready_data["dependencies"]


def test_prometheus_metrics_endpoint():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        settings = Settings(downloads_dir=root / "downloads", data_dir=root / "data", mode="local")
        app = create_app(settings)
        client = TestClient(app)

        # Trigger traffic to record metrics
        client.get("/api/health")

        # Query /metrics endpoint
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "text/plain" in metrics_resp.headers["content-type"]
        text_body = metrics_resp.text

        # Verify key Prometheus metrics exist
        assert "snacky_http_requests_total" in text_body
        assert "snacky_http_request_duration_seconds" in text_body
        assert "snacky_jobs_total" in text_body
        assert "snacky_worker_active_jobs" in text_body

