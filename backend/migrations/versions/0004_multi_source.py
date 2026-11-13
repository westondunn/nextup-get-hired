"""Retain source provenance and add grouping keys without deleting existing jobs."""

import hashlib
import json
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for table, name in (("jobs", "job_source"), ("job_fetches", "fetch_source")):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name, table, "source IN ('sample', 'sample_greenhouse', 'adzuna', 'greenhouse')"
        )
    op.add_column("jobs", sa.Column("dedupe_key", sa.String(64), nullable=True))
    op.add_column(
        "jobs", sa.Column("date_kind", sa.String(8), server_default="posted", nullable=False)
    )
    # Keep this backfill self-contained so future application changes cannot alter it.
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text("SELECT source, external_id, company, title, location FROM jobs")
        )
        .mappings()
        .all()
    )
    for row in rows:
        parts = [
            " ".join(unicodedata.normalize("NFKC", row[field]).casefold().split())
            for field in ("company", "title", "location")
        ]
        if not all(parts) or parts[0] == "company not provided":
            parts = [row["source"], row["external_id"]]
        namespace = "sample" if row["source"].startswith("sample") else "live"
        key = hashlib.sha256(
            json.dumps([namespace, *parts], ensure_ascii=False).encode()
        ).hexdigest()
        connection.execute(
            sa.text(
                "UPDATE jobs SET dedupe_key=:key WHERE source=:source AND external_id=:external_id"
            ),
            {"key": key, "source": row["source"], "external_id": row["external_id"]},
        )
    op.alter_column("jobs", "dedupe_key", nullable=False)
    op.create_index("ix_jobs_dedupe_key", "jobs", ["dedupe_key"])


def downgrade():
    # Refuse destructive rollback rather than silently deleting new-source data.
    connection = op.get_bind()
    for table in ("jobs", "job_fetches"):
        if connection.scalar(
            sa.text(
                f"SELECT count(*) FROM {table} WHERE source IN ('greenhouse', 'sample_greenhouse')"
            )
        ):
            raise RuntimeError(
                "Cannot downgrade while Greenhouse records exist; preserve/export them first."
            )
    op.drop_index("ix_jobs_dedupe_key", table_name="jobs")
    op.drop_column("jobs", "dedupe_key")
    op.drop_column("jobs", "date_kind")
    for table, name in (("jobs", "job_source"), ("job_fetches", "fetch_source")):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, "source IN ('sample', 'adzuna')")
