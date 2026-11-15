"""Stored Google connection: the user's own OAuth client and the grant made with it.

See docs/decisions/0003-google-connection.md, section 6. There is one connection, so the
table holds at most one row. The client secret and the refresh token are stored only as
values sealed by ``app.token_vault``; the checks below refuse anything that is not in that
form, so a mistake in the application cannot leave a credential in the table as plain text.
No access token is stored.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "oss_0031"
down_revision = "oss_0030"
branch_labels = None
depends_on = None

STATES = "'not_connected','connected','needs_reauthorization'"
# A format version, a dot, then URL-safe base64. See app.token_vault.
SEALED = r"'^v[0-9]+\.[A-Za-z0-9_-]+=*$'"


def upgrade():
    op.create_table(
        "google_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_sealed", sa.Text(), nullable=False),
        sa.Column("refresh_token_sealed", sa.Text()),
        sa.Column("key_version", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(30), nullable=False, server_default="not_connected"),
        sa.Column(
            "granted_scopes",
            postgresql.ARRAY(sa.String(200)),
            nullable=False,
            server_default=sa.text("'{}'::character varying[]"),
        ),
        sa.Column("account_address", sa.String(320)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="single_google_connection"),
        sa.CheckConstraint("client_id <> ''", name="google_connection_client_id"),
        sa.CheckConstraint(f"state IN ({STATES})", name="google_connection_state"),
        sa.CheckConstraint("key_version >= 1", name="google_connection_key_version"),
        sa.CheckConstraint(
            f"client_secret_sealed ~ {SEALED}", name="google_connection_client_secret_sealed"
        ),
        sa.CheckConstraint(
            f"refresh_token_sealed ~ {SEALED}", name="google_connection_refresh_token_sealed"
        ),
        # A refresh token is held exactly when a grant has been stored.
        sa.CheckConstraint(
            "(state = 'not_connected') = (refresh_token_sealed IS NULL)",
            name="google_connection_grant",
        ),
    )


def downgrade():
    # Dropping the table would discard the user's client secret and leave a grant at Google
    # that nothing here can revoke any more. The row has to be removed first.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM google_connections")):
        raise RuntimeError("A stored Google connection exists; remove it before downgrade.")
    op.drop_table("google_connections")
