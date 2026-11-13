"""Link follow-up tasks to the imported message they answer."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "campaign_tasks",
        sa.Column(
            "communication_id",
            sa.Uuid(),
            sa.ForeignKey(
                "communications.id",
                ondelete="SET NULL",
                name="campaign_tasks_communication_id_fkey",
            ),
        ),
    )
    op.create_index("ix_campaign_tasks_communication_id", "campaign_tasks", ["communication_id"])
    # Earlier missed-reply tasks named their message only through the seed key.
    op.execute(
        """
        UPDATE campaign_tasks AS t
        SET communication_id = c.id
        FROM communications AS c
        WHERE t.communication_id IS NULL
          AND t.seed_key = 'fu-' || left(c.id::text, 8) || '-rpl'
        """
    )


def downgrade():
    op.drop_index("ix_campaign_tasks_communication_id", table_name="campaign_tasks")
    op.drop_column("campaign_tasks", "communication_id")
