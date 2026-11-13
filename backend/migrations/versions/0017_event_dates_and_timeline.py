"""Add event_date to pursuit_events for backdating, and actor/source/evidence fields."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pursuit_events", sa.Column("event_date", sa.Date()))
    op.add_column("pursuit_events", sa.Column("actor", sa.String(200), server_default=""))
    op.add_column("pursuit_events", sa.Column("source", sa.String(200), server_default=""))
    op.add_column("pursuit_events", sa.Column("evidence", sa.String(500), server_default=""))


def downgrade():
    op.drop_column("pursuit_events", "evidence")
    op.drop_column("pursuit_events", "source")
    op.drop_column("pursuit_events", "actor")
    op.drop_column("pursuit_events", "event_date")
