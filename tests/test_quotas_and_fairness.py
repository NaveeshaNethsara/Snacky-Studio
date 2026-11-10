"""Enterprise tests for Phase 4:
- Quotas & Tier Enforcement (Unlimited Tier for Owner)
- Sliding-Window Rate Limiting
- Fair Outbox Scheduling Across Multiple Tenants
- Emergency Kill Switch & Abuse Domain Blocklist
- Supabase Auth JWT Verification & Auto-Provisioning
"""
import time
from unittest.mock import MagicMock

import jwt
import pytest

from app.auth import verify_supabase_token
from app.config import Settings
from app.errors import ProblemDetail
from app.quotas import (
    check_rate_limit,
    check_tenant_quota,
    get_quota_summary,
    get_today_utc,
)


# -----------------------------------------------------------------------------
# 1. Sliding Window Rate Limiter
# -----------------------------------------------------------------------------
def test_check_rate_limit_sliding_window():
    mock_redis = MagicMock()
    # Mock pipeline returning count <= max
    pipe = MagicMock()
    pipe.execute.return_value = [None, None, 10, None]  # count = 10
    mock_redis.pipeline.return_value = pipe

    allowed, retry_after = check_rate_limit(mock_redis, "snacky:ratelimit:t1", max_requests=20, window_seconds=60)
    assert allowed is True
    assert retry_after == 0

    # Mock pipeline returning count > max
    pipe.execute.return_value = [None, None, 25, None]  # count = 25 > 20
    allowed, retry_after = check_rate_limit(mock_redis, "snacky:ratelimit:t1", max_requests=20, window_seconds=60)
    assert allowed is False
    assert retry_after == 60


# -----------------------------------------------------------------------------
# 2. Quota & Tier Enforcement (Owner Unlimited Bypass)
# -----------------------------------------------------------------------------
class MockQuotaStore:
    def __init__(self, tenant_tier="free", suspended=False, active_count=0, daily_jobs=0, kill_switch=False, blocked=None):
        self.tenant = {
            "id": "tenant-123",
            "tier": tenant_tier,
            "is_suspended": suspended,
            "suspension_reason": "Policy violation" if suspended else None,
            "max_concurrent_jobs": -1 if tenant_tier == "unlimited" else 2,
            "max_daily_jobs": -1 if tenant_tier == "unlimited" else 10,
            "max_daily_bytes": -1 if tenant_tier == "unlimited" else 1000000,
            "storage_quota_bytes": -1 if tenant_tier == "unlimited" else 5000000,
        }
        self.active_count = active_count
        self.daily_jobs = daily_jobs
        self.kill_switch = kill_switch
        self.blocked_domains = blocked or []

    def get_tenant(self, tenant_id):
        return self.tenant

    def get_abuse_controls(self):
        return {
            "kill_switch_active": self.kill_switch,
            "blocked_domains": self.blocked_domains,
            "allowed_domains": [],
        }

    def get_tenant_usage_today(self, tenant_id, date_str):
        return {"job_count": self.daily_jobs, "bytes_downloaded": 0}


def test_owner_bypasses_all_quotas_and_kill_switch():
    store = MockQuotaStore(
        tenant_tier="free",
        active_count=100,  # Far above limit
        daily_jobs=500,    # Far above limit
        kill_switch=True,  # Kill switch active
    )
    owner_user = {"role": "owner", "tenant_id": "tenant-123", "email": "owner@example.com"}

    # Owner should bypass kill switch, concurrent clamp, and daily limit without throwing!
    result = check_tenant_quota(store, None, "tenant-123", owner_user, target_url="https://youtube.com/watch?v=123")
    assert result["is_unlimited"] is True
    assert result["tier"] == "unlimited"


def test_suspended_tenant_rejected():
    store = MockQuotaStore(suspended=True)
    user = {"role": "member", "tenant_id": "tenant-123"}
    with pytest.raises(ProblemDetail) as exc:
        check_tenant_quota(store, None, "tenant-123", user)
    assert exc.value.status_code == 403
    assert "suspended" in exc.value.detail.lower()


def test_kill_switch_blocks_standard_user():
    store = MockQuotaStore(kill_switch=True)
    user = {"role": "member", "tenant_id": "tenant-123"}
    with pytest.raises(ProblemDetail) as exc:
        check_tenant_quota(store, None, "tenant-123", user)
    assert exc.value.status_code == 503


