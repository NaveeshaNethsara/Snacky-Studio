# ADR-002: Multi-Tenancy Isolation, RBAC & Tamper-Evident Audit Logging

## Status
Accepted

## Context
Snacky Studio previously operated as a single shared-workspace environment where any authenticated user had full permissions across all downloads and files. Furthermore, real-time Server-Sent Events (SSE) broadcasted all task progress to all connected browsers, creating a cross-tenant data leak if multiple organizations were to use the platform.

Enterprise operations require:
1. Strict tenant isolation (Tenant A cannot see or access Tenant B's data or downloads).
2. Role-Based Access Control (RBAC): `owner`, `admin`, `member`, `viewer`.
3. Multi-Factor Authentication (MFA) via RFC 6238 TOTP.
4. Tamper-evident audit logging (recording who, what, when, IP, status, target).

## Decision
1. **Multi-Tenancy Model:**
   - Implement a shared PostgreSQL database with explicit `tenant_id` columns on `media_jobs`, `users`, and `audit_logs`.
   - Foreign key cascading deletes maintain referential integrity.
   - All repository queries in `CloudJobStore` enforce `WHERE tenant_id = :tenant_id`.
   - Local mode automatically defaults to `tenant_id = 'default-tenant'`, preserving zero-configuration local desktop operation.
2. **Partitioned SSE Stream:**
   - Partition real-time SSE progress snapshots and Redis pub/sub channels by tenant (`snacky:tenant:{tenant_id}:tasks`).
   - Clients only receive real-time updates for their authenticated tenant workspace.
3. **Role-Based Access Control (RBAC):**
   - `owner`: full workspace control (manage admins/owners, delete workspace).
   - `admin`: manage members/viewers, view audit logs, cancel any job in tenant, export data.
   - `member`: create downloads, cancel own downloads, download media, delete own downloads.
   - `viewer`: read-only access (view progress, stream tasks, view library). Submitting or deleting downloads returns HTTP 403 Forbidden.
4. **Tamper-Evident Audit Logging:**
   - Implement an append-only `audit_logs` table.
   - Each entry calculates a cryptographic hash linking to the previous entry:
     $$\text{hash}_n = \text{SHA256}(\text{hash}_{n-1} : \text{tenant\_id} : \text{user\_id} : \text{action} : \text{IP} : \text{status} : \text{timestamp} : \text{details})$$
   - An integrity verification endpoint (`GET /api/admin/audit-logs/verify`) verifies the entire hash chain and immediately flags any modification or deletion of past records.
5. **TOTP MFA:**
   - Adopt `pyotp` (RFC 6238) for time-based one-time password generation and verification.
   - Users can configure authenticator apps (1Password, Google Authenticator) and activate MFA on their account.

## Consequences
### Positive
- Complete tenant data isolation at database, API, and real-time streaming layers.
- Granular permission control preventing unauthorized job submission or file deletion by viewers.
- Cryptographically verifiable compliance and audit trails for SOC2 / ISO 27001 readiness.
- Zero breaking changes to local desktop mode or existing test fixtures.

### Negative
- Requires maintaining tenant and user context across request lifecycles.
- Slight database storage overhead for audit log hash chains.

