"""Add target_date and series to content_items for campaign scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("content_items", sa.Column("target_date", sa.Date(), nullable=True))
    op.add_column("content_items", sa.Column("series", sa.String(80), nullable=True))
    op.create_index(
        "ix_content_items_series",
        "content_items",
        ["series"],
        postgresql_where=sa.text("series IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ix_content_items_series", table_name="content_items")
    op.drop_column("content_items", "series")
    op.drop_column("content_items", "target_date")
