"""Allow imported communications to be dismissed from the review queue."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TABLE = "communications"
NAME = "comm_status"
OLD = "status IN ('draft','copied','sent','received','private_note')"
NEW = "status IN ('draft','copied','sent','received','private_note','dismissed')"


def upgrade():
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, NEW)


def downgrade():
    # Dismissed rows become private notes: still stored and deduplicated, never
    # queued for review or matched by the missed-reply rule.
    op.execute(sa.text("UPDATE communications SET status='private_note' WHERE status='dismissed'"))
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(NAME, TABLE, OLD)
