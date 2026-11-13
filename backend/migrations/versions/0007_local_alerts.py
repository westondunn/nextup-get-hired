"""Opt-in local inbox and durable per-search duplicate suppression."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "saved_searches",
        sa.Column("alerts_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "saved_searches",
        sa.Column("alert_min_score", sa.Integer(), server_default="70", nullable=False),
    )
    op.add_column(
        "saved_searches",
        sa.Column("alert_check_status", sa.String(30), server_default="disabled", nullable=False),
    )
    op.add_column("saved_searches", sa.Column("alert_checked_at", sa.DateTime(timezone=True)))
    op.add_column("saved_searches", sa.Column("alert_worker", sa.String(255)))
    op.create_check_constraint(
        "alert_min_score_range", "saved_searches", "alert_min_score BETWEEN 0 AND 100"
    )
    op.create_table(
        "job_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "search_id",
            sa.Uuid(),
            sa.ForeignKey("saved_searches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_key", sa.String(64), nullable=False),
        sa.Column("search_name", sa.String(80), nullable=False),
        sa.Column("job", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("search_id", "job_key", name="alert_search_job_key"),
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM job_alerts")) or connection.scalar(
        sa.text("SELECT count(*) FROM saved_searches WHERE alerts_enabled")
    ):
        raise RuntimeError("Alert data exists; preserve it before downgrade.")
    op.drop_table("job_alerts")
    op.drop_constraint("alert_min_score_range", "saved_searches", type_="check")
    for column in (
        "alert_worker",
        "alert_checked_at",
        "alert_check_status",
        "alert_min_score",
        "alerts_enabled",
    ):
        op.drop_column("saved_searches", column)
