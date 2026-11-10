"""Add user_preferences table for Phase 8 user preferences persistence."""
from alembic import op
import sqlalchemy as sa

revision = "0007_user_preferences"
down_revision = "0006_promote_columns_and_indices"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_user_preferences_tenant_user", "user_preferences", ["tenant_id", "user_id"])


def downgrade():
    op.drop_index("ix_user_preferences_tenant_user", table_name="user_preferences")
    op.drop_table("user_preferences")

