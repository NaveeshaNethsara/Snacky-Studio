# ADR 0006: Observability, SRE Operations, and Prometheus Telemetry

- **Status:** Accepted
- **Date:** 2026-11-09
- **Author:** Principal Software Engineer & Systems Architect

## Context
As a multi-tenant media processing platform with asynchronous workers, private object storage, and public APIs, Snacky Studio requires comprehensive observability to achieve commercial-grade site reliability engineering (SRE):
1. **Request Tracing:** Distributed request life cycles span the API gateway, FastAPI replicas, Celery queues, and worker processes. Without end-to-end correlation IDs, diagnosing failed jobs or race conditions across distributed microservices is difficult.
2. **Log Standardization & Compliance:** Plain-text logs are difficult to parse in cloud aggregation platforms (Datadog, Loki, CloudWatch) and risk leaking sensitive customer credentials (passwords, bearer tokens, API keys, pre-signed S3 signatures).
3. **Telemetry & Metrics:** SRE teams need real-time visibility into queue depth, HTTP throughput/error rates, job execution latencies, worker concurrency, and quota rejections.
4. **Health Probes:** Kubernetes clusters need distinct liveness probes (is the container alive?) and readiness probes (are PostgreSQL, Redis, and S3 reachable?).
5. **Operational Incident Response:** On-call engineers need actionable, prescriptive runbooks for alerts (queue depth, high error rate, Redis pressure, DB pool exhaustion, disk space).

## Decisions

### 1. Structured JSON Logging with End-to-End Correlation IDs
- Built `JSONFormatter` in `app/logging_conf.py`, standardizing all log output into structured JSON (`timestamp`, `level`, `logger`, `message`, `correlation_id`, `request_id`, `tenant_id`, `user_id`).
- Implemented `CorrelationIdMiddleware` reading or generating `X-Correlation-ID` and `X-Request-ID`. Context is preserved across async coroutines using Python's `contextvars`.
- Propagated correlation IDs from API replicas to Celery worker tasks via task kwargs and metadata headers.

### 2. Automated PII & Secret Scrubbing
All log output passes through automated regular expression scrubbers before emission:
- Passwords (`password: "***"`)
- Bearer tokens (`Authorization: Bearer ***`)
- Scoped API keys (`snk_live_***`)
- Pre-signed S3 URLs (`X-Amz-Signature=***`)
- Database connection strings (`postgresql://user:***@host...`)

### 3. Prometheus Metrics Exposition (`/metrics`)
Integrated `prometheus-client` with custom metrics in `app/metrics.py`:
- `snacky_http_requests_total`: throughput counter labeled by method, normalized endpoint, and status code.
- `snacky_http_request_duration_seconds`: latency histogram across API endpoints.
- `snacky_queue_depth`: gauge tracking pending/queued jobs in outbox per tenant.
- `snacky_jobs_total` & `snacky_job_latency_seconds`: end-to-end task execution metrics labeled by media format, status, and tenant.
- `snacky_sse_connections_active`: gauge tracking live SSE client streams.
- `snacky_quota_rejections_total` & `snacky_webhook_deliveries_total`: abuse and integration telemetry.
- `snacky_worker_active_jobs`: gauge tracking active worker execution concurrency.

### 4. Granular Liveness & Readiness Probes
- `/health/live`: immediate liveness probe returning process uptime without testing external services.
- `/health/ready`: comprehensive readiness probe with sub-second dependency checks for PostgreSQL, Redis broker, and S3 storage. Returns HTTP 200 with `status: "degraded"` if Redis is down (since SQL polling fallback is active), and HTTP 503 only when the core database is unreachable.
- Admin Console UI displays live dependency cards and self-healing degradation indicators.

### 5. Grafana Dashboard & Operational Runbooks
- Authored production-ready Grafana dashboard specification: `infra/grafana/snacky-overview.json`.
- Authored operational incident response runbooks in `docs/runbooks/operations.md` covering queue depth spikes, error rates, database connection exhaustion, Redis memory pressure, and worker disk exhaustion.

## Alternatives Considered
- **OpenTelemetry Collector Sidecar:** Considered requiring a mandatory OTel collector sidecar container. Rejected for baseline deployments to keep resource overhead minimal and local mode zero-config. Standard Prometheus `/metrics` exposition satisfies 100% of Kubernetes monitoring needs with native scrape compatibility.
- **Unstructured Text Logs in Cloud Mode:** Rejected due to non-negotiable security requirements to enforce automated secret scrubbing and JSON queryability in log analyzers.

## Consequences
- **Positive:** Complete visibility across distributed API and worker tiers, zero risk of credential leaks in logs, automated Kubernetes health management, and rapid incident triage.
- **Backward Compatibility:** Local desktop mode remains zero-config and unaffected.

