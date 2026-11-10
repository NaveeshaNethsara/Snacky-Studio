# Disaster Recovery & Business Continuity Runbook (DR-SOP)

**Platform:** Snacky Studio Enterprise Media Ingestion Platform  
**Target SLAs:**
- **Recovery Point Objective (RPO):** $\le 1$ hour (continuous WAL archiving & transaction safety)
- **Recovery Time Objective (RTO):** $\le 15$ minutes (automated decryption, schema restoration, and verification)

---

## 1. High Availability Architecture Overview

Snacky Studio's cloud tier is designed with zero single-points-of-failure (no-SPOF) and graceful degradation:

```
                  ┌───────────────────────────────┐
                  │    Active-Active Ingress      │
                  │   (Nginx / Kubernetes PDB)    │
                  └──────────────┬────────────────┘
                                 │
             ┌───────────────────┴───────────────────┐
             │                                       │
    ┌────────▼─────────┐                    ┌────────▼─────────┐
    │  API Replica 1   │                    │   API Replica 2  │
    └────────┬─────────┘                    └────────┬─────────┘
             │                                       │
             ├───────────────────┬───────────────────┤
             │                   │                   │
    ┌────────▼─────────┐┌────────▼─────────┐┌────────▼─────────┐
    │  PostgreSQL HA   ││   Redis Sentinel ││   S3 Storage     │
    │  Primary + Standby││ 3-node HA quorum ││ Versioned + Rep  │
    │  (PgBouncer Pool)││ (Fallback: SQL)  ││ (RustFS/AWS S3)  │
    └──────────────────┘└──────────────────┘└──────────────────┘
```

### Self-Healing & Failure Modes
1. **Database Failover:** In HA clusters (Patroni / CloudNativePG / Supabase), primary failure promotes the standby within 10–30 seconds. Application queries retry with exponential backoff.
2. **Redis Outage:** If Redis becomes unavailable, `TaskEventHub` automatically degrades to authoritative SQL snapshot polling. No SSE connections drop with 500 errors. Once Redis recovers, `TaskEventHub` self-heals and resumes instant pub/sub.
3. **Worker SIGTERM / Crash:** Celery workers catch `SIGTERM`/`SIGINT` during rolling deploys or node drains, releasing job leases via `store.release_job_lease(...)` so another worker immediately picks up the task without waiting 120s.
4. **Poison Jobs:** Any corrupt media stream that crashes workers repeatedly is quarantined to `status="error"` after 3 failed attempts by `reap_stuck_jobs(...)`, preventing cascade worker restarts.

---

## 2. Automated Backup System

Backups are executed via `scripts/backup.py` and run on a schedule (e.g., hourly cron or Kubernetes CronJob):

```bash
# Execute encrypted backup
python scripts/backup.py --output-dir ./backups --upload-s3 --s3-bucket snacky-vault-backups
```

### Technical Specification
- **Compression:** Gzip level 9 streaming compression.
- **Encryption:** Authenticated **AES-256-GCM** (NIST SP 800-38D).
  - 96-bit cryptographically secure random initialization vector (nonce).
  - 128-bit authentication tag protecting against ciphertext tampering.
  - Encryption key derived from `BACKUP_ENCRYPTION_KEY` using SHA-256.
- **Sidecar Metadata (`.meta.json`):**
  - SHA-256 cryptographic digest of the encrypted payload.
  - Alembic schema revision number.
  - Per-table record counts for data integrity auditing.
  - Execution duration and timestamps.

---

## 3. Restore Verification Protocol

> **Rule:** *A backup that has never been restored is not a backup.*

Restore verification runs automatically via CI/CD and scheduled cron to prove compliance with RTO targets:

```bash
# Verify checksum, decrypt AES-256-GCM payload, and validate data integrity
python scripts/verify_restore.py backups/snacky_backup_YYYYMMDD_HHMMSSZ.sql.gz.enc
```

### Verification Steps Executed:
1. Validates that the SHA-256 file hash matches the signed metadata sidecar.
2. Verifies the AES-256-GCM authentication tag and decrypts the ciphertext.
3. Decompresses the Gzip stream and validates JSON schema integrity.
4. Spins up an isolated ephemeral schema (`restore_verify_<id>`) in PostgreSQL.
5. Populates all tables, counts rows, and validates 100% parity with pre-backup statistics.
6. Drops the ephemeral schema and records the RTO execution time (must be $\le 900$s).

---

## 4. Emergency Recovery Procedures

### Scenario A: Primary Database Corruption / Loss (Full Disaster Recovery)

1. **Provision Target Database:**
   Ensure clean PostgreSQL 17 instance is available and reachable via connection string.

2. **Retrieve Latest Encrypted Backup:**
   ```bash
   aws s3 cp s3://snacky-vault-backups/backups/postgres/snacky_backup_latest.sql.gz.enc ./
   aws s3 cp s3://snacky-vault-backups/backups/postgres/snacky_backup_latest.meta.json ./
   ```

3. **Verify Integrity & Restore:**
   ```bash
   export SNACKY_DATABASE_URL="postgresql+psycopg://user:pass@new-db-host:5432/snacky?sslmode=require"
   export BACKUP_ENCRYPTION_KEY="<production-vault-key>"
   
   python scripts/verify_restore.py snacky_backup_latest.sql.gz.enc
   ```

4. **Run Alembic Migrations to Confirm Schema State:**
   ```bash
   alembic upgrade head
   ```

5. **Point Application Services:**
   Update `SNACKY_DATABASE_URL` in Kubernetes Secret / `.env.cloud` and perform a rolling restart:
   ```bash
   kubectl rollout restart deployment/snacky-api -n snacky
   kubectl rollout restart deployment/snacky-worker -n snacky
   ```

---

### Scenario B: S3 Object Storage Recovery

1. **Bucket Versioning:** All media buckets have versioning enabled. In the event of accidental bulk deletion or ransomware, restore the previous object versions:
   ```bash
   python -c "
   import boto3
   s3 = boto3.resource('s3')
   bucket = s3.Bucket('snacky-media')
   for ver in bucket.object_versions.filter(Prefix='media/'):
       if ver.is_latest and ver.delete_marker:
           ver.delete()  # Deleting the delete marker restores the object
   "
   ```

2. **Cross-Region Replication (CRR):** In production AWS deployments, media is asynchronously replicated to secondary region (`us-west-2` or `eu-central-1`). In failover, update `SNACKY_S3_ENDPOINT` to the replication bucket.

---

## 5. Soft-Delete and Media Lifecycle Management

### Policy:
- When a user deletes a file, the row is marked with `deleted_at = now()` (soft delete).
- Files remain accessible to administrators for **30 days**.
- After 30 days, `snacky.reap_and_purge` Celery maintenance task automatically removes the file from S3 object storage and hard-deletes the record from the database.
- S3 Bucket Lifecycle Policy (`scripts/s3_lifecycle_policy.json`) enforces hard expiration at the object storage layer.

---

## 6. Key Rotation SOP

To rotate `BACKUP_ENCRYPTION_KEY`:
1. Generate new 32-byte high-entropy passphrase.
2. Run a full backup using the new passphrase:
   ```bash
   python scripts/backup.py --key "$NEW_KEY" --output-dir ./backups
   ```
3. Verify the new backup with `verify_restore.py --key "$NEW_KEY"`.
4. Update the key in production Vault / Kubernetes Secrets.
5. Retain the old key in the archive vault for restoring legacy snapshots.

