# ADR 0003: Public API Platform, Webhook Delivery Engine, and Media Source Plugin Architecture

## Status
Accepted

## Context
Snacky Studio previously only offered internal and session-based endpoints (`/api/*`), tightly coupling the React frontend to the backend while lacking an external integration surface for developers, B2B workflows, or scheduled jobs. 

Key architectural gaps addressed:
1. **Lack of public API contract**: No versioning, unstandardized error structures, and lack of idempotency on job submission.
2. **Missing machine-to-machine authentication**: Only interactive session cookies existed; external automations could not authenticate with least-privilege scoping or revocation controls.
3. **Absence of event notifications**: External systems had to poll `/api/tasks` continuously, wasting server resources and introducing latency.
4. **Monolithic downloader logic**: All extractor, download, and remuxing heuristics were entangled in a single module (`downloader.py`), making it fragile to add support for new streaming platforms.

## Decisions

### 1. Versioned API (`/api/v1`) & RFC 9457 Problem Details
- All external endpoints are namespaced under `/api/v1`.
- Errors return standard `application/problem+json` bodies (RFC 9457) containing `type`, `title`, `status`, `detail`, and `instance`.
- OpenAPI/Swagger interactive documentation (`/docs` and `/openapi.json`) is auth-gated in production cloud environments.

### 2. Scoped API Keys (`snk_live_...`)
- High-entropy cryptographic tokens generated via `secrets.token_hex(24)` with the standard prefix `snk_live_`.
- Plaintext keys are presented once to the client upon creation and never stored.
- Keys are hashed with SHA-256 at rest in the `api_keys` table.
- Fine-grained capability scopes (`jobs:read`, `jobs:write`, `admin`) enforced on every endpoint.

### 3. Distributed Idempotency Key Handling
- Clients can provide the `Idempotency-Key` HTTP header when calling `POST /api/v1/jobs`.
- Request signatures (SHA-256 over `tenant_id + url + format + quality + photo_index`) are cached in PostgreSQL with a 24-hour TTL.
- Repeated calls with identical keys and identical payloads return cached responses with `X-Cache: HIT-IDEMPOTENT`.
- Repeated calls with matching keys but conflicting payloads are rejected with HTTP 409 Conflict.

### 4. Transactional Webhooks with SSRF Defense & Replay Protection
- Webhook subscription model with events (`job.created`, `job.completed`, `job.failed`, `job.cancelled`).
- Built upon transactional outbox (`webhook_deliveries` table) so event persistence is atomic with database changes.
- **SSRF Defense**: Target URLs are resolved to IP addresses and inspected against RFC 1918 private subnets, loopbacks, link-local metadata addresses (`169.254.169.254`), and non-HTTP protocols before any connection is initiated.
- **Cryptographic Replay Defense**: Outbound webhook requests are stamped with `X-Snacky-Timestamp` and signed with HMAC-SHA256 (`X-Snacky-Signature: sha256=...`) computed over `f"{timestamp}.{raw_body}"`.
- **Reliable Delivery & DLQ**: Deliveries retry up to 5 times with exponential backoff and jitter (`delay = min(3600, 2^attempt * 10 + jitter)`). Dead-lettered webhooks can be manually redelivered from the API.

### 5. Decoupled Media Source Plugin Architecture
- Replaced monolithic conditional logic with `BaseMediaPlugin` and `MediaPluginRegistry`.
- First-party plugins: `YouTubePlugin`, `InstagramPlugin`, `TikTokPlugin`, `FacebookPlugin`, `TwitterPlugin`, and fallback `GenericWebMediaPlugin`.
- Hardened retry sleep calculation (`_safe_retry_sleep`) to accept both positional and keyword argument conventions (`n`, `attempt`, `**kwargs`), permanently resolving the TikTok MP3 download crash.

## Consequences

### Positive
- Production-ready developer platform enabling external automation, SDKs, and third-party integrations.
- Zero risk of duplicate downloads under unreliable network retries due to idempotency keys.
- Real-time webhook notifications eliminate client-side polling overhead.
- Protection against SSRF and cloud metadata exfiltration.
- Clean separation of platform download logic into modular, testable plugins.

### Trade-offs
- Outbound webhooks require an egress network path and slight processing overhead in background worker queues.

