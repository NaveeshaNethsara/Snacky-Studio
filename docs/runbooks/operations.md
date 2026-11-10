# SRE Operational Runbooks: Incident Management & Alert Response

**Platform:** Snacky Studio Production Platform  
**Target Audience:** SREs, Systems Architects, and On-Call Engineers  
**Severity Levels:** P1 (Critical Outage), P2 (Degraded Performance), P3 (Warning/Non-Urgent)

---

## Alert 1: `SnackyQueueDepthHigh` (P2)

### Trigger Criteria
`sum(snacky_queue_depth) > 50` sustained for $> 5$ minutes.

### Impact
Customer download processing latencies increase; jobs remain queued in the database outbox.

### Diagnostic Procedure
1. **Check Worker Pod Status & Utilization:**
   ```bash
   kubectl get pods -n snacky -l app=snacky-worker
   kubectl top pods -n snacky -l app=snacky-worker
   ```
2. **Inspect Celery Broker & Active Leases:**
   ```bash
   # Check worker active job count from Prometheus
   curl -s http://localhost:8000/metrics | grep snacky_worker_active_jobs
   ```
3. **Check for Stuck Worker Leases:**
   ```sql
   SELECT id, tenant_id, lease_owner, lease_until, attempt_count, created_at 
   FROM media_jobs 
   WHERE status = 'queued' OR (status = 'fetching_info' AND lease_until < EXTRACT(EPOCH FROM NOW()))
   ORDER BY created_at ASC LIMIT 20;
   ```

### Remediation SOP
1. **Scale Worker Replicas Horizontally:**
   ```bash
   kubectl scale deployment/snacky-worker -n snacky --replicas=8
   ```
2. **Trigger Stuck Job Reaper Manually:**
   ```bash
   python -c "
   from app.config import Settings
   from app.cloud_store import CloudJobStore
   from app.lifecycle import reap_stuck_jobs
   s = Settings()
   store = CloudJobStore(s.database_url)
   print(reap_stuck_jobs(store))
   store.close()
   "
   ```
3. **Examine Upstream Throttling:** If workers are alive but slow, verify whether upstream platforms (YouTube/Instagram) are rate-limiting worker egress IPs. Configure egress proxy rotation or update cookies if needed.

---

## Alert 2: `SnackyHighErrorRate` (P1 / P2)

### Trigger Criteria
`rate(snacky_jobs_total{status="error"}[5m]) / rate(snacky_jobs_total[5m]) > 0.05` ($> 5\%$ job failures over 5m window).

### Impact
Users receive error states for download jobs; customer satisfaction drops.

### Diagnostic Procedure
1. **Query Recent Audit Logs & Error Payloads:**
   ```sql
   SELECT id, tenant_id, url, payload->>'error' as error, created_at
   FROM media_jobs 
   WHERE status = 'error' 
   ORDER BY created_at DESC LIMIT 20;
   ```
2. **Identify Failing Media Platform:**
   Check Grafana panel: *Job Completion Rate vs Error Rate* filtered by platform.

### Remediation SOP
1. **Upstream Extractor Incompatibility:**
   If a social network updated their API or page DOM (e.g. TikTok or Instagram layout change):
   - Check if yt-dlp / gallery-dl has an emergency patch available:
     ```bash
     pip install --upgrade yt-dlp gallery-dl
     ```
2. **Abusive Tenant Sending Malformed URLs:**
   If an automated bot or tenant is spamming dead links:
   - Identify offending `tenant_id` from query above.
   - Suspend tenant via Admin Console or CLI:
     ```bash
     python -c "
     from app.config import Settings
     from app.cloud_store import CloudJobStore
     store = CloudJobStore(Settings().database_url)
     store.suspend_tenant('offending-tenant-id', reason='Excessive malformed jobs')
     store.close()
     "
     ```
3. **Emergency Platform Kill Switch:**
   If a major upstream provider is completely blocking traffic, activate the emergency kill switch in the Admin Console to pause job acceptance gracefully with HTTP 503 while preserving running jobs.

