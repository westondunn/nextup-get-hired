"""Remove sample sources from production CHECK constraints."""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    # Delete any lingering sample rows first so the tighter constraints can apply.
    op.execute("DELETE FROM jobs WHERE source IN ('sample', 'sample_greenhouse')")
    op.execute("DELETE FROM job_fetches WHERE source IN ('sample', 'sample_greenhouse')")
    op.execute(
        "DELETE FROM saved_searches WHERE source IN ('sample', 'sample_greenhouse', 'sample_all')"
    )

    op.drop_constraint("fetch_source", "job_fetches")
    op.create_check_constraint(
        "fetch_source",
        "job_fetches",
        "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference')",
    )

    op.drop_constraint("job_source", "jobs")
    op.create_check_constraint(
        "job_source",
        "jobs",
        "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference')",
    )

    op.drop_constraint("saved_search_source", "saved_searches")
    op.create_check_constraint(
        "saved_search_source",
        "saved_searches",
        "source IN ('adzuna', 'greenhouse', 'lever', 'ashby', 'reference', 'all')",
    )


def downgrade():
    op.drop_constraint("fetch_source", "job_fetches")
    op.create_check_constraint(
        "fetch_source",
        "job_fetches",
        "source IN ('sample', 'sample_greenhouse', 'adzuna', 'greenhouse', "
        "'lever', 'ashby', 'reference')",
    )

    op.drop_constraint("job_source", "jobs")
    op.create_check_constraint(
        "job_source",
        "jobs",
        "source IN ('sample', 'sample_greenhouse', 'adzuna', 'greenhouse', "
        "'lever', 'ashby', 'reference')",
    )

    op.drop_constraint("saved_search_source", "saved_searches")
    op.create_check_constraint(
        "saved_search_source",
        "saved_searches",
        "source IN ('sample', 'sample_greenhouse', 'sample_all', "
        "'adzuna', 'greenhouse', 'lever', 'ashby', 'reference', 'all')",
    )
