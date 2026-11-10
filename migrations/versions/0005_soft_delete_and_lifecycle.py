"""Soft deletes, storage key indexing, and lifecycle tracking on media_jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0005_soft_delete_and_lifecycle"
down_revision = "0004_quotas_and_abuse_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("media_jobs", sa.Column("deleted_at", sa.Float(), nullable=True))
    op.create_index("ix_media_jobs_deleted_at", "media_jobs", ["deleted_at"])
    op.add_column("media_jobs", sa.Column("storage_key", sa.String(512), nullable=True))
    op.add_column("media_jobs", sa.Column("last_heartbeat_at", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("media_jobs", "last_heartbeat_at")
    op.drop_column("media_jobs", "storage_key")
    op.drop_index("ix_media_jobs_deleted_at", table_name="media_jobs")
    op.drop_column("media_jobs", "deleted_at")

