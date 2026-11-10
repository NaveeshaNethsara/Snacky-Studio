"""Verification suite for Phase 2: Multi-tenancy isolation, RBAC permissions, TOTP MFA, and tamper-evident audit logging."""
import pyotp
import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE, hash_password, make_session
from app.cloud_store import CloudJobStore
from app.config import Settings
from app.main import create_app


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared_p2.sqlite'}"
    s = CloudJobStore(url, initialize=True)
    yield s
    s.close()


def test_tenant_isolation_prevents_cross_tenant_access(store):
    # Setup Tenant Alpha and Tenant Beta
    alpha = store.create_tenant("Alpha Workspace", "alpha")
    beta = store.create_tenant("Beta Workspace", "beta")

    # Alpha creates a download job
    job_alpha = store.create_job("https://youtu.be/alpha", "mp4", "720", 0, "Alpha Vid", 100, tenant_id=alpha["id"])
    # Beta creates a download job
    job_beta = store.create_job("https://youtu.be/beta", "mp4", "720", 0, "Beta Vid", 100, tenant_id=beta["id"])

    # Alpha list should ONLY contain job_alpha
    alpha_tasks = store.list(tenant_id=alpha["id"])
    assert len(alpha_tasks) == 1
    assert alpha_tasks[0]["id"] == job_alpha

    # Beta list should ONLY contain job_beta
    beta_tasks = store.list(tenant_id=beta["id"])
    assert len(beta_tasks) == 1
    assert beta_tasks[0]["id"] == job_beta

    # Direct retrieval with cross tenant must return None
    assert store.get(job_alpha, tenant_id=beta["id"]) is None
    assert store.get(job_beta, tenant_id=alpha["id"]) is None


def test_rbac_user_management_and_totp_mfa(store):
    tenant = store.create_tenant("Acme Corp", "acme")
    pwd_hash = hash_password("SecurePassword123")

    # Create users with different roles
    owner = store.create_user(tenant["id"], "owner@acme.com", pwd_hash, role="owner")
    admin = store.create_user(tenant["id"], "admin@acme.com", pwd_hash, role="admin")
    member = store.create_user(tenant["id"], "member@acme.com", pwd_hash, role="member")
    viewer = store.create_user(tenant["id"], "viewer@acme.com", pwd_hash, role="viewer")

    assert owner["role"] == "owner"
    assert admin["role"] == "admin"
    assert member["role"] == "member"
    assert viewer["role"] == "viewer"

    # Setup TOTP MFA for member
    secret = pyotp.random_base32()
    store.update_user_totp(member["id"], secret, enabled=True)
    updated_member = store.get_user(member["id"])
    assert updated_member["totp_enabled"] is True

    # Verify TOTP code verification
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()
    assert totp.verify(valid_code)
    assert not totp.verify("000000")


def test_tamper_evident_audit_log_hash_chain(store):
    tenant = store.create_tenant("Security Inc", "sec")

    # Record 3 sequential audit logs
    log1 = store.record_audit(tenant["id"], "u1", "u1@sec.com", "auth.login", "1.1.1.1", "success")
    log2 = store.record_audit(tenant["id"], "u1", "u1@sec.com", "job.create", "1.1.1.1", "success", target_type="job", target_id="j1")
    log3 = store.record_audit(tenant["id"], "u1", "u1@sec.com", "media.download", "1.1.1.1", "success", target_type="job", target_id="j1")

    # Hash chain must be intact
    assert store.verify_audit_chain(tenant["id"]) is True

    # Tamper with an existing audit log entry in the database directly
    with store.engine.begin() as db:
        from sqlalchemy import update
        from app.cloud_store import audit_logs
        db.execute(update(audit_logs).where(audit_logs.c.id == log2).values(action="job.deleted_tampered"))

    # Hash chain verification must now FAIL
    assert store.verify_audit_chain(tenant["id"]) is False


def test_api_rbac_enforcement_viewer_cannot_download_or_delete(tmp_path, store, monkeypatch):
    tenant = store.create_tenant("RBAC Test", "rbac")
    pwd_hash = hash_password("SecretPassword123")
    viewer_user = store.create_user(tenant["id"], "viewer@rbac.com", pwd_hash, role="viewer")
    owner_user = store.create_user(tenant["id"], "owner@rbac.com", pwd_hash, role="owner")

    settings = Settings(
        mode="cloud",
        downloads_dir=tmp_path / "work",
        data_dir=tmp_path / "data",
        database_url="postgresql+psycopg://unused",
        cloud_password="a-very-strong-enterprise-password-16",
        session_secret="s" * 32,
        public_origin="http://localhost:8080",
    )

    class FakeRedisMock:
        def __init__(self):
            self.data = {}

        def get(self, key):
            return self.data.get(key)

        def set(self, key, val, **kwargs):
            self.data[key] = val

        def delete(self, key):
            self.data.pop(key, None)

        def publish(self, ch, msg):
            pass

    fake_redis = FakeRedisMock()

    class Manager:
        def __init__(self, *args):
            self.store = store
            self.redis = fake_redis

        def owns(self, _):
            return True

        def shutdown(self):
            pass

    monkeypatch.setattr("app.cloud.CloudDownloadManager", Manager)

    app = create_app(settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        # 1. Viewer session
        viewer_token = make_session(settings.session_secret)
        import json
        from app.auth import parse_session_token
        _, nonce = parse_session_token(viewer_token, settings.session_secret)
        fake_redis.data[f"snacky:session:{nonce}"] = json.dumps({
            "user_id": viewer_user["id"],
            "tenant_id": tenant["id"],
            "email": viewer_user["email"],
            "role": "viewer",
        })

        # Viewer attempts to submit a download -> must be rejected 403 Forbidden
        viewer_headers = {"Cookie": f"{COOKIE}={viewer_token}"}
        resp = client.post("/api/download", json={"url": "https://youtu.be/example"}, headers=viewer_headers)
        assert resp.status_code == 403
        assert "Viewers are not permitted" in resp.json()["detail"]

        # Viewer attempts to delete a file -> must be rejected 403 Forbidden
        del_resp = client.delete("/api/history/sample.mp4", headers=viewer_headers)
        assert del_resp.status_code == 403
        assert "Viewers are not permitted" in del_resp.json()["detail"]

        # 2. Owner session
        owner_token = make_session(settings.session_secret)
        _, owner_nonce = parse_session_token(owner_token, settings.session_secret)
        fake_redis.data[f"snacky:session:{owner_nonce}"] = json.dumps({
            "user_id": owner_user["id"],
            "tenant_id": tenant["id"],
            "email": owner_user["email"],
            "role": "owner",
        })
        owner_headers = {"Cookie": f"{COOKIE}={owner_token}"}

        # Owner can view audit logs
        audit_resp = client.get("/api/admin/audit-logs", headers=owner_headers)
        assert audit_resp.status_code == 200
        assert "logs" in audit_resp.json()

        # Owner can export audit logs as CSV
        export_resp = client.get("/api/admin/audit-logs/export", headers=owner_headers)
        assert export_resp.status_code == 200
        assert export_resp.headers["content-type"].startswith("text/csv")
        assert "Actor Email" in export_resp.text

        # Owner can verify audit chain
        verify_resp = client.get("/api/admin/audit-logs/verify", headers=owner_headers)
        assert verify_resp.status_code == 200
        assert verify_resp.json()["verified"] is True
