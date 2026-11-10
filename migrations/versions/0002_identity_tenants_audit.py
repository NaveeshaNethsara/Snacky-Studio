"""Tenant workspaces, per-user accounts, RBAC, and tamper-evident audit logs."""
import time
from alembic import op
import sqlalchemy as sa

revision = "0002_identity_tenants_audit"
down_revision = "0001_shared_jobs"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # 2. Users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("token_version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 3. Audit logs table (tamper-evident hash chain)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False, server_default="0" * 64),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # 4. Expand media_jobs with tenant_id, user_id, attempt_count
    with op.batch_alter_table("media_jobs") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"))
        batch_op.create_index("ix_media_jobs_tenant_id", ["tenant_id"])
        batch_op.create_index("ix_media_jobs_user_id", ["user_id"])

    # 5. Insert default tenant and backfill existing jobs
    now = time.time()
    op.execute(
        sa.text(
            f"INSERT INTO tenants (id, name, slug, created_at, is_active) "
            f"VALUES ('default-tenant', 'Default Workspace', 'default', {now}, true)"
        )
    )
    op.execute(sa.text("UPDATE media_jobs SET tenant_id = 'default-tenant' WHERE tenant_id IS NULL"))


def downgrade():
    with op.batch_alter_table("media_jobs") as batch_op:
        batch_op.drop_index("ix_media_jobs_user_id")
        batch_op.drop_index("ix_media_jobs_tenant_id")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("user_id")
        batch_op.drop_column("tenant_id")

    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("tenants")

