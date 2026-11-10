# ADR 0005: Data Lifecycle, High Availability, and Disaster Recovery Architecture

- **Status:** Accepted
- **Date:** 2026-11-09
- **Author:** Principal Software Engineer & Systems Architect

## Context
Snacky Studio requires commercial-grade resilience and business continuity guarantees:
1. **High Availability (HA):** Single points of failure in the database, broker, or ingress could cause platform-wide downtime.
2. **Graceful Worker Teardown:** During Kubernetes rolling upgrades or autoscaling events, SIGTERM sent to Celery workers could leave claimed jobs locked in the database until lease expiry (up to 120s), degrading customer experience.
3. **Broker Dependency Resilience:** If Redis suffers a network partition or failover, real-time progress streaming via SSE must not crash or return HTTP 500 errors.
4. **Media Lifecycle & Soft Deletes:** Immediate destructive deletion prevents audit compliance and recovery from accidental file removal. Soft deletes must be retained for 30 days before automated physical purge from S3.
5. **Disaster Recovery (DR):** The platform needs strict RPO ($\le 1$ hour) and RTO ($\le 15$ minutes) compliance, backed by automated encrypted backups and self-verifying restore pipelines.

## Decisions

### 1. High Availability Reference Deployments
- **PostgreSQL HA:** CloudNativePG / Patroni cluster with 3 instances (1 primary, 2 streaming synchronous/asynchronous standby replicas) and automated quorum failover. Dedicated PgBouncer deployment in transaction pooling mode (`max_client_conn: 1000`, `pool_mode: transaction`) buffers connection bursts.
- **Redis HA:** Redis Sentinel 3-node cluster with automated failover and `PodDisruptionBudget (minAvailable: 2)`.
- **API & Worker HA:** Multi-replica API deployments (`replicas: 3`) across availability zones with HPA, and Celery worker deployments with `terminationGracePeriodSeconds: 120`.

### 2. Graceful Shutdown & Immediate Lease Release
Celery workers register `SIGTERM` and `SIGINT` OS signal handlers. Upon receiving a termination signal:
- Active execution cancellation events are flagged (`cancel.event.set()`), halting media download loops promptly.
- Workers proactively release database leases (`store.release_job_lease(...)`), resetting `lease_owner=None` and `lease_until=0`. This enables surviving worker replicas to pick up the job instantly with zero lease-timeout latency.

### 3. Self-Healing SSE Event Hub (Redis Degradation & Auto-Reconnect)
In `app/events.py`, `TaskEventHub` is hardened with automated graceful degradation:
- If Redis is unreachable, SSE streaming automatically falls back to polling PostgreSQL snapshot records (`TaskEventHub.refresh(...)`).
- A self-healing background monitor attempts reconnection to Redis every 15 seconds. Once the Redis cluster recovers, SSE clients seamlessly return to real-time pub/sub delivery.

### 4. Soft Deletes & Media Lifecycle Purge Engine
- Added `deleted_at`, `storage_key`, and `last_heartbeat_at` columns via Alembic migration `0005_soft_delete_and_lifecycle.py`.
- Deletions set `deleted_at = now()`, hiding media from completed histories while preserving data for 30 days.
- Periodic Celery maintenance task `snacky.reap_and_purge` executes:
  - `purge_expired_media(...)`: removes files past the 30-day retention window from S3 and hard-deletes the database rows.
  - `reap_stuck_jobs(...)`: reaps orphaned jobs and quarantines poison jobs after 3 failed attempts.
- S3 Bucket Lifecycle Configuration (`scripts/s3_lifecycle_policy.json`) enforces object expiration and incomplete multipart cleanup at the storage layer.

### 5. Automated Encrypted Backup & Restore Verification
- Backups are encrypted with **AES-256-GCM** (NIST SP 800-38D) with a 96-bit random nonce and 128-bit authentication tag, and compressed with Gzip level 9 (`scripts/backup.py`).
- Every backup generates a `.meta.json` sidecar containing SHA-256 digests and table row counts.
- `scripts/verify_restore.py` validates backups by decrypting, verifying checksums, restoring into an ephemeral schema (`restore_verify_<id>`), and asserting 100% row count parity.
- RTO target ($\le 900$s) is measured and validated on every run.

## Alternatives Considered
- **Active-Active Multi-Master Postgres (BDR / CockroachDB):** Rejected as premature complexity. Single-primary with synchronous streaming replication and automated Patroni failover provides 99.99% availability with zero multi-master conflict overhead.
- **Unencrypted SQL dumps:** Rejected due to non-negotiable enterprise security standards. Backups stored in S3 or local volumes must be encrypted at rest with authenticated AES-256-GCM.

## Consequences
- **Positive:** Zero single points of failure, automated recovery from broker outages, instant job failover on worker restarts, deterministic RPO/RTO guarantees, and complete audit compliance for deleted media.
- **Backward Compatibility:** Local desktop mode remains 100% zero-config and unaffected.

