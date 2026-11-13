"""Profile-driven employer feeds, durable scheduling, and saved job references."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None
OLD = "'sample','sample_greenhouse','adzuna','greenhouse'"
NEW = OLD + ",'lever','ashby','reference'"


def upgrade():
    for table, name in (
        ("jobs", "job_source"),
        ("job_fetches", "fetch_source"),
        ("saved_searches", "saved_search_source"),
    ):
        op.drop_constraint(name, table, type_="check")
        values = (
            (
                "'sample','sample_greenhouse','sample_all','adzuna','greenhouse',"
                "'lever','ashby','reference','all'"
            )
            if table == "saved_searches"
            else NEW
        )
        op.create_check_constraint(name, table, f"source IN ({values})")
    op.add_column(
        "job_fetches", sa.Column("board_key", sa.String(100), server_default="", nullable=False)
    )
    op.drop_index("ix_job_fetches_active_source", table_name="job_fetches")
    op.create_index(
        "ix_job_fetches_active_source",
        "job_fetches",
        ["source", "board_key"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued','running') OR "
            "(status='publish_failed' AND recovery_deadline IS NOT NULL)"
        ),
    )
    op.create_table(
        "discovery_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("interval_hours", sa.Integer(), server_default="24", nullable=False),
        sa.Column("min_score", sa.Integer(), server_default="20", nullable=False),
        sa.Column("boards", postgresql.JSONB(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id=1", name="single_discovery_settings"),
        sa.CheckConstraint("interval_hours BETWEEN 6 AND 168", name="discovery_interval"),
        sa.CheckConstraint("min_score BETWEEN 0 AND 100", name="discovery_score"),
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM discovery_settings")):
        raise RuntimeError("Discovery configuration exists; preserve it before downgrade.")
    for table in ("jobs", "job_fetches", "saved_searches"):
        if connection.scalar(
            sa.text(f"SELECT count(*) FROM {table} WHERE source IN ('lever','ashby','reference')")
        ):
            raise RuntimeError("Discovery source data exists; preserve it before downgrade.")
    if connection.scalar(sa.text("SELECT count(*) FROM job_fetches WHERE board_key<>''")):
        raise RuntimeError("Employer fetch history exists; preserve it before downgrade.")
    op.drop_table("discovery_settings")
    op.drop_index("ix_job_fetches_active_source", table_name="job_fetches")
    op.drop_column("job_fetches", "board_key")
    op.create_index(
        "ix_job_fetches_active_source",
        "job_fetches",
        ["source"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued','running') OR "
            "(status='publish_failed' AND recovery_deadline IS NOT NULL)"
        ),
    )
    for table, name in (
        ("jobs", "job_source"),
        ("job_fetches", "fetch_source"),
        ("saved_searches", "saved_search_source"),
    ):
        op.drop_constraint(name, table, type_="check")
        values = (
            ("'sample','sample_greenhouse','sample_all','adzuna','greenhouse','all'")
            if table == "saved_searches"
            else OLD
        )
        op.create_check_constraint(name, table, f"source IN ({values})")