---

## Alert 3: `SnackyDatabaseConnectionPoolExhausted` (P1)

### Trigger Criteria
PgBouncer client connections $\ge 90\%$ of `max_client_conn` (900/1000) or application pool wait time $> 1.0$s.

### Impact
New API requests block or return HTTP 503 / 500 errors.

### Diagnostic Procedure
1. **Inspect Active Database Connections:**
   ```sql
   SELECT client_addr, usename, state, count(*) 
   FROM pg_stat_activity 
   GROUP BY client_addr, usename, state;
   ```
2. **Check for Long-Running or Locked Transactions:**
   ```sql
   SELECT pid, now() - query_start AS duration, query, state 
   FROM pg_stat_activity 
   WHERE state != 'idle' AND (now() - query_start) > interval '10 seconds'
   ORDER BY duration DESC;
   ```

### Remediation SOP
1. **Terminate Hanging Queries:**
   ```sql
   SELECT pg_terminate_backend(pid) 
   FROM pg_stat_activity 
   WHERE state != 'idle' AND (now() - query_start) > interval '60 seconds';
   ```
2. **Verify PgBouncer Transaction Pooling:**
   Ensure `pool_mode` is set to `transaction` and not `session`.
3. **Restart Degraded API Replicas:**
   ```bash
   kubectl rollout restart deployment/snacky-api -n snacky
   ```

---

## Alert 4: `SnackyRedisMemoryPressure` (P2)

### Trigger Criteria
Redis memory usage exceeds $80\%$ of `maxmemory`.

### Impact
Redis pub/sub or rate limit caching may fail, causing degradation to SQL fallback.

### Diagnostic Procedure
1. **Check Memory Usage & Big Keys:**
   ```bash
   redis-cli info memory
   redis-cli --bigkeys
   ```
2. **Check Key Eviction Statistics:**
   ```bash
   redis-cli info stats | grep evicted_keys
   ```

### Remediation SOP
1. **Enforce LRU Eviction Policy:**
   ```bash
   redis-cli config set maxmemory-policy volatile-lru
   ```
2. **Flush Expired Session / Rate-Limit Keys:**
   Active rate-limit keys use 60-second rolling TTLs. Ensure no un-expiring keys exist outside `snacky:ratelimit:*`.
3. **Scale Redis Memory Allocation:**
   Increase memory limit in `infra/k8s/redis-ha.yaml` or managed Redis instance.

---

## Alert 5: `SnackyDiskSpaceCritical` (P1)

### Trigger Criteria
Persistent volume storage utilization $> 85\%$.

### Impact
Worker processes cannot write temporary media chunks; downloads crash.

### Diagnostic Procedure
1. **Check Disk Usage across Worker Pods:**
   ```bash
   kubectl exec -it <worker-pod> -n snacky -- df -h /downloads
   ```
2. **Locate Orphaned Temporary Directories:**
   ```bash
   kubectl exec -it <worker-pod> -n snacky -- find /downloads -type d -name "snacky-*" -mtime +1
   ```

### Remediation SOP
1. **Trigger Manual Media Purge Task:**
   ```bash
   python -c "
   from app.config import Settings
   from app.cloud_store import CloudJobStore
   from app.storage import S3MediaStorage
   from app.lifecycle import purge_expired_media
   s = Settings()
   store = CloudJobStore(s.database_url)
   storage = S3MediaStorage(s, store)
   purge_expired_media(store, storage, retention_seconds=0) # purge all soft-deleted items
   store.close()
   "
   ```
2. **Clean Stale Temporary Files:**
   ```bash
   kubectl exec -it <worker-pod> -n snacky -- find /downloads -type d -name "snacky-*" -mmin +120 -exec rm -rf {} +
   ```
3. **Expand Persistent Volume Claim:**
   Increase storage capacity in `compose.yaml` or Kubernetes PVC specification.

