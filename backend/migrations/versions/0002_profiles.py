"""Add the single local search profile."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skills", postgresql.ARRAY(sa.String(100)), nullable=False),
        sa.Column("target_titles", postgresql.ARRAY(sa.String(120)), nullable=False),
        sa.Column("location", sa.String(160), nullable=False),
        sa.Column("work_preferences", postgresql.ARRAY(sa.String(10)), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="single_profile"),
    )


def downgrade():
    op.drop_table("profiles")
