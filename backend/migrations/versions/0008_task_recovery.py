"""Bounded durable work recovery and fenced fetch claims; preserve existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("diagnostic_runs", "job_fetches"):
        op.add_column(table, sa.Column("recovery_deadline", sa.DateTime(timezone=True)))
        op.add_column(table, sa.Column("last_dispatched_at", sa.DateTime(timezone=True)))
        op.add_column(
            table, sa.Column("delivery_attempts", sa.Integer(), server_default="0", nullable=False)
        )
    op.add_column("diagnostic_runs", sa.Column("error_message", sa.String(300)))
    op.add_column("job_fetches", sa.Column("execution_token", sa.Uuid()))
    op.add_column("job_fetches", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.drop_constraint("run_status", "diagnostic_runs", type_="check")
    op.create_check_constraint(
        "run_status",
        "diagnostic_runs",
        "status IN ('queued', 'succeeded', 'publish_failed', 'failed')",
    )
    op.drop_index("ix_job_fetches_active_source", table_name="job_fetches")
    op.create_index(
        "ix_job_fetches_active_source",
        "job_fetches",
        ["source"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running') OR "
            "(status = 'publish_failed' AND recovery_deadline IS NOT NULL)"
        ),
    )
    # Existing history is deliberately not enrolled in automatic provider replay.


def downgrade():
    connection = op.get_bind()
    for table in ("diagnostic_runs", "job_fetches"):
        if connection.scalar(
            sa.text(f"SELECT count(*) FROM {table} WHERE recovery_deadline IS NOT NULL")
        ):
            raise RuntimeError("Recovery history exists; preserve it before downgrade.")
    if connection.scalar(sa.text("SELECT count(*) FROM diagnostic_runs WHERE status='failed'")):
        raise RuntimeError("Failed diagnostic history exists; preserve it before downgrade.")
    op.drop_index("ix_job_fetches_active_source", table_name="job_fetches")
    op.create_index(
        "ix_job_fetches_active_source",
        "job_fetches",
        ["source"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_constraint("run_status", "diagnostic_runs", type_="check")
    op.create_check_constraint(
        "run_status", "diagnostic_runs", "status IN ('queued', 'succeeded', 'publish_failed')"
    )
    op.drop_column("diagnostic_runs", "error_message")
    op.drop_column("job_fetches", "execution_token")
    op.drop_column("job_fetches", "lease_expires_at")
    for table in ("diagnostic_runs", "job_fetches"):
        for column in ("delivery_attempts", "last_dispatched_at", "recovery_deadline"):
            op.drop_column(table, column)
