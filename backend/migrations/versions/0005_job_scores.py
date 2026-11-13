"""Cache versioned score explanations without modifying source or profile data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("score", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("score_breakdown", postgresql.JSONB(), nullable=True))
    op.add_column("jobs", sa.Column("score_signature", sa.String(64), nullable=True))
    op.create_check_constraint(
        "job_score_range", "jobs", "score IS NULL OR score BETWEEN 0 AND 100"
    )


def downgrade():
    op.drop_constraint("job_score_range", "jobs", type_="check")
    op.drop_column("jobs", "score_signature")
    op.drop_column("jobs", "score_breakdown")
    op.drop_column("jobs", "score")
