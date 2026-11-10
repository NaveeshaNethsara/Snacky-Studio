# ADR 0007: Scale and Performance Hardening (Column Promotion, Redis Metadata Caching, and KEDA Worker Autoscaling)

- **Status:** Accepted
- **Date:** 2026-11-09
- **Author:** Principal Software Engineer & Systems Architect

## Context
As Snacky Studio scales to handle multiple tenants, large download volumes, and high-concurrency API integrations, the architecture identified three distinct scalability and performance bottlenecks:
1. **Database Sequential Scans on JSONB:** Hot metadata queries (`find_file`, `soft_delete_by_filename`, active job filtering) queried properties (`filename`, `deleted_at`) nested inside the unstructured `payload` JSONB column. Because PostgreSQL cannot use standard B-tree index seeks across arbitrary JSON keys without specialized expression indexes, every query caused high-cost Sequential Scans ($O(N)$) and significant CPU/memory buffer overhead.
2. **Database Connection Saturation from Read-Heavy Traffic:** High-frequency endpoints (media availability checks, tenant tier/quota lookups, global abuse control checks) directly queried PostgreSQL on every single request. Under burst traffic, database connection pools risked exhaustion.
3. **Static Worker Provisioning vs. Spike-Heavy Media Workloads:** Video downloads and audio transcoding workloads are burst-prone. Static worker pod allocations either leave costly GPU/CPU instances idle or cause massive queue backlog spikes during traffic surges. Standard Kubernetes Horizontal Pod Autoscaler (HPA) metrics based on CPU/memory are lagging indicators for media queues.

## Decisions

### 1. Column Promotion & Composite B-Tree Indexing
- Promoted `filename` (VARCHAR(512)) and `deleted_at` (FLOAT / DOUBLE PRECISION) to first-class table columns in `media_jobs` via Alembic migration `0006_promote_columns_and_indices.py`.
- Safely backfilled existing records using the non-destructive expand/contract migration pattern.
- Created three high-selectivity composite B-tree indexes:
  - `ix_media_jobs_tenant_filename`: `(tenant_id, filename)` — transforms file lookups into $O(\log N)$ seeks.
  - `ix_media_jobs_tenant_deleted_status`: `(tenant_id, deleted_at, status)` — optimizes queue scheduling and worker claims while filtering soft-deleted media.
  - `ix_media_jobs_tenant_created_at`: `(tenant_id, created_at)` — accelerates cursor pagination and audit log queries.
- Maintained backwards-compatible OR fallback logic (`or_(jobs.c.filename == filename, jobs.c.payload["filename"].as_string() == filename)`) to ensure uninterrupted operation during rolling database upgrades.

### 2. High-Performance Redis Metadata Caching Layer (`MetadataCache`)
- Implemented `MetadataCache` in `app/cache.py` using a transparent read-through cache-aside pattern.
- Configured targeted TTLs:
  - File metadata lookups: 300 seconds (5 minutes).
  - Tenant configurations & tiers: 60 seconds (1 minute).
  - Abuse controls & global kill switch: 60 seconds (1 minute).
- Implemented surgical write-invalidation:
  - Cache invalidated immediately when a worker completes a download, a user soft-deletes a file, or an admin changes tenant tiers/abuse settings.
- Built-in fail-open resilience: wrapped all cache operations in sub-second socket/connect timeouts (1.0s) with try/except fallbacks to direct database queries. If Redis suffers transient outages or restarts, application availability remains 100%.

### 3. Horizontal Worker Autoscaling with KEDA
- Authored KEDA `ScaledObject` and `TriggerAuthentication` in `infra/k8s/keda-worker-scaledobject.yaml` targeting the `snacky-worker` deployment.
- Primary scaling trigger: Redis queue depth monitoring the Celery `media` queue list:
  - Target value: 5 queued tasks per worker replica.
  - Minimum replicas: 2 (warm baseline for instant task pick-up).
  - Maximum replicas: 15 (defensive cap to protect external networks and S3 ingress).
  - Polling interval: 15 seconds; cooldown period: 180 seconds.
- Secondary fallback trigger: Prometheus metric query `snacky_queue_depth`.

### 4. Load Benchmarking Suite (k6)
- Implemented `scripts/k6_benchmark.js` executing smoke (5 VUs), stress (50 VUs), and spike (100 VUs) scenarios.
- Established strict performance thresholds:
  - `http_req_duration`: p(95) < 100ms, p(99) < 250ms.
  - `http_req_failed`: rate < 0.01 (less than 1% failure under peak load).
  - `health_req_duration`: p(95) < 25ms.

## Alternatives Considered

- **PostgreSQL Functional/Expression Indexes on JSONB:**
  - *Alternative:* Create `CREATE INDEX ix_file ON media_jobs ((payload->>'filename'))`.
  - *Why Rejected:* While expression indexes avoid schema alterations, they do not resolve serialization overhead, increase payload size, make type enforcement harder, and prevent composite indexes with standard SQL columns across different database engines (e.g. SQLite in local mode). Promoting the column is the standard clean engineering practice.
- **Memcached for Metadata Caching:**
  - *Alternative:* Use Memcached instead of Redis for metadata caching.
  - *Why Rejected:* Redis is already deployed in our stack as the Celery task broker, rate limiter, and SSE pub/sub engine. Adding Memcached would introduce an unnecessary operational dependency without measurable latency benefits.
- **Kubernetes Native HPA (CPU/Memory Based):**
  - *Alternative:* Autoscale Celery workers using standard Kubernetes HPA on CPU utilization.
  - *Why Rejected:* Workers waiting on network I/O (yt-dlp video streams) often consume low CPU while a queue is rapidly backing up. Queue-depth scaling via KEDA directly reflects actual pending work and responds orders of magnitude faster.

