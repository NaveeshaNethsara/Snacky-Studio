"""Shared job snapshots, worker leases, and the dispatch outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0001_shared_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_jobs",sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("created_at",sa.Float,nullable=False),sa.Column("status",sa.String(24),nullable=False),
        sa.Column("version",sa.Integer,nullable=False),sa.Column("lease_owner",sa.String(36)),
        sa.Column("lease_until",sa.Float,nullable=False),sa.Column("dispatch_after",sa.Float,nullable=False),
        sa.Column("payload",sa.JSON,nullable=False))
    for name in ("created_at","status","dispatch_after"):
        op.create_index("ix_media_jobs_"+name,"media_jobs",[name])
    op.create_table("queue_admission",sa.Column("id",sa.Integer,primary_key=True))
    op.execute(sa.text("INSERT INTO queue_admission (id) VALUES (1)"))


def downgrade():
    op.drop_table("queue_admission")
    op.drop_table("media_jobs")
