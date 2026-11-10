"""Verification suite for Phase 1 security hardening: Argon2id, IP spoofing defense, session revocation, and security headers."""
import time
from dataclasses import replace
from unittest.mock import MagicMock

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    COOKIE,
    get_client_ip,
    hash_password,
    make_session,
    parse_session_token,
    revoke_session,
    valid_session,
    verify_password,
)
from app.config import Settings
from app.main import create_app


def test_argon2id_hashing_and_verification():
    raw = "super-secret-workspace-password-1234"
    h = hash_password(raw)
    assert h.startswith("$argon2id$")
    assert verify_password(raw, h)
    assert not verify_password("wrong-password", h)
    assert not verify_password("", h)


def test_backward_compatible_plain_password_verification():
    plain = "legacy-raw-password"
    assert verify_password(plain, plain)
    assert not verify_password("wrong", plain)


def test_trusted_proxy_ip_extraction_defense():
    trusted = "127.0.0.1,10.0.0.0/8,172.16.0.0/12"

    # Case 1: Untrusted direct peer sending spoofed header -> ignore header
    req_untrusted = MagicMock()
    req_untrusted.client.host = "198.51.100.5"
    req_untrusted.headers = {"x-forwarded-for": "203.0.113.195"}
    assert get_client_ip(req_untrusted, trusted) == "198.51.100.5"

    # Case 2: Trusted proxy (e.g. Nginx at 172.18.0.2) forwards single client IP
    req_trusted = MagicMock()
    req_trusted.client.host = "172.18.0.2"
    req_trusted.headers = {"x-forwarded-for": "203.0.113.50"}
    assert get_client_ip(req_trusted, trusted) == "203.0.113.50"

    # Case 3: Attacker attempts to spoof by prepending fake IP in X-Forwarded-For
    req_spoofed = MagicMock()
    req_spoofed.client.host = "172.18.0.2"
    req_spoofed.headers = {"x-forwarded-for": "1.1.1.1, 203.0.113.50"}
    # Right-to-left traversal picks the actual untrusted hop before the proxy
    assert get_client_ip(req_spoofed, trusted) == "203.0.113.50"

    # Case 4: Chained internal proxies before reaching API
    req_chained = MagicMock()
    req_chained.client.host = "127.0.0.1"
    req_chained.headers = {"x-forwarded-for": "203.0.113.99, 10.0.0.5"}
    assert get_client_ip(req_chained, trusted) == "203.0.113.99"


def test_server_side_session_revocation():
    secret = "s" * 32
    redis_mock = fakeredis.FakeRedis()
    token = make_session(secret)

    # Valid before revocation
    assert valid_session(token, secret, redis_client=redis_mock)

    # Revoke individual session
    revoke_session(token, secret, redis_mock)
    assert not valid_session(token, secret, redis_client=redis_mock)


def test_logout_all_sessions_revocation():
    secret = "s" * 32
    redis_mock = fakeredis.FakeRedis()

    old_token = make_session(secret, now=time.time() - 100)
    assert valid_session(old_token, secret, redis_client=redis_mock)

    # Set revocation cutoff
    redis_mock.set("snacky:revoked_before", str(time.time()), ex=28800)

    # Old token is now invalid
    assert not valid_session(old_token, secret, redis_client=redis_mock)

    # Token generated after cutoff is valid
    fresh_token = make_session(secret, now=time.time() + 5)
    assert valid_session(fresh_token, secret, redis_client=redis_mock)


def test_cloud_security_headers_and_argon2_login(tmp_path, monkeypatch):
    password = "a-very-strong-enterprise-password-16"
    argon_hash = hash_password(password)

    settings = Settings(
        mode="cloud",
        downloads_dir=tmp_path / "work",
        data_dir=tmp_path / "data",
        database_url="postgresql+psycopg://unused",
        cloud_password_hash=argon_hash,
        session_secret="s" * 32,
        public_origin="https://studio.example.com",
    )

    fake_redis = fakeredis.FakeRedis()

    class Manager:
        def __init__(self, *args):
            self.store = MagicMock()
            self.redis = fake_redis

        def owns(self, _):
            return True

        def shutdown(self):
            pass

    monkeypatch.setattr("app.cloud.CloudDownloadManager", Manager)
    monkeypatch.setattr("app.main.S3MediaStorage", lambda *args: MagicMock())

    app = create_app(settings)
    with TestClient(app, base_url="https://studio.example.com") as client:
        # Check security headers on root response
        resp = client.get("/")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in resp.headers["content-security-policy"]
        assert resp.headers["cross-origin-opener-policy"] == "same-origin"
        assert "max-age=31536000" in resp.headers["strict-transport-security"]

        # Login with correct password verified by Argon2id
        login_res = client.post("/api/session/login", json={"password": password})
        assert login_res.status_code == 200
        assert login_res.json()["authenticated"] is True
        assert COOKIE in login_res.cookies

        # Verify session is active
        session_check = client.get("/api/session")
        assert session_check.status_code == 200
        assert session_check.json()["authenticated"] is True

        # Logout revokes session on server
        logout_res = client.post("/api/session/logout")
        assert logout_res.status_code == 200

        # Attempting to use the revoked cookie should now fail with 401
        reused_res = client.get("/api/tasks", cookies=login_res.cookies)
        assert reused_res.status_code == 401


def test_logout_all_endpoint(tmp_path, monkeypatch):
    password = "a-very-strong-enterprise-password-16"
    settings = Settings(
        mode="cloud",
        downloads_dir=tmp_path / "work",
        data_dir=tmp_path / "data",
        database_url="postgresql+psycopg://unused",
        cloud_password=password,
        session_secret="s" * 32,
        public_origin="http://localhost:8080",
    )

    fake_redis = fakeredis.FakeRedis()

    class Manager:
        def __init__(self, *args):
            self.store = MagicMock()
            self.redis = fake_redis

        def owns(self, _):
            return True

        def shutdown(self):
            pass

    monkeypatch.setattr("app.cloud.CloudDownloadManager", Manager)
    monkeypatch.setattr("app.main.S3MediaStorage", lambda *args: MagicMock())

    app = create_app(settings)
    with TestClient(app, base_url="http://localhost:8080") as client:
        login_res = client.post("/api/session/login", json={"password": password})
        assert login_res.status_code == 200

        # Invoke logout-all
        res = client.post("/api/session/logout-all")
        assert res.status_code == 200
        assert res.json()["revoked_all"] is True

        # Verification of revoked state
        assert client.get("/api/tasks", cookies=login_res.cookies).status_code == 401

