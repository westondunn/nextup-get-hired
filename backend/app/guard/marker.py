"""Guard-owned database state: the environment marker and the authorization ledger.

Both tables are created by the guard inside the INIT transaction (never by a revision,
so the 0001-0029 graph is unaffected) and are owned by the migration owner. The
runtime role gets SELECT on the marker only and nothing on the ledger; it must never
write ``alembic_version`` either. ``lock_down`` re-applies those rules after every
authorized migration, because the bootstrap's default privileges grant DML on every
new table to the runtime role.

Functions take an ``execute(sql, params)`` callable returning rows, so they are testable
without a database. Only ``apply`` (inside its authorized transaction) calls them.
"""

import re
from datetime import UTC, datetime

from app.guard.errors import GuardRefused
from app.guard.facts import LEDGER_TABLE, MARKER_TABLE

_ROLE = re.compile(r"^nextup_(dev|stg|ci)_app$")

CREATE_MARKER = f"""
CREATE TABLE {MARKER_TABLE} (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    environment text NOT NULL CHECK (environment IN ('dev', 'staging', 'ci', 'test', 'personal')),
    lineage text NOT NULL CHECK (lineage = 'nextup'),
    database_name text NOT NULL,
    cluster_name text NOT NULL,
    system_identifier text NOT NULL,
    instance_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    guard_version text NOT NULL,
    adopted_approval_sha256 text
)"""

CREATE_LEDGER = f"""
CREATE TABLE {LEDGER_TABLE} (
    nonce_sha256 text PRIMARY KEY CHECK (nonce_sha256 ~ '^[0-9a-f]{{64}}$'),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz NOT NULL DEFAULT now(),
    operation text NOT NULL,
    target text
)"""

INSERT_MARKER = (
    f"INSERT INTO {MARKER_TABLE} (environment, lineage, database_name, cluster_name, "
    "system_identifier, instance_id, guard_version) "
    "VALUES (:environment, 'nextup', :database_name, :cluster_name, :system_identifier, "
    "CAST(:instance_id AS uuid), :guard_version)"
)

CONSUME = (
    f"INSERT INTO {LEDGER_TABLE} (nonce_sha256, expires_at, operation, target) "
    "VALUES (:nonce, :expires_at, :operation, :target) "
    "ON CONFLICT (nonce_sha256) DO NOTHING RETURNING 1"
)


def _app_role(app_role: str) -> str:
    if not _ROLE.fullmatch(app_role):
        raise GuardRefused("NXG-I04")
    return f'"{app_role}"'


def lock_down_statements(app_role: str) -> tuple[str, ...]:
    role = _app_role(app_role)
    return (
        f"REVOKE ALL ON {MARKER_TABLE}, {LEDGER_TABLE} FROM PUBLIC, {role}",
        f"GRANT SELECT ON {MARKER_TABLE} TO {role}",
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON alembic_version "
        f"FROM PUBLIC, {role}",
    )


def create_tables(execute, app_role: str) -> None:
    """INIT only: both guard tables, then the privilege lock-down for them."""
    execute(CREATE_MARKER, None)
    execute(CREATE_LEDGER, None)
    role = _app_role(app_role)
    execute(f"REVOKE ALL ON {MARKER_TABLE}, {LEDGER_TABLE} FROM PUBLIC, {role}", None)
    execute(f"GRANT SELECT ON {MARKER_TABLE} TO {role}", None)


def insert_marker(execute, identity, facts, guard_version: str) -> None:
    execute(
        INSERT_MARKER,
        {
            "environment": identity.environment,
            "database_name": facts.database,
            "cluster_name": facts.cluster_name,
            "system_identifier": facts.system_identifier,
            "instance_id": None if identity.instance_id is None else str(identity.instance_id),
            "guard_version": guard_version,
        },
    )


def lock_down(execute, app_role: str) -> None:
    """After migrations: alembic_version and the guard tables are not writable by the app."""
    for statement in lock_down_statements(app_role):
        execute(statement, None)


class DatabaseLedger:
    """One row per consumed nonce, inserted in the same transaction as the migration.

    The caller holds the guard's transaction-level advisory lock. A unique primary key
    makes a concurrent or repeated consume return False even without the lock.
    """

    def __init__(self, execute, *, operation: str, target: str | None):
        self._execute = execute
        self._operation = operation
        self._target = target

    def consume(self, nonce_id: str, expires_at: int) -> bool:
        rows = self._execute(
            CONSUME,
            {
                "nonce": nonce_id,
                "expires_at": datetime.fromtimestamp(int(expires_at), UTC),
                "operation": self._operation,
                "target": self._target,
            },
        )
        return bool(rows)