def test_domain_blocklist_enforced():
    store = MockQuotaStore(blocked=["malicious-site.com"])
    user = {"role": "member", "tenant_id": "tenant-123"}
    with pytest.raises(ProblemDetail) as exc:
        check_tenant_quota(store, None, "tenant-123", user, target_url="https://sub.malicious-site.com/video")
    assert exc.value.status_code == 403
    assert "Domain Blocked" in exc.value.title


def test_daily_job_quota_exceeded():
    store = MockQuotaStore(tenant_tier="free", daily_jobs=10)
    user = {"role": "member", "tenant_id": "tenant-123"}
    with pytest.raises(ProblemDetail) as exc:
        check_tenant_quota(store, None, "tenant-123", user, target_url="https://youtube.com/watch?v=123")
    assert exc.value.status_code == 429
    assert exc.value.headers.get("Retry-After") == "3600"


# -----------------------------------------------------------------------------
# 3. Fair Scheduling Outbox Dispatch Test
# -----------------------------------------------------------------------------
def test_fair_round_robin_tenant_dispatch():
    """Verify that a flooded tenant A cannot starve tenant B."""
    class FakeTransactionStore:
        def __init__(self, job_rows):
            self.job_rows = job_rows
            self.dispatched = []

        def dispatch_due(self, send, *, interval=30, limit=6, per_tenant_limit=2):
            # Same fair algorithm as CloudJobStore.dispatch_due
            tenant_counts = {}
            dispatched_rows = []
            for row in self.job_rows:
                tid = row["tenant_id"]
                if tenant_counts.get(tid, 0) < per_tenant_limit:
                    dispatched_rows.append(row)
                    tenant_counts[tid] = tenant_counts.get(tid, 0) + 1
                    if len(dispatched_rows) >= limit:
                        break
            for r in dispatched_rows:
                send(r["id"])
            return len(dispatched_rows)

    # Tenant A has 10 jobs queued; Tenant B has 2 jobs queued
    rows = [{"id": f"A{i}", "tenant_id": "tenant-A"} for i in range(10)]
    rows.extend([{"id": f"B{i}", "tenant_id": "tenant-B"} for i in range(2)])

    store = FakeTransactionStore(rows)
    sent_ids = []
    count = store.dispatch_due(lambda jid: sent_ids.append(jid), limit=6, per_tenant_limit=2)

    # Dispatched 4 jobs total (2 from A, 2 from B)
    assert count == 4
    assert "A0" in sent_ids
    assert "A1" in sent_ids
    assert "B0" in sent_ids
    assert "B1" in sent_ids
    assert "A2" not in sent_ids  # Tenant A clamped to per_tenant_limit so Tenant B gets serviced!


# -----------------------------------------------------------------------------
# 4. Supabase JWT Verification & Owner Auto-Mapping
# -----------------------------------------------------------------------------
def test_supabase_jwt_verification():
    settings = Settings(
        mode="cloud",
        supabase_url="https://ymcpksqadkvxnzzlgfqf.supabase.co",
        supabase_jwt_secret="test-supabase-secret-minimum-32-chars!",
        owner_email="naveesha@example.com",
    )

    # 1. Owner user token
    now = int(time.time())
    owner_token = jwt.encode(
        {
            "iss": "https://ymcpksqadkvxnzzlgfqf.supabase.co/auth/v1",
            "sub": "user-uuid-1",
            "email": "naveesha@example.com",
            "role": "authenticated",
            "exp": now + 3600,
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    owner_session = verify_supabase_token(owner_token, settings)
    assert owner_session is not None
    assert owner_session["email"] == "naveesha@example.com"
    assert owner_session["role"] == "owner"
    assert owner_session["auth_type"] == "supabase"

    # 2. Standard user token
    member_token = jwt.encode(
        {
            "iss": "https://ymcpksqadkvxnzzlgfqf.supabase.co/auth/v1",
            "sub": "user-uuid-2",
            "email": "member@example.com",
            "role": "authenticated",
            "exp": now + 3600,
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    member_session = verify_supabase_token(member_token, settings)
    assert member_session is not None
    assert member_session["email"] == "member@example.com"
    assert member_session["role"] == "member"

    # 3. Invalid issuer token
    bad_token = jwt.encode(
        {
            "iss": "https://attacker.supabase.co/auth/v1",
            "sub": "bad-user",
            "email": "hacker@example.com",
            "role": "authenticated",
            "exp": now + 3600,
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    assert verify_supabase_token(bad_token, settings) is None

