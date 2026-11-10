# ADR 0004: Quotas, Tenant Tiers, Fair Scheduling, and Abuse Prevention

## Status
Accepted

## Context
As a multi-tenant platform with media processing and conversion workloads, Snacky Studio requires protective boundaries against resource starvation, runaway downloads, and API abuse. A single tenant queuing thousands of intensive 4K video downloads could saturate Celery workers, exhaust disk space, or breach cloud egress bandwidth.

Furthermore, platform owners and administrators require an **unrestricted experience (`unlimited` tier)** for their own workloads, with personal credentials bypassing all limits, alongside emergency controls to suspend abusive tenants or halt downloads platform-wide.

## Decisions

### 1. Multi-Tenant Tiers & Owner Unlimited Bypass
- Introduced explicit tenant tiers: `unlimited`, `pro`, and `free` in the `tenants` table.
- **Owner Unlimited Bypass**: Any user with `role: "owner"` or tenant with `tier: "unlimited"` unconditionally bypasses:
  - Global emergency kill switch
  - Sliding-window rate limiters
  - Concurrent active job clamps (`max_concurrent_jobs = -1`)
  - Daily job quotas (`max_daily_jobs = -1`)
  - Daily bandwidth limits (`max_daily_bytes = -1`)
- Standard tiers enforce concurrency limits and daily quotas with clear HTTP 429 Problem Details and `Retry-After` headers.

### 2. Fair Round-Robin Outbox Scheduling
- Replaced monolithic `ORDER BY created_at LIMIT N` outbox dispatch with fair round-robin scheduling across tenants (`per_tenant_limit = 4`).
- Even when one tenant enqueues thousands of jobs, other tenants receive immediate worker capacity on every dispatch cycle, preventing tenant starvation.

### 3. Redis Sliding-Window Rate Limiting
- Evaluated token bucket vs. sliding-window log using Redis sorted sets.
- Implemented sliding-window rate limiting (`zremrangebyscore`, `zadd`, `zcard`, `expire`) to eliminate burst boundary exploits.

### 4. Abuse Controls & Emergency Kill Switch
- Created singleton `abuse_controls` table for platform operations.
- **Emergency Kill Switch**: Allows administrators to pause non-owner download jobs instantly during maintenance or upstream API disruptions, returning HTTP 503 Service Unavailable.
- **Dynamic Domain Blocklist**: Configurable list of blocked domains (e.g. copyright infringement or malicious domains) evaluated before URL extraction.
- **Per-Tenant Suspension**: Ability to suspend rogue tenants with customizable suspension reasons returning HTTP 403 Forbidden.

### 5. Supabase Auth & Cloud PostgreSQL Integration
- Added direct Supabase JWT verification (`verify_supabase_token`) using HS256 / RS256 decoding.
- Incoming Supabase tokens automatically link users and tenants in PostgreSQL, automatically assigning `role: "owner"` and `tier: "unlimited"` when the user matches the configured `SNACKY_OWNER_EMAIL`.
- Cloud mode fully compatible with Supabase PostgreSQL connection strings (`postgresql+psycopg://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres` or Transaction Pooler port `6543`).

## Consequences

### Positive
- Platform owners have completely unmetered, unlimited personal accounts with zero limits.
- Fair scheduling guarantees responsive processing for all tenants under heavy load.
- Protection against noisy neighbors, rate limit exhaustion, and platform abuse.
- Streamlined integration with Supabase for PostgreSQL and authentication.

### Trade-offs
- Tracking daily usage requires atomic increments in the `tenant_usage` table.

