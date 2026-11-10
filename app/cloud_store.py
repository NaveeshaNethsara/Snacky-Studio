"""Multi-tenant transactional job state, RBAC identity, tamper-evident audit logs, and outbox dispatch."""
import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from contextlib import contextmanager

from app.cache import MetadataCache

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    case,
    create_engine,
    delete,
    func,
    or_,
    select,
    update,
)

from app.jobs import TERMINAL_STATUSES, QueueFullError

logger = logging.getLogger(__name__)

metadata = MetaData()

tenants = Table(
    "tenants",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("slug", String(100), unique=True, index=True, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("is_active", Boolean, default=True, nullable=False),
    Column("tier", String(20), default="free", nullable=False),
    Column("is_suspended", Boolean, default=False, nullable=False),
    Column("suspension_reason", String(255), nullable=True),
    Column("max_concurrent_jobs", Integer, default=5, nullable=False),
    Column("max_daily_jobs", Integer, default=50, nullable=False),
    Column("max_daily_bytes", BigInteger, default=5368709120, nullable=False),
    Column("storage_quota_bytes", BigInteger, default=21474836480, nullable=False),
)

tenant_usage = Table(
    "tenant_usage",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("date", String(10), index=True, nullable=False),
    Column("job_count", Integer, default=0, nullable=False),
    Column("bytes_downloaded", BigInteger, default=0, nullable=False),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("tenant_id", "date", name="uq_tenant_usage_date"),
)

abuse_controls = Table(
    "abuse_controls",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kill_switch_active", Boolean, default=False, nullable=False),
    Column("blocked_domains", JSON, nullable=False),
    Column("allowed_domains", JSON, nullable=False),
    Column("updated_at", Float, nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("email", String(255), index=True, nullable=False),
    Column("password_hash", String(255), nullable=True),
    Column("role", String(20), nullable=False, default="member"),
    Column("is_active", Boolean, default=True, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("totp_secret", String(64), nullable=True),
    Column("totp_enabled", Boolean, default=False, nullable=False),
    Column("token_version", Integer, default=1, nullable=False),
    UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("user_id", String(36), index=True, nullable=True),
    Column("actor_email", String(255), index=True, nullable=True),
    Column("action", String(50), index=True, nullable=False),
    Column("target_type", String(50), nullable=True),
    Column("target_id", String(255), nullable=True),
    Column("client_ip", String(45), nullable=False),
    Column("status", String(20), nullable=False),
    Column("details", JSON, nullable=False),
    Column("created_at", Float, index=True, nullable=False),
    Column("prev_hash", String(64), nullable=False, default="0" * 64),
)

jobs = Table(
    "media_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), index=True, nullable=False, default="default-tenant"),
    Column("user_id", String(36), index=True, nullable=True),
    Column("created_at", Float, nullable=False, index=True),
    Column("status", String(24), nullable=False, index=True),
    Column("version", Integer, nullable=False, default=1),
    Column("lease_owner", String(36)),
    Column("lease_until", Float, nullable=False, default=0),
    Column("dispatch_after", Float, nullable=False, default=0, index=True),
    Column("attempt_count", Integer, default=0, nullable=False),
    Column("deleted_at", Float, index=True, nullable=True),
    Column("storage_key", String(512), nullable=True),
    Column("last_heartbeat_at", Float, default=0, nullable=False),
    Column("filename", String(512), index=True, nullable=True),
    Column("payload", JSON, nullable=False),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("name", String(100), nullable=False),
    Column("key_prefix", String(16), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True, index=True),
    Column("scopes", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=True),
    Column("last_used_at", Float, nullable=True),
    Column("is_revoked", Boolean, default=False, nullable=False),
)

webhooks = Table(
    "webhooks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("target_url", String(2048), nullable=False),
    Column("secret", String(64), nullable=False),
    Column("events", JSON, nullable=False),
    Column("is_active", Boolean, default=True, nullable=False),
    Column("created_at", Float, nullable=False),
)

webhook_deliveries = Table(
    "webhook_deliveries",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("webhook_id", String(36), ForeignKey("webhooks.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("event", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False, default="queued"),
    Column("status_code", Integer, nullable=True),
    Column("attempt_count", Integer, default=0, nullable=False),
    Column("next_attempt_at", Float, default=0, index=True, nullable=False),
    Column("response_body", String(2048), nullable=True),
    Column("created_at", Float, index=True, nullable=False),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False),
    Column("key", String(255), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("response_code", Integer, nullable=False),
    Column("response_body", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, index=True, nullable=False),
    UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
)

user_preferences = Table(
    "user_preferences",
    metadata,
    Column("user_id", String(36), primary_key=True),
    Column("tenant_id", String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
    Column("preferences", JSON, nullable=False),
    Column("updated_at", Float, nullable=False),
)

admission = Table("queue_admission", metadata, Column("id", Integer, primary_key=True))


class CloudJobStore:
    def __init__(self, url, redis_url: str | None = None, *, initialize=False):
        self.engine = create_engine(url, pool_pre_ping=True)
        self.cache = MetadataCache(redis_url)
        if initialize:
            metadata.create_all(self.engine)
            with self.engine.begin() as db:
                if not db.execute(select(admission.c.id)).first():
                    db.execute(admission.insert().values(id=1))
                # Ensure default workspace exists with unlimited tier for owner
                if not db.execute(select(tenants.c.id).where(tenants.c.id == "default-tenant")).first():
                    now = time.time()
                    db.execute(
                        tenants.insert().values(
                            id="default-tenant",
                            name="Default Workspace",
                            slug="default",
                            created_at=now,
                            is_active=True,
                            tier="unlimited",
                            is_suspended=False,
                            suspension_reason=None,
                            max_concurrent_jobs=-1,
                            max_daily_jobs=-1,
                            max_daily_bytes=-1,
                            storage_quota_bytes=-1,
                        )
                    )
                # Ensure abuse controls singleton exists
                if not db.execute(select(abuse_controls.c.id)).first():
                    db.execute(
                        abuse_controls.insert().values(
                            id=1,
                            kill_switch_active=False,
                            blocked_domains=[],
                            allowed_domains=[],
                            updated_at=time.time(),
                        )
                    )

    @contextmanager
    def transaction(self):
        with self.engine.connect() as db:
            if self.engine.dialect.name == "sqlite":
                db.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                db.begin()
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    # -------------------------------------------------------------------------
    # Tenant Management
    # -------------------------------------------------------------------------
    def create_tenant(self, name: str, slug: str | None = None) -> dict:
        slug = slug or name.lower().replace(" ", "-")[:50]
        tenant_id = str(uuid.uuid4())
        now = time.time()
        with self.transaction() as db:
            db.execute(
                tenants.insert().values(
                    id=tenant_id,
                    name=name,
                    slug=slug,
                    created_at=now,
                    is_active=True,
                )
            )
        return {"id": tenant_id, "name": name, "slug": slug, "created_at": now, "is_active": True}

    def get_tenant(self, tenant_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(tenants).where(tenants.c.id == tenant_id)).mappings().first()
            return dict(row) if row else None

    def get_tenant_by_slug(self, slug: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(tenants).where(tenants.c.slug == slug)).mappings().first()
            return dict(row) if row else None

    def list_tenants(self) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(select(tenants).order_by(tenants.c.name)).mappings().all()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # User Management & RBAC
    # -------------------------------------------------------------------------
    def create_user(
        self,
        tenant_id: str,
        email: str,
        password_hash: str | None,
        role: str = "member",
        totp_secret: str | None = None,
    ) -> dict:
        user_id = str(uuid.uuid4())
        now = time.time()
        with self.transaction() as db:
            db.execute(
                users.insert().values(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email.lower().strip(),
                    password_hash=password_hash,
                    role=role,
                    is_active=True,
                    created_at=now,
                    totp_secret=totp_secret,
                    totp_enabled=False,
                    token_version=1,
                )
            )
        return {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": email.lower().strip(),
            "role": role,
            "is_active": True,
            "totp_enabled": False,
            "created_at": now,
        }

    def get_user(self, user_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return dict(row) if row else None

    def get_user_by_email(self, tenant_id: str, email: str) -> dict | None:
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(users).where(
                        users.c.tenant_id == tenant_id,
                        users.c.email == email.lower().strip(),
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def update_user_role(self, tenant_id: str, user_id: str, new_role: str) -> dict:
        with self.transaction() as db:
            db.execute(
                update(users)
                .where(users.c.id == user_id, users.c.tenant_id == tenant_id)
                .values(role=new_role, token_version=users.c.token_version + 1)
            )
        return self.get_user(user_id) or {}

    def update_user_totp(self, user_id: str, secret: str | None, enabled: bool) -> None:
        with self.transaction() as db:
            db.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(totp_secret=secret, totp_enabled=enabled, token_version=users.c.token_version + 1)
            )

    def list_users(self, tenant_id: str) -> list[dict]:
        with self.engine.connect() as db:
            rows = (
                db.execute(select(users).where(users.c.tenant_id == tenant_id).order_by(users.c.created_at.desc()))
                .mappings()
                .all()
            )
            return [
                {
                    "id": r["id"],
                    "tenant_id": r["tenant_id"],
                    "email": r["email"],
                    "role": r["role"],
                    "is_active": r["is_active"],
                    "totp_enabled": r["totp_enabled"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def delete_user(self, tenant_id: str, user_id: str) -> bool:
        with self.transaction() as db:
            res = db.execute(
                update(users)
                .where(users.c.id == user_id, users.c.tenant_id == tenant_id)
                .values(is_active=False, token_version=users.c.token_version + 1)
            )
            return bool(res.rowcount)

    # -------------------------------------------------------------------------
    # Tamper-Evident Audit Logging
    # -------------------------------------------------------------------------
    def record_audit(
        self,
        tenant_id: str,
        user_id: str | None,
        actor_email: str | None,
        action: str,
        client_ip: str,
        status: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict | None = None,
    ) -> str:
        log_id = str(uuid.uuid4())
        now = time.time()
        details_json = details or {}

        with self.transaction() as db:
            # Retrieve latest entry hash for tenant to form cryptographically linked chain
            last_entry = (
                db.execute(
                    select(audit_logs.c.prev_hash, audit_logs.c.id)
                    .where(audit_logs.c.tenant_id == tenant_id)
                    .order_by(audit_logs.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            prev_hash = last_entry["prev_hash"] if last_entry else "0" * 64
            # Hash payload linking to previous record
            record_str = f"{prev_hash}:{tenant_id}:{user_id or ''}:{action}:{client_ip}:{status}:{now}:{json.dumps(details_json, sort_keys=True)}"
            current_hash = hashlib.sha256(record_str.encode()).hexdigest()

            db.execute(
                audit_logs.insert().values(
                    id=log_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    actor_email=actor_email,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id else None,
                    client_ip=client_ip,
                    status=status,
                    details=details_json,
                    created_at=now,
                    prev_hash=current_hash,
                )
            )
        return log_id

    def list_audit_logs(
        self, tenant_id: str, *, limit: int = 100, action: str | None = None
    ) -> list[dict]:
        with self.engine.connect() as db:
            query = (
                select(audit_logs)
                .where(audit_logs.c.tenant_id == tenant_id)
                .order_by(audit_logs.c.created_at.desc())
                .limit(limit)
            )
            if action:
                query = query.where(audit_logs.c.action == action)
            rows = db.execute(query).mappings().all()
            return [dict(r) for r in rows]

    def verify_audit_chain(self, tenant_id: str) -> bool:
        """Verify the integrity of the cryptographic hash chain for a tenant."""
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    select(audit_logs)
                    .where(audit_logs.c.tenant_id == tenant_id)
                    .order_by(audit_logs.c.created_at.asc())
                )
                .mappings()
                .all()
            )
            prev = "0" * 64
            for row in rows:
                expected_str = f"{prev}:{row['tenant_id']}:{row['user_id'] or ''}:{row['action']}:{row['client_ip']}:{row['status']}:{row['created_at']}:{json.dumps(row['details'], sort_keys=True)}"
                expected_hash = hashlib.sha256(expected_str.encode()).hexdigest()
                if row["prev_hash"] != expected_hash:
                    return False
                prev = expected_hash
            return True

    # -------------------------------------------------------------------------
    # Job Operations (Multi-Tenant Scoped)
    # -------------------------------------------------------------------------
    def get(self, job_id: str, *, tenant_id: str | None = None):
        with self.engine.connect() as db:
            query = select(jobs.c.payload).where(jobs.c.id == job_id)
            if tenant_id:
                query = query.where(jobs.c.tenant_id == tenant_id)
            row = db.execute(query).first()
        return row[0] if row else None

    def list(self, *, tenant_id: str = "default-tenant", limit: int = 150):
        with self.engine.connect() as db:
            query = (
                select(jobs.c.payload)
                .where(jobs.c.tenant_id == tenant_id)
                .order_by(
                    case((jobs.c.status.in_(TERMINAL_STATUSES), 1), else_=0),
                    jobs.c.created_at.desc(),
                )
                .limit(limit)
            )
            return list(db.execute(query).scalars())

    def create_job(
        self,
        url: str,
        media_format: str,
        quality: str,
        photo_index: int,
        title: str,
        capacity: int,
        *,
        tenant_id: str = "default-tenant",
        user_id: str | None = None,
        batch_id: str | None = None,
    ):
        now = time.time()
        task = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "url": url,
            "format": media_format,
            "quality": quality,
            "photo_index": photo_index,
            "title": title,
            "thumbnail": "",
            "status": "queued",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": "—",
            "eta": "—",
            "filename": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        if batch_id:
            task["batch_id"] = batch_id
        with self.transaction() as db:
            db.execute(select(admission.c.id).where(admission.c.id == 1).with_for_update()).first()
            count = db.execute(
                select(func.count())
                .select_from(jobs)
                .where(jobs.c.tenant_id == tenant_id, ~jobs.c.status.in_(TERMINAL_STATUSES))
            ).scalar_one()
            if count >= capacity:
                raise QueueFullError("The download queue is full. Try again when a file is ready.")
            db.execute(
                jobs.insert().values(
                    id=task["id"],
                    tenant_id=tenant_id,
                    user_id=user_id,
                    created_at=now,
                    status="queued",
                    version=1,
                    lease_until=0,
                    dispatch_after=0,
                    attempt_count=0,
                    payload=task,
                )
            )
        return task["id"]

    def _locked(self, db, job_id, tenant_id=None):
        query = select(jobs).where(jobs.c.id == job_id).with_for_update()
        if tenant_id:
            query = query.where(jobs.c.tenant_id == tenant_id)
        row = db.execute(query).mappings().first()
        if not row:
            raise KeyError(job_id)
        return row

    def _write(self, db, row, changes, **columns):
        payload = dict(row["payload"])
        payload.update(changes, updated_at=time.time())
        if "filename" in changes and "filename" not in columns:
            columns["filename"] = changes["filename"]
        if "deleted_at" in changes and "deleted_at" not in columns:
            columns["deleted_at"] = changes["deleted_at"]
        db.execute(
            update(jobs)
            .where(jobs.c.id == row["id"])
            .values(payload=payload, status=payload["status"], version=row["version"] + 1, **columns)
        )
        return payload

    def update(self, job_id, *, tenant_id=None, **changes):
        with self.transaction() as db:
            return self._write(db, self._locked(db, job_id, tenant_id), changes)

    def claim(self, job_id, owner, ttl):
        with self.transaction() as db:
            row = self._locked(db, job_id)
            if row["status"] in TERMINAL_STATUSES:
                return None
            if row["payload"].get("cancel_requested"):
                self._write(
                    db,
                    row,
                    {"status": "cancelled", "completed_at": time.time()},
                    lease_owner=None,
                    lease_until=0,
                )
                return None
            if row["lease_owner"] and row["lease_until"] > time.time():
                return None
            return self._write(
                db,
                row,
                {"status": "fetching_info", "error": None},
                lease_owner=owner,
                lease_until=time.time() + ttl,
                attempt_count=row["attempt_count"] + 1,
            )

    def heartbeat(self, job_id, owner, ttl):
        now = time.time()
        with self.engine.begin() as db:
            result = db.execute(
                update(jobs)
                .where(jobs.c.id == job_id, jobs.c.lease_owner == owner, ~jobs.c.status.in_(TERMINAL_STATUSES))
                .values(lease_until=now + ttl, last_heartbeat_at=now)
            )
            return bool(result.rowcount)

    def worker_update(self, job_id, owner, ttl, **changes):
        with self.transaction() as db:
            row = self._locked(db, job_id)
            if row["lease_owner"] != owner or row["status"] in TERMINAL_STATUSES:
                return None
            if row["payload"].get("cancel_requested") and changes.get("status") not in TERMINAL_STATUSES:
                changes["status"] = "cancelling"
            terminal = changes.get("status") in TERMINAL_STATUSES
            storage_key = changes.get("storage_key") or row.get("storage_key")
            return self._write(
                db,
                row,
                changes,
                storage_key=storage_key,
                lease_owner=None if terminal else owner,
                lease_until=0 if terminal else time.time() + ttl,
            )

    def cancel(self, job_id, *, tenant_id=None):
        with self.transaction() as db:
            row = self._locked(db, job_id, tenant_id)
            if row["status"] in TERMINAL_STATUSES:
                return row["payload"]
            status = "cancelled" if not row["lease_owner"] or row["lease_until"] < time.time() else "cancelling"
            return self._write(
                db,
                row,
                {
                    "cancel_requested": True,
                    "status": status,
                    "completed_at": time.time() if status == "cancelled" else None,
                },
            )

    def dispatch_due(self, send, *, interval=30, limit=20, per_tenant_limit=4):
        now = time.time()
        with self.transaction() as db:
            candidates = (
                db.execute(
                    select(jobs)
                    .where(
                        ~jobs.c.status.in_(TERMINAL_STATUSES),
                        jobs.c.lease_until < now,
                        jobs.c.dispatch_after <= now,
                    )
                    .order_by(jobs.c.created_at)
                    .limit(limit * 3)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            # Fair round-robin allocation preventing tenant starvation
            tenant_counts: dict[str, int] = {}
            dispatched_rows = []
            for row in candidates:
                tid = row["tenant_id"]
                if tenant_counts.get(tid, 0) < per_tenant_limit:
                    dispatched_rows.append(row)
                    tenant_counts[tid] = tenant_counts.get(tid, 0) + 1
                    if len(dispatched_rows) >= limit:
                        break

            for row in dispatched_rows:
                send(row["id"])
                db.execute(update(jobs).where(jobs.c.id == row["id"]).values(dispatch_after=now + interval))
        return len(dispatched_rows)

    def completed(self, *, tenant_id: str = "default-tenant"):
        with self.engine.connect() as db:
            return list(
                db.execute(
                    select(jobs.c.payload)
                    .where(
                        jobs.c.tenant_id == tenant_id,
                        jobs.c.status == "completed",
                        jobs.c.deleted_at.is_(None),
                    )
                    .order_by(jobs.c.created_at.desc())
                    .limit(500)
                ).scalars()
            )

    def find_file(self, filename: str, *, tenant_id: str = "default-tenant"):
        cached = self.cache.get_file(tenant_id, filename)
        if cached:
            return cached

        with self.engine.connect() as db:
            row = db.execute(
                select(jobs.c.payload).where(
                    jobs.c.tenant_id == tenant_id,
                    jobs.c.status == "completed",
                    or_(jobs.c.filename == filename, jobs.c.payload["filename"].as_string() == filename),
                    jobs.c.deleted_at.is_(None),
                )
            ).scalar()

        if row:
            self.cache.set_file(tenant_id, filename, row, ttl=300)
        return row

    # -------------------------------------------------------------------------
    # Cursor-based Job Pagination
    # -------------------------------------------------------------------------
    def list_cursor(self, *, tenant_id: str = "default-tenant", cursor: str | None = None, limit: int = 20):
        with self.engine.connect() as db:
            query = select(jobs.c.payload).where(jobs.c.tenant_id == tenant_id)
            if cursor:
                try:
                    raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                    c_time = float(raw["created_at"])
                    c_id = str(raw["id"])
                    query = query.where(
                        or_(
                            jobs.c.created_at < c_time,
                            and_(jobs.c.created_at == c_time, jobs.c.id < c_id),
                        )
                    )
                except Exception as exc:
                    logger.warning("Invalid cursor %s: %s", cursor, exc)
            query = query.order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(limit + 1)
            rows = list(db.execute(query).scalars())

            has_more = len(rows) > limit
            items = rows[:limit]
            next_cursor = None
            if has_more and items:
                last_item = items[-1]
                payload_dict = last_item if isinstance(last_item, dict) else {}
                c_data = {"created_at": payload_dict.get("created_at", 0), "id": payload_dict.get("id", "")}
                next_cursor = base64.urlsafe_b64encode(json.dumps(c_data).encode()).decode()

            return {"items": items, "next_cursor": next_cursor, "has_more": has_more}

    # -------------------------------------------------------------------------
    # API Keys Management
    # -------------------------------------------------------------------------
    def create_api_key(
        self,
        tenant_id: str,
        user_id: str,
        name: str,
        scopes: list[str],
        expires_at: float | None = None,
    ):
        raw_token = secrets.token_hex(24)
        full_key = f"snk_live_{raw_token}"
        key_prefix = full_key[:15]
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        key_id = str(uuid.uuid4())
        now = time.time()
        with self.transaction() as db:
            db.execute(
                api_keys.insert().values(
                    id=key_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name=name,
                    key_prefix=key_prefix,
                    key_hash=key_hash,
                    scopes=scopes,
                    created_at=now,
                    expires_at=expires_at,
                    last_used_at=None,
                    is_revoked=False,
                )
            )
        return {"id": key_id, "key": full_key, "name": name, "prefix": key_prefix, "scopes": scopes}

    def get_api_key_by_hash(self, key_hash: str):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(api_keys)
                    .where(
                        api_keys.c.key_hash == key_hash,
                        api_keys.c.is_revoked.is_(False),
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            if row["expires_at"] and row["expires_at"] < time.time():
                return None
            return dict(row)

    def touch_api_key(self, key_id: str):
        with self.engine.begin() as db:
            db.execute(
                update(api_keys)
                .where(api_keys.c.id == key_id)
                .values(last_used_at=time.time())
            )

    def list_api_keys(self, tenant_id: str):
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    select(
                        api_keys.c.id,
                        api_keys.c.tenant_id,
                        api_keys.c.user_id,
                        api_keys.c.name,
                        api_keys.c.key_prefix,
                        api_keys.c.scopes,
                        api_keys.c.created_at,
                        api_keys.c.expires_at,
                        api_keys.c.last_used_at,
                        api_keys.c.is_revoked,
                    )
                    .where(api_keys.c.tenant_id == tenant_id)
                    .order_by(api_keys.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]

    def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                update(api_keys)
                .where(api_keys.c.id == key_id, api_keys.c.tenant_id == tenant_id)
                .values(is_revoked=True)
            )
            return bool(result.rowcount)

    # -------------------------------------------------------------------------
    # Idempotency Key Handling
    # -------------------------------------------------------------------------
    def get_idempotency_key(self, tenant_id: str, key: str):
        now = time.time()
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(idempotency_keys).where(
                        idempotency_keys.c.tenant_id == tenant_id,
                        idempotency_keys.c.key == key,
                        idempotency_keys.c.expires_at > now,
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def save_idempotency_key(
        self,
        tenant_id: str,
        key: str,
        request_hash: str,
        response_code: int,
        response_body: dict | list | str,
        ttl: float = 86400,
    ):
        now = time.time()
        with self.engine.begin() as db:
            db.execute(
                idempotency_keys.insert().values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    key=key,
                    request_hash=request_hash,
                    response_code=response_code,
                    response_body=response_body,
                    created_at=now,
                    expires_at=now + ttl,
                )
            )

    # -------------------------------------------------------------------------
    # Webhooks & Delivery Log Engine
    # -------------------------------------------------------------------------
    def create_webhook(self, tenant_id: str, target_url: str, secret: str, events: list[str]):
        webhook_id = str(uuid.uuid4())
        now = time.time()
        with self.transaction() as db:
            db.execute(
                webhooks.insert().values(
                    id=webhook_id,
                    tenant_id=tenant_id,
                    target_url=target_url,
                    secret=secret,
                    events=events,
                    is_active=True,
                    created_at=now,
                )
            )
        return {
            "id": webhook_id,
            "tenant_id": tenant_id,
            "target_url": target_url,
            "events": events,
            "created_at": now,
        }

    def list_webhooks(self, tenant_id: str):
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    select(webhooks)
                    .where(webhooks.c.tenant_id == tenant_id)
                    .order_by(webhooks.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]

    def delete_webhook(self, tenant_id: str, webhook_id: str) -> bool:
        with self.transaction() as db:
            result = db.execute(
                delete(webhooks).where(
                    webhooks.c.id == webhook_id,
                    webhooks.c.tenant_id == tenant_id,
                )
            )
            return bool(result.rowcount)

    def enqueue_webhook_events(self, tenant_id: str, event_name: str, payload: dict):
        now = time.time()
        enqueued_count = 0
        with self.transaction() as db:
            hooks = (
                db.execute(
                    select(webhooks).where(
                        webhooks.c.tenant_id == tenant_id,
                        webhooks.c.is_active.is_(True),
                    )
                )
                .mappings()
                .all()
            )
            for hook in hooks:
                hook_events = hook["events"] or []
                if "*" in hook_events or event_name in hook_events:
                    db.execute(
                        webhook_deliveries.insert().values(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            webhook_id=hook["id"],
                            event=event_name,
                            payload=payload,
                            status="queued",
                            status_code=None,
                            attempt_count=0,
                            next_attempt_at=now,
                            response_body=None,
                            created_at=now,
                        )
                    )
                    enqueued_count += 1
        return enqueued_count

    def list_webhook_deliveries(self, tenant_id: str, limit: int = 50):
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    select(webhook_deliveries)
                    .where(webhook_deliveries.c.tenant_id == tenant_id)
                    .order_by(webhook_deliveries.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]

    def get_due_webhook_deliveries(self, limit: int = 20):
        now = time.time()
        with self.transaction() as db:
            query = (
                select(
                    webhook_deliveries,
                    webhooks.c.target_url,
                    webhooks.c.secret,
                )
                .join(webhooks, webhook_deliveries.c.webhook_id == webhooks.c.id)
                .where(
                    webhook_deliveries.c.status.in_(["queued", "retrying"]),
                    webhook_deliveries.c.next_attempt_at <= now,
                    webhooks.c.is_active.is_(True),
                )
                .order_by(webhook_deliveries.c.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = db.execute(query).mappings().all()
            return [dict(r) for r in rows]

    def record_webhook_delivery_attempt(
        self,
        delivery_id: str,
        success: bool,
        status_code: int | None,
        response_body: str | None,
        next_attempt_at: float | None = None,
    ):
        with self.engine.begin() as db:
            status = "delivered" if success else ("retrying" if next_attempt_at else "failed")
            db.execute(
                update(webhook_deliveries)
                .where(webhook_deliveries.c.id == delivery_id)
                .values(
                    status=status,
                    status_code=status_code,
                    response_body=(response_body[:2000] if response_body else None),
                    attempt_count=webhook_deliveries.c.attempt_count + 1,
                    next_attempt_at=(next_attempt_at or 0),
                )
            )

    def redeliver_webhook(self, tenant_id: str, delivery_id: str) -> bool:
        with self.engine.begin() as db:
            result = db.execute(
                update(webhook_deliveries)
                .where(
                    webhook_deliveries.c.id == delivery_id,
                    webhook_deliveries.c.tenant_id == tenant_id,
                )
                .values(
                    status="queued",
                    next_attempt_at=time.time(),
                )
            )
            return bool(result.rowcount)

    # -------------------------------------------------------------------------
    # Tenant Tiers, Quotas, Usage, and Abuse Controls
    # -------------------------------------------------------------------------
    def get_tenant(self, tenant_id: str):
        cached = self.cache.get_tenant(tenant_id)
        if cached:
            return cached
        with self.engine.connect() as db:
            row = db.execute(select(tenants).where(tenants.c.id == tenant_id)).mappings().first()
            if row:
                data = dict(row)
                self.cache.set_tenant(tenant_id, data, ttl=60)
                return data
            return None

    def update_tenant_tier(
        self,
        tenant_id: str,
        tier: str,
        max_concurrent: int | None = None,
        max_daily_jobs: int | None = None,
        max_daily_bytes: int | None = None,
        storage_quota: int | None = None,
    ):
        self.cache.invalidate_tenant(tenant_id)
        values = {"tier": tier}
        if tier == "unlimited":
            values.update({
                "max_concurrent_jobs": -1,
                "max_daily_jobs": -1,
                "max_daily_bytes": -1,
                "storage_quota_bytes": -1,
            })
        else:
            if max_concurrent is not None:
                values["max_concurrent_jobs"] = max_concurrent
            if max_daily_jobs is not None:
                values["max_daily_jobs"] = max_daily_jobs
            if max_daily_bytes is not None:
                values["max_daily_bytes"] = max_daily_bytes
            if storage_quota is not None:
                values["storage_quota_bytes"] = storage_quota

        with self.transaction() as db:
            result = db.execute(update(tenants).where(tenants.c.id == tenant_id).values(**values))
            return bool(result.rowcount)

    def suspend_tenant(self, tenant_id: str, reason: str | None = None):
        self.cache.invalidate_tenant(tenant_id)
        with self.transaction() as db:
            result = db.execute(
                update(tenants)
                .where(tenants.c.id == tenant_id)
                .values(is_suspended=True, suspension_reason=reason)
            )
            return bool(result.rowcount)

    def unsuspend_tenant(self, tenant_id: str):
        self.cache.invalidate_tenant(tenant_id)
        with self.transaction() as db:
            result = db.execute(
                update(tenants)
                .where(tenants.c.id == tenant_id)
                .values(is_suspended=False, suspension_reason=None)
            )
            return bool(result.rowcount)

    def get_tenant_usage_today(self, tenant_id: str, date_str: str):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(tenant_usage).where(
                        tenant_usage.c.tenant_id == tenant_id,
                        tenant_usage.c.date == date_str,
                    )
                )
                .mappings()
                .first()
            )
            if row:
                return dict(row)
            return {
                "tenant_id": tenant_id,
                "date": date_str,
                "job_count": 0,
                "bytes_downloaded": 0,
                "updated_at": time.time(),
            }

    def increment_tenant_job_count(self, tenant_id: str, date_str: str):
        now = time.time()
        with self.engine.begin() as db:
            row = db.execute(
                select(tenant_usage.c.id).where(
                    tenant_usage.c.tenant_id == tenant_id,
                    tenant_usage.c.date == date_str,
                )
            ).first()
            if row:
                db.execute(
                    update(tenant_usage)
                    .where(tenant_usage.c.id == row[0])
                    .values(
                        job_count=tenant_usage.c.job_count + 1,
                        updated_at=now,
                    )
                )
            else:
                db.execute(
                    tenant_usage.insert().values(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        date=date_str,
                        job_count=1,
                        bytes_downloaded=0,
                        updated_at=now,
                    )
                )

    def increment_tenant_bytes(self, tenant_id: str, date_str: str, bytes_count: int):
        now = time.time()
        with self.engine.begin() as db:
            row = db.execute(
                select(tenant_usage.c.id).where(
                    tenant_usage.c.tenant_id == tenant_id,
                    tenant_usage.c.date == date_str,
                )
            ).first()
            if row:
                db.execute(
                    update(tenant_usage)
                    .where(tenant_usage.c.id == row[0])
                    .values(
                        bytes_downloaded=tenant_usage.c.bytes_downloaded + bytes_count,
                        updated_at=now,
                    )
                )
            else:
                db.execute(
                    tenant_usage.insert().values(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        date=date_str,
                        job_count=0,
                        bytes_downloaded=bytes_count,
                        updated_at=now,
                    )
                )

    def get_abuse_controls(self):
        cached = self.cache.get_abuse_controls()
        if cached:
            return cached
        with self.engine.connect() as db:
            row = db.execute(select(abuse_controls).where(abuse_controls.c.id == 1)).mappings().first()
            if row:
                data = dict(row)
            else:
                data = {
                    "id": 1,
                    "kill_switch_active": False,
                    "blocked_domains": [],
                    "allowed_domains": [],
                    "updated_at": time.time(),
                }
            self.cache.set_abuse_controls(data, ttl=60)
            return data

    def update_abuse_controls(
        self,
        kill_switch_active: bool | None = None,
        blocked_domains: list[str] | None = None,
        allowed_domains: list[str] | None = None,
    ):
        self.cache.invalidate_abuse_controls()
        values = {"updated_at": time.time()}
        if kill_switch_active is not None:
            values["kill_switch_active"] = kill_switch_active
        if blocked_domains is not None:
            values["blocked_domains"] = blocked_domains
        if allowed_domains is not None:
            values["allowed_domains"] = allowed_domains

        with self.engine.begin() as db:
            db.execute(update(abuse_controls).where(abuse_controls.c.id == 1).values(**values))
        return self.get_abuse_controls()

    # -------------------------------------------------------------------------
    # Media Lifecycle, Soft Deletes, and Poison-Job Reaper
    # -------------------------------------------------------------------------
    def soft_delete_job(self, job_id: str, *, tenant_id: str | None = None) -> bool:
        now = time.time()
        with self.transaction() as db:
            row = self._locked(db, job_id, tenant_id)
            payload = dict(row["payload"])
            payload["deleted_at"] = now
            if payload.get("filename"):
                self.cache.invalidate_file(row["tenant_id"], payload["filename"])
            result = db.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(deleted_at=now, payload=payload, version=row["version"] + 1)
            )
            return bool(result.rowcount)

    def soft_delete_by_filename(self, filename: str, *, tenant_id: str = "default-tenant") -> str | None:
        now = time.time()
        self.cache.invalidate_file(tenant_id, filename)
        with self.transaction() as db:
            query = select(jobs).where(
                jobs.c.tenant_id == tenant_id,
                jobs.c.status == "completed",
                or_(jobs.c.filename == filename, jobs.c.payload["filename"].as_string() == filename),
                jobs.c.deleted_at.is_(None),
            ).with_for_update()
            row = db.execute(query).mappings().first()
            if not row:
                return None
            payload = dict(row["payload"])
            payload["deleted_at"] = now
            db.execute(
                update(jobs)
                .where(jobs.c.id == row["id"])
                .values(deleted_at=now, payload=payload, version=row["version"] + 1)
            )
            return row["id"]

    def find_expired_media(self, retention_seconds: float, limit: int = 100):
        cutoff = time.time() - retention_seconds
        with self.engine.connect() as db:
            query = (
                select(jobs.c.id, jobs.c.tenant_id, jobs.c.storage_key, jobs.c.deleted_at)
                .where(jobs.c.deleted_at.is_not(None), jobs.c.deleted_at < cutoff)
                .limit(limit)
            )
            return [dict(r) for r in db.execute(query).mappings().all()]

    def hard_delete_job(self, job_id: str) -> bool:
        with self.transaction() as db:
            result = db.execute(delete(jobs).where(jobs.c.id == job_id))
            return bool(result.rowcount)

    def release_job_lease(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self.engine.begin() as db:
            result = db.execute(
                update(jobs)
                .where(jobs.c.id == job_id, jobs.c.lease_owner == owner, ~jobs.c.status.in_(TERMINAL_STATUSES))
                .values(lease_owner=None, lease_until=0, dispatch_after=now)
            )
            return bool(result.rowcount)

    def reap_stuck_jobs(self, max_lease_seconds: float = 300, max_attempts: int = 3):
        now = time.time()
        reaped_count = 0
        poison_count = 0
        with self.transaction() as db:
            stuck_rows = (
                db.execute(
                    select(jobs)
                    .where(
                        ~jobs.c.status.in_(TERMINAL_STATUSES),
                        jobs.c.lease_until < now,
                    )
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for row in stuck_rows:
                if row["attempt_count"] >= max_attempts:
                    payload = dict(row["payload"])
                    payload.update({
                        "status": "error",
                        "error": f"Job exceeded maximum execution attempts ({row['attempt_count']}/{max_attempts}). Quarantined as poison job.",
                        "completed_at": now,
                    })
                    db.execute(
                        update(jobs)
                        .where(jobs.c.id == row["id"])
                        .values(
                            status="error",
                            payload=payload,
                            lease_owner=None,
                            lease_until=0,
                            version=row["version"] + 1,
                        )
                    )
                    poison_count += 1
                else:
                    payload = dict(row["payload"])
                    payload["status"] = "queued"
                    db.execute(
                        update(jobs)
                        .where(jobs.c.id == row["id"])
                        .values(
                            status="queued",
                            payload=payload,
                            lease_owner=None,
                            lease_until=0,
                            dispatch_after=now,
                        )
                    )
                    reaped_count += 1
        return {"reaped": reaped_count, "poison": poison_count}

    # -------------------------------------------------------------------------
    # User Preferences
    # -------------------------------------------------------------------------
    def get_user_preferences(self, user_id: str, tenant_id: str) -> dict[str, Any] | None:
        cached = self.cache.get_preferences(user_id)
        if cached:
            return cached

        with self.engine.connect() as db:
            row = db.execute(
                select(user_preferences.c.preferences).where(
                    user_preferences.c.user_id == user_id,
                    user_preferences.c.tenant_id == tenant_id,
                )
            ).scalars().first()
            if row:
                self.cache.set_preferences(user_id, row, ttl=300)
                return row
            return None

    def set_user_preferences(self, user_id: str, tenant_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        self.cache.invalidate_preferences(user_id)
        with self.transaction() as db:
            existing = db.execute(
                select(user_preferences.c.user_id).where(
                    user_preferences.c.user_id == user_id,
                    user_preferences.c.tenant_id == tenant_id,
                )
            ).scalars().first()
            if existing:
                db.execute(
                    update(user_preferences)
                    .where(
                        user_preferences.c.user_id == user_id,
                        user_preferences.c.tenant_id == tenant_id,
                    )
                    .values(preferences=prefs, updated_at=now)
                )
            else:
                db.execute(
                    user_preferences.insert().values(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        preferences=prefs,
                        updated_at=now,
                    )
                )
        self.cache.set_preferences(user_id, prefs, ttl=300)
        return prefs

    # -------------------------------------------------------------------------
    # Batch Processing Lookups
    # -------------------------------------------------------------------------
    def list_jobs_by_batch(self, batch_id: str, *, tenant_id: str = "default-tenant") -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(
                select(jobs.c.payload)
                .where(
                    jobs.c.tenant_id == tenant_id,
                    jobs.c.deleted_at.is_(None),
                )
                .order_by(jobs.c.created_at.asc())
            ).scalars().all()
            return [row for row in rows if row.get("batch_id") == batch_id]

    def close(self):
        self.cache.close()
        self.engine.dispose()
