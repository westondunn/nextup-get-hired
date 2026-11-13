"""Create durable diagnostic execution records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "diagnostic_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("worker", sa.String(255)),
        sa.Column("result", postgresql.JSONB()),
        sa.CheckConstraint(
            "status IN ('queued', 'succeeded', 'publish_failed')", name="run_status"
        ),
        sa.CheckConstraint("source IN ('manual', 'scheduler')", name="run_source"),
    )
    op.create_index("ix_diagnostic_runs_completed_at", "diagnostic_runs", ["completed_at"])


def downgrade():
    op.drop_table("diagnostic_runs")
