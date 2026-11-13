"""Store resume files with their versions and record which version a pursuit used."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

FILE_COLUMNS = (
    sa.Column("file_name", sa.String(255)),
    sa.Column("file_type", sa.String(100)),
    sa.Column("file_size", sa.Integer()),
    sa.Column("file_uploaded_at", sa.DateTime(timezone=True)),
    sa.Column("file_data", sa.LargeBinary()),
)


def upgrade():
    for column in FILE_COLUMNS:
        op.add_column("resume_versions", column)
    op.add_column(
        "pursuits",
        sa.Column(
            "resume_version_id",
            sa.Uuid(),
            sa.ForeignKey(
                "resume_versions.id",
                ondelete="SET NULL",
                name="pursuits_resume_version_id_fkey",
            ),
        ),
    )
    op.create_index("ix_pursuits_resume_version_id", "pursuits", ["resume_version_id"])


def downgrade():
    op.drop_index("ix_pursuits_resume_version_id", table_name="pursuits")
    op.drop_column("pursuits", "resume_version_id")
    for column in reversed(FILE_COLUMNS):
        op.drop_column("resume_versions", column.name)
