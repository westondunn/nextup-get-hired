"""Job ratings: "more like this" / "less like this" feedback that tunes scoring."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_ratings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_key", sa.String(64), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company", sa.String(300), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("job_key", name="job_rating_job_key"),
        sa.CheckConstraint("rating IN (-1, 1)", name="job_rating_value"),
    )


def downgrade():
    # Ratings are the user's own judgments; refuse to discard them silently.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM job_ratings)")).scalar():
        raise RuntimeError(
            "Cannot downgrade while job ratings exist; clear them on the Job Board first."
        )
    op.drop_table("job_ratings")
