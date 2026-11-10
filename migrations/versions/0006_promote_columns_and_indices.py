"""Promote filename to indexed column and add composite performance indexes."""
from alembic import op
import sqlalchemy as sa

revision = "0006_promote_columns_and_indices"
down_revision = "0005_soft_delete_and_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add filename column
    op.add_column("media_jobs", sa.Column("filename", sa.String(512), nullable=True))

    # 2. Backfill existing filenames from JSON payload if present
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE media_jobs "
                "SET filename = payload->>'filename' "
                "WHERE payload->>'filename' IS NOT NULL AND filename IS NULL"
            )
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                "UPDATE media_jobs "
                "SET filename = json_extract(payload, '$.filename') "
                "WHERE json_extract(payload, '$.filename') IS NOT NULL AND filename IS NULL"
            )
        )

    # 3. Create high-performance composite B-Tree indexes
    op.create_index("ix_media_jobs_tenant_filename", "media_jobs", ["tenant_id", "filename"])
    op.create_index(
        "ix_media_jobs_tenant_deleted_status",
        "media_jobs",
        ["tenant_id", "deleted_at", "status"],
    )
    op.create_index(
        "ix_media_jobs_tenant_created_at",
        "media_jobs",
        ["tenant_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_media_jobs_tenant_created_at", table_name="media_jobs")
    op.drop_index("ix_media_jobs_tenant_deleted_status", table_name="media_jobs")
    op.drop_index("ix_media_jobs_tenant_filename", table_name="media_jobs")
    op.drop_column("media_jobs", "filename")

