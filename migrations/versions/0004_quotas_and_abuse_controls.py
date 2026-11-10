"""Quotas, tenant tiers, daily usage tracking, and abuse controls."""
from alembic import op
import sqlalchemy as sa

revision = "0004_quotas_and_abuse_controls"
down_revision = "0003_api_keys_and_webhooks"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Expand tenants table with tier, quotas, and suspension controls
    op.add_column("tenants", sa.Column("tier", sa.String(20), nullable=False, server_default="free"))
    op.add_column("tenants", sa.Column("is_suspended", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tenants", sa.Column("suspension_reason", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("tenants", sa.Column("max_daily_jobs", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("tenants", sa.Column("max_daily_bytes", sa.BigInteger(), nullable=False, server_default="5368709120"))
    op.add_column("tenants", sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=False, server_default="21474836480"))

    # 2. Daily tenant usage table
    op.create_table(
        "tenant_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),  # YYYY-MM-DD
        sa.Column("job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("tenant_id", "date", name="uq_tenant_usage_date"),
    )
    op.create_index("ix_tenant_usage_tenant_id", "tenant_usage", ["tenant_id"])
    op.create_index("ix_tenant_usage_date", "tenant_usage", ["date"])

    # 3. System-wide abuse controls & kill switch singleton table
    op.create_table(
        "abuse_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kill_switch_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blocked_domains", sa.JSON(), nullable=False),
        sa.Column("allowed_domains", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("abuse_controls")
    op.drop_table("tenant_usage")
    op.drop_column("tenants", "storage_quota_bytes")
    op.drop_column("tenants", "max_daily_bytes")
    op.drop_column("tenants", "max_daily_jobs")
    op.drop_column("tenants", "max_concurrent_jobs")
    op.drop_column("tenants", "suspension_reason")
    op.drop_column("tenants", "is_suspended")
    op.drop_column("tenants", "tier")

