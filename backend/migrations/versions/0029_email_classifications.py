"""Email classifications written by the external n8n labeler and read by the Gmail sync.

n8n upserts one row per Gmail message (contract in docs/CORRESPONDENCE_SYNC.md); the
sync merges it into ``communications.detection['n8n']`` as a hint and stamps
``applied_at``. n8n never writes ``communications``.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

CLASSES = "'new_application','opportunity','existing_company','not_relevant'"

# The contract passes string_to_array(NULLIF($4, ''), '|'), which is NULL when the
# model found no company; a column default never applies to an explicit NULL.
DEFAULTS_FUNCTION = """
CREATE OR REPLACE FUNCTION nextup_email_classification_defaults() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.companies := coalesce(NEW.companies, '{}'::text[]);
    RETURN NEW;
END
$$
"""

# The n8n login is read-only everywhere else; it may write only this table.
GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n') THEN
        GRANT SELECT, INSERT, UPDATE ON email_classifications TO n8n;
    END IF;
END
$$
"""


def upgrade():
    op.create_table(
        "email_classifications",
        sa.Column("gmail_message_id", sa.String(200), primary_key=True),
        sa.Column("thread_id", sa.String(200)),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column(
            "companies",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey(
                "companies.id",
                ondelete="SET NULL",
                name="email_classifications_company_id_fkey",
            ),
        ),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"classification IN ({CLASSES})", name="email_classification_value"),
    )
    op.create_index("ix_email_classifications_company_id", "email_classifications", ["company_id"])
    op.create_index(
        "ix_email_classifications_unapplied",
        "email_classifications",
        ["classified_at"],
        postgresql_where=sa.text("applied_at IS NULL"),
    )
    op.execute(DEFAULTS_FUNCTION)
    op.execute(
        "CREATE TRIGGER email_classification_defaults BEFORE INSERT OR UPDATE"
        " ON email_classifications FOR EACH ROW"
        " EXECUTE FUNCTION nextup_email_classification_defaults()"
    )
    op.execute(GRANT)


def downgrade():
    # Hints merged into communications go with the table they came from.
    op.execute("UPDATE communications SET detection = detection - 'n8n' WHERE detection ? 'n8n'")
    op.drop_table("email_classifications")  # drops its trigger and indexes too
    op.execute("DROP FUNCTION IF EXISTS nextup_email_classification_defaults()")
