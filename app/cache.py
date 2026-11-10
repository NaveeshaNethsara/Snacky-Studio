"""High-performance Redis caching layer for hot metadata queries with transparent fallback."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MetadataCache:
    """Read-through caching for hot metadata (file lookups, tenant config, abuse controls)."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url
        self._client = None
        if redis_url:
            try:
                import redis
                self._client = redis.Redis.from_url(
                    redis_url,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    decode_responses=True,
                )
            except Exception as exc:
                logger.warning("Redis metadata cache initialization failed: %s; using DB direct", exc)
                self._client = None

    def _get(self, key: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        try:
            val = self._client.get(key)
            return json.loads(val) if val else None
        except Exception as exc:
            logger.debug("Cache read error for key %s: %s", key, exc)
            return None

    def _set(self, key: str, value: Any, ttl: int):
        if not self._client:
            return
        try:
            self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception as exc:
            logger.debug("Cache write error for key %s: %s", key, exc)

    def _delete(self, key: str):
        if not self._client:
            return
        try:
            self._client.delete(key)
        except Exception as exc:
            logger.debug("Cache delete error for key %s: %s", key, exc)

    # -------------------------------------------------------------------------
    # Hot File Lookups (TTL: 300s)
    # -------------------------------------------------------------------------
    def get_file(self, tenant_id: str, filename: str) -> dict[str, Any] | None:
        key = f"snacky:cache:file:{tenant_id}:{filename}"
        return self._get(key)

    def set_file(self, tenant_id: str, filename: str, data: dict[str, Any], ttl: int = 300):
        key = f"snacky:cache:file:{tenant_id}:{filename}"
        self._set(key, data, ttl)

    def invalidate_file(self, tenant_id: str, filename: str):
        key = f"snacky:cache:file:{tenant_id}:{filename}"
        self._delete(key)

    # -------------------------------------------------------------------------
    # Tenant Configuration & Tiers (TTL: 60s)
    # -------------------------------------------------------------------------
    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        key = f"snacky:cache:tenant:{tenant_id}"
        return self._get(key)

    def set_tenant(self, tenant_id: str, data: dict[str, Any], ttl: int = 60):
        key = f"snacky:cache:tenant:{tenant_id}"
        self._set(key, data, ttl)

    def invalidate_tenant(self, tenant_id: str):
        key = f"snacky:cache:tenant:{tenant_id}"
        self._delete(key)

    # -------------------------------------------------------------------------
    # Global Abuse Controls & Kill Switch (TTL: 60s)
    # -------------------------------------------------------------------------
    def get_abuse_controls(self) -> dict[str, Any] | None:
        key = "snacky:cache:abuse_controls"
        return self._get(key)

    def set_abuse_controls(self, data: dict[str, Any], ttl: int = 60):
        key = "snacky:cache:abuse_controls"
        self._set(key, data, ttl)

    def invalidate_abuse_controls(self):
        key = "snacky:cache:abuse_controls"
        self._delete(key)

    # -------------------------------------------------------------------------
    # User Preferences (TTL: 300s)
    # -------------------------------------------------------------------------
    def get_preferences(self, user_id: str) -> dict[str, Any] | None:
        key = f"snacky:cache:pref:{user_id}"
        return self._get(key)

    def set_preferences(self, user_id: str, data: dict[str, Any], ttl: int = 300):
        key = f"snacky:cache:pref:{user_id}"
        self._set(key, data, ttl)

    def invalidate_preferences(self, user_id: str):
        key = f"snacky:cache:pref:{user_id}"
        self._delete(key)

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

