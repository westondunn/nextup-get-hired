"""Migration authorization through every Alembic entry point.

No database: Alembic runs for real (1.20.1, pinned by uv.lock) against ``migrations/env.py``,
but every connection is a fake that records SQL. Covers every entry point and the
database-ledger path of ``apply_in_transaction`` (mocked ledger table).
"""

import argparse
import io
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from app import guard
from app.config import load_settings
from app.guard import facts as F
from app.guard import marker as M
from app.guard.errors import GuardError, GuardRefused
from app.guard.facts import gather
from app.guard.plan import Authorization, plan

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
SYSID = "7311234567890123456"
INSTANCE = str(uuid.uuid4())
PASSWORD = "unit_test_only_password_0123456789"
SENTINEL = "SENTINEL_value_must_never_leak_8f1c"
NOW = 1_800_000_000


def environ(env="dev", role="migrator", **extra):
    prefix = {"dev": "nextup_dev", "staging": "nextup_stg", "ci": "nextup_ci", "test": "nextup_ci"}[
        env
    ]
    values = {
        "NEXTUP_ENV": env,
        "NEXTUP_INSTANCE_ID": INSTANCE,
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": prefix,
        "NEXTUP_DB_USER": f"{prefix}_{'owner' if role == 'migrator' else 'app'}",
        "NEXTUP_DB_PASSWORD": PASSWORD,
    }
    if role == "migrator":
        values.update(NEXTUP_DB_ROLE="migrator", NEXTUP_MIGRATION_KEY="m" * 48)
    values.update(extra)
    return values


def settings(env="dev", role="migrator", **extra):
    return load_settings(environ(env, role, **extra))


def rows_for(identity, *, initialized=False, revision="0029", **changes):
    db, user, cluster = identity.database.name, identity.database.user, identity.expected_cluster
    migrator = identity.role == "migrator"
    rows = {
        F.IDENTITY: [(db, cluster, user, user, 170004, "public")],
        F.ROLE_ATTRIBUTES: [(False, False, False, False, False)],
        F.CREATE_RIGHTS: [(False, migrator, False)],
        F.APPLICATION_TABLES: [(24 if initialized else 0,)],
        F.ALEMBIC_ROWS: [(revision,)] if initialized else [],
        F.MARKER_ROWS: [(identity.environment, "nextup", db, cluster, SYSID, INSTANCE, "2b.1")]
        if initialized
        else [],
        F.EXTENSION: [(True,)],
        F.CLASSIFIER: [(False,)],
        F.FOREIGN_GRANTEES: [],
        F.GUARD_TABLE_WRITES: [(migrator,)],
        F.PROVISIONING: [(F.PROVISIONED,)],
        F.PROVISIONING_PERSISTED: [("database", "nextup.provisioning=complete-v1")],
        F.SYSTEM_IDENTIFIER: [(SYSID,)],
        "present": {"alembic_version": initialized, F.MARKER_TABLE: initialized},
        "test_target": (cluster, db, "public"),
    }
    rows.update(changes)
    return rows


class Result:
    def __init__(self, rows, returns_rows=True):
        self.rows, self.returns_rows = list(rows), returns_rows

    def fetchall(self):
        return list(self.rows)

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


class Transaction:
    def __init__(self, connection):
        self.connection = connection
        connection.active = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.commit() if exc_type is None else self.rollback()
        return False

    def commit(self):
        self.connection.active = False
        self.connection.events.append("COMMIT")

    def rollback(self):
        self.connection.active = False
        self.connection.events.append("ROLLBACK")


class FakeConnection:
    """SQLAlchemy-Connection-shaped fake: answers the guard's SQL from ``rows`` and records
    every statement. The ledger table is an in-memory set that survives across fakes when
    shared (``consumed``), like a committed table would."""

    _NO_ROWS = (
        "SET ",
        "SELECT pg_advisory_xact_lock",
        "CREATE TABLE",
        "\nCREATE TABLE",
        "REVOKE",
        "GRANT",
        "INSERT INTO nextup_environment",
    )

    def __init__(self, rows, consumed=None):
        self.rows = rows
        self.consumed = set() if consumed is None else consumed
        self.active = False
        self.events: list[str] = []

    @property
    def sql(self):
        return [e for e in self.events if e not in ("COMMIT", "ROLLBACK")]

    def in_transaction(self):
        return self.active

    def begin(self):
        return Transaction(self)

    def exec_driver_sql(self, sql):
        self.events.append(sql)
        return Result([], returns_rows=False)

    def execute(self, clause, params=None):
        sql = str(clause)
        self.events.append(sql)
        params = params or {}
        if sql == F.TABLE_PRESENT:
            return Result([(self.rows["present"].get(params["table"], False),)])
        if sql == M.CONSUME:
            if params["nonce"] in self.consumed:
                return Result([])
            self.consumed.add(params["nonce"])
            return Result([(1,)])
        if sql in self.rows:
            return Result(self.rows[sql])
        if sql.startswith("SELECT current_setting('cluster_name'), current_database()"):
            return Result([self.rows["test_target"]])
        if sql.startswith(self._NO_ROWS):
            return Result([], returns_rows=False)
        raise AssertionError("unexpected SQL: " + sql[:60])


def facts_of(connection, identity):
    owner, app = guard._roles(identity)
    return gather(guard.sqlalchemy_query(connection), owner_role=owner, app_role=app)


def initialized_after(identity, revision):
    return rows_for(identity, initialized=True, revision=revision)


@pytest.fixture
def migrator(monkeypatch):
    current = settings()
    monkeypatch.setattr("app.config.get_settings", lambda: current)
    return current


@pytest.fixture(autouse=True)
def _clean_registry():
    guard._ISSUED.clear()
    yield
    guard._ISSUED.clear()


def alembic_config(**attributes):
    config = Config(str(ALEMBIC_INI))
    config.attributes.update(attributes)
    return config


def no_engine(*_args, **_kwargs):
    raise AssertionError("no connection may be attempted")


# ---------- direct Alembic ----------


class TestDirectAlembic:
    @pytest.mark.parametrize(
        "invoke",
        [
            lambda c: command.upgrade(c, "head"),
            lambda c: command.upgrade(c, "0028"),
            lambda c: command.downgrade(c, "0028"),
            lambda c: command.downgrade(c, "base"),
            lambda c: command.stamp(c, "head"),
        ],
        ids=["upgrade-head", "upgrade-rev", "downgrade", "downgrade-base", "stamp"],
    )
    def test_writes_without_authorization_are_refused_before_connecting(
        self, migrator, monkeypatch, invoke
    ):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        with pytest.raises(GuardRefused) as caught:
            invoke(alembic_config())
        assert caught.value.code == "NXG-A01"

    def test_runtime_role_cannot_write_either(self, monkeypatch):
        runtime = settings(role="runtime")
        monkeypatch.setattr("app.config.get_settings", lambda: runtime)
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(alembic_config(), "head")
        assert caught.value.code == "NXG-A01"

    def test_no_environment_variable_authorizes(self, migrator, monkeypatch):
        for name in (
            "NEXTUP_PLAN",
            "NEXTUP_TOKEN",
            "NEXTUP_MIGRATION_TOKEN",
            "NEXTUP_ALEMBIC_OFFLINE_REVIEW",
        ):
            monkeypatch.setenv(name, "1")
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(alembic_config(), "head")
        assert caught.value.code == "NXG-A01"

    def test_unknown_x_arguments_are_refused(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        config = alembic_config()
        config.cmd_opts = argparse.Namespace(x=["nextup_plan=anything"])
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(config, "head")
        assert caught.value.code == "NXG-A05"

    def test_programmatic_connection_without_authorization(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(alembic_config(connection=connection), "head")
        assert caught.value.code == "NXG-A01"
        assert connection.events == []

    def test_forged_authorization_objects_are_refused(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        forged = Authorization("0" * 64, "0" * 64, "INIT", "0029", NOW + 600)
        for value in (forged, "nxa1.x.y", object()):
            with pytest.raises(GuardRefused) as caught:
                command.upgrade(
                    alembic_config(connection=connection, nextup_authorization=value), "head"
                )
            assert caught.value.code == "NXG-A01"
        assert connection.events == []

    def test_alembic_internals_match_the_classification(self, monkeypatch):
        """Tripwire: fails loudly if Alembic changes the option names env.py relies on."""
        seen = []

        def record(context, _metadata, environ=None):
            opts = context._proxy.context_opts
            seen.append(
                ("destination_rev" in opts, guard._operation(opts), context.is_offline_mode())
            )

        monkeypatch.setattr(guard, "run_alembic", record)
        config = alembic_config()
        command.upgrade(config, "head")
        command.downgrade(config, "0028")
        command.stamp(config, "head")
        command.current(config)
        assert seen == [
            (True, "upgrade", False),
            (True, "downgrade", False),
            (True, "stamp", False),
            (False, None, False),
        ]


# ---------- fake Alembic context for read-only and offline paths ----------


class FakeContext:
    def __init__(self, opts, attributes=None, offline=False, xargs=None):
        self._proxy = argparse.Namespace(context_opts=opts)
        self.config = argparse.Namespace(attributes=attributes or {})
        self.offline, self.xargs = offline, xargs or {}
        self.configured, self.ran = [], 0

    def is_offline_mode(self):
        return self.offline

    def get_x_argument(self, as_dictionary=False):
        return dict(self.xargs)

    def configure(self, **kwargs):
        self.configured.append(kwargs)

    def begin_transaction(self):
        from contextlib import nullcontext

        return nullcontext()

    def run_migrations(self):
        self.ran += 1


def display_version(rev, context):  # same name/shape as Alembic's `current`
    return []


def upgrade(rev, context):
    return []


class TestReadOnlyAndOffline:
    def test_read_only_commands_run_in_a_read_only_transaction(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        context = FakeContext(
            {"fn": display_version, "dont_mutate": True}, {"connection": connection}
        )
        guard.run_alembic(context, None)
        assert connection.events[:2] == [
            "SET TRANSACTION READ ONLY",
            "SET LOCAL statement_timeout = '60s'",
        ]
        assert connection.events[-1] == "ROLLBACK" and context.ran == 1

    def test_read_only_refuses_inside_an_open_transaction(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        connection.active = True  # READ ONLY could no longer be the first statement
        context = FakeContext({"fn": display_version}, {"connection": connection})
        with pytest.raises(GuardRefused) as caught:
            guard.run_alembic(context, None)
        assert caught.value.code == "NXG-A01" and context.ran == 0

    def test_offline_sql_needs_the_review_flag_and_never_reads_settings(self, monkeypatch):
        monkeypatch.setattr(
            "app.config.get_settings",
            lambda: (_ for _ in ()).throw(AssertionError("settings read")),
        )
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        context = FakeContext(
            {"fn": upgrade, "destination_rev": "head", "as_sql": True}, offline=True
        )
        with pytest.raises(GuardRefused) as caught:
            guard.run_alembic(context, None, environ={})
        assert caught.value.code == "NXG-A08" and context.ran == 0
        guard.run_alembic(context, None, environ={"NEXTUP_ALEMBIC_OFFLINE_REVIEW": "1"})
        assert context.configured[0]["url"] == "postgresql+psycopg://" and context.ran == 1

    def test_unknown_alembic_internals_fail_closed(self):
        context = FakeContext({"fn": upgrade, "destination_rev": "head"})
        context._proxy = None
        with pytest.raises(GuardRefused) as caught:
            guard.run_alembic(context, None)
        assert caught.value.code == "NXG-A01"

    def test_write_with_unknown_operation_is_refused(self, migrator):
        def mystery(rev, context):
            return []

        context = FakeContext({"fn": mystery, "destination_rev": "head"})
        with pytest.raises(GuardRefused) as caught:
            guard.run_alembic(context, None)
        assert caught.value.code == "NXG-A06"


# ---------- apply_in_transaction with the database ledger ----------


def token_for(connection, current, **kwargs):
    facts = facts_of(connection, current.identity)
    connection.events.clear()
    return plan(facts, current.identity, guard._load_lineage(), now=NOW, settings=current, **kwargs)


class Recorder:
    def __init__(self, after=None, failure=None):
        self.calls, self.after, self.failure = [], after, failure

    def __call__(self, connection, authorization, decision):
        self.calls.append((authorization.operation, authorization.target, decision.mode))
        if self.failure is not None:
            raise self.failure
        if self.after is not None:
            connection.rows = self.after


class TestApply:
    def test_init_runs_once_in_order_and_replays_are_refused(self, migrator):
        identity = migrator.identity
        connection = FakeConnection(rows_for(identity))
        decision, token = token_for(connection, migrator)
        assert decision.mode == "INIT" and token.startswith("nxa1.")
        run = Recorder(after=initialized_after(identity, "0029"))
        applied = guard.apply_in_transaction(
            connection, migrator, token, operation="upgrade", target="0029", run=run, now=NOW + 5
        )
        assert applied.mode == "INIT" and run.calls == [("INIT", "0029", "INIT")]
        sql = connection.sql
        position = {
            name: next(i for i, s in enumerate(sql) if s.lstrip().startswith(name))
            for name in (
                "SET LOCAL lock_timeout",
                "SELECT pg_advisory_xact_lock",
                "CREATE TABLE nextup_environment",
                "CREATE TABLE nextup_migration_authorizations",
                M.CONSUME,
                "INSERT INTO nextup_environment",
                "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON alembic_version",
            )
        }
        assert list(position.values()) == sorted(position.values()), (
            "lock -> tables -> consume -> marker -> lock-down"
        )
        assert connection.events[-1] == "COMMIT"
        assert guard._ISSUED == {}

        # Same token again after the change: bound state differs.
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                connection,
                migrator,
                token,
                operation="upgrade",
                target="0029",
                run=run,
                now=NOW + 6,
            )
        assert caught.value.code == "NXG-A02"
        # Same token against an identical pre-state but a ledger that already holds it.
        replay = FakeConnection(rows_for(identity), consumed=connection.consumed)
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                replay, migrator, token, operation="upgrade", target="0029", run=run, now=NOW + 7
            )
        assert caught.value.code == "NXG-A03"
        assert replay.events[-1] == "ROLLBACK" and len(run.calls) == 1

    def test_expired_and_not_yet_valid_tokens(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        _, token = token_for(connection, migrator, ttl=60)
        run = Recorder()
        for now in (NOW + 60, NOW + 10_000, NOW - 120):
            with pytest.raises(GuardRefused) as caught:
                guard.apply_in_transaction(
                    connection,
                    migrator,
                    token,
                    operation="upgrade",
                    target="0029",
                    run=run,
                    now=now,
                )
            assert caught.value.code == "NXG-A04"
        assert run.calls == [] and M.CONSUME not in connection.sql

    def test_mismatched_state_request_or_key(self, migrator):
        identity = migrator.identity
        run = Recorder()
        _, token = token_for(FakeConnection(rows_for(identity)), migrator)
        cases = {
            "system identifier changed (restore into another cluster)": rows_for(
                identity, **{F.SYSTEM_IDENTIFIER: [("999",)]}
            ),
        }
        for label, rows in cases.items():
            connection = FakeConnection(rows)
            with pytest.raises(GuardRefused) as caught:
                guard.apply_in_transaction(
                    connection,
                    migrator,
                    token,
                    operation="upgrade",
                    target="0029",
                    run=run,
                    now=NOW,
                )
            assert caught.value.code == "NXG-A02", label
        with pytest.raises(GuardRefused) as caught:  # a different target than the plan
            guard.apply_in_transaction(
                FakeConnection(rows_for(identity)),
                migrator,
                token,
                operation="upgrade",
                target="0028",
                run=run,
                now=NOW,
            )
        assert caught.value.code == "NXG-A02"
        other_key = load_settings(environ(NEXTUP_MIGRATION_KEY="z" * 48))
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                FakeConnection(rows_for(identity)),
                other_key,
                token,
                operation="upgrade",
                target="0029",
                run=run,
                now=NOW,
            )
        assert caught.value.code == "NXG-A05"
        # Change a full 6-bit symbol of the MAC (never the final, partly unused one).
        tampered = token[:-2] + ("B" if token[-2] != "B" else "C") + token[-1]
        for bad in ("", "nxa1.only-two", tampered, "x" * 2000):
            with pytest.raises(GuardRefused) as caught:
                guard.apply_in_transaction(
                    FakeConnection(rows_for(identity)),
                    migrator,
                    bad,
                    operation="upgrade",
                    target="0029",
                    run=run,
                    now=NOW,
                )
            assert caught.value.code in ("NXG-A01", "NXG-A05")
        assert run.calls == []

    def test_populated_unrecognized_database_is_refused_before_any_write(self, migrator):
        identity = migrator.identity
        _, token = token_for(FakeConnection(rows_for(identity)), migrator)
        for label, changes in {
            "tables, no marker": {F.APPLICATION_TABLES: [(5,)]},
            "alembic only": {
                F.ALEMBIC_ROWS: [("0029",)],
                "present": {"alembic_version": True, F.MARKER_TABLE: False},
            },
        }.items():
            connection = FakeConnection(rows_for(identity, **changes))
            run = Recorder()
            with pytest.raises(GuardRefused) as caught:
                guard.apply_in_transaction(
                    connection,
                    migrator,
                    token,
                    operation="upgrade",
                    target="0029",
                    run=run,
                    now=NOW,
                )
            assert caught.value.code == "NXG-M01", label
            assert not any(
                s.lstrip().startswith(("CREATE", "INSERT", "REVOKE", "GRANT"))
                for s in connection.sql
            )
            assert run.calls == [] and connection.events[-1] == "ROLLBACK"

    def test_noop_and_runtime_role_are_refused(self, migrator):
        identity = migrator.identity
        at_head = FakeConnection(initialized_after(identity, "0029"))
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                at_head,
                migrator,
                "nxa1.a.b",
                operation="upgrade",
                target="0029",
                run=Recorder(),
                now=NOW,
            )
        assert caught.value.code == "NXG-A02"
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                at_head,
                settings(role="runtime"),
                "nxa1.a.b",
                operation="upgrade",
                target="0029",
                run=Recorder(),
                now=NOW,
            )
        assert caught.value.code == "NXG-A01"

    def test_failed_migration_rolls_back_and_hides_driver_text(self, migrator):
        identity = migrator.identity
        connection = FakeConnection(rows_for(identity))
        _, token = token_for(connection, migrator)
        failure = OperationalError(f"INSERT {SENTINEL}", {"v": SENTINEL}, Exception(SENTINEL))
        with pytest.raises(GuardRefused) as caught:
            guard.apply_in_transaction(
                connection,
                migrator,
                token,
                operation="upgrade",
                target="0029",
                run=Recorder(failure=failure),
                now=NOW,
            )
        assert caught.value.code == "NXG-A09" and SENTINEL not in str(caught.value) + repr(
            caught.value
        )
        assert caught.value.__suppress_context__ and caught.value.__cause__ is None
        assert connection.events[-1] == "ROLLBACK" and guard._ISSUED == {}

    def test_post_checks_refuse_incomplete_or_foreign_results(self, migrator):
        identity = migrator.identity
        for label, after, code in (
            ("revision not reached", initialized_after(identity, "0028"), "NXG-L03"),
            (
                "foreign grantee",
                rows_for(identity, initialized=True, **{F.FOREIGN_GRANTEES: [("n8n",)]}),
                "NXG-R02",
            ),
        ):
            connection = FakeConnection(rows_for(identity))
            _, token = token_for(connection, migrator)
            with pytest.raises(GuardRefused) as caught:
                guard.apply_in_transaction(
                    connection,
                    migrator,
                    token,
                    operation="upgrade",
                    target="0029",
                    run=Recorder(after=after),
                    now=NOW,
                )
            assert caught.value.code == code, label
            assert connection.events[-1] == "ROLLBACK"


# ---------- authorization handed to env.py (programmatic) ----------


class TestProgrammaticBinding:
    def apply_with(self, migrator, inner):
        identity = migrator.identity
        connection = FakeConnection(rows_for(identity))
        _, token = token_for(connection, migrator)

        def run(conn, authorization, decision):
            inner(conn, authorization)
            conn.rows = initialized_after(identity, decision.target)

        guard.apply_in_transaction(
            connection, migrator, token, operation="upgrade", target="0029", run=run, now=NOW
        )
        return connection

    def test_authorization_is_single_use_and_bound(self, migrator):
        outcomes = {}

        def inner(conn, authorization):
            def attempt(label, opts, connection=conn):
                context = FakeContext(
                    opts, {"connection": connection, "nextup_authorization": authorization}
                )
                try:
                    guard.run_alembic(context, None)
                    outcomes[label] = "ran" if context.ran == 1 else "no-run"
                except GuardError as exc:
                    outcomes[label] = exc.code

            def downgrade(rev, context):
                return []

            attempt(
                "other connection", {"fn": upgrade, "destination_rev": "head"}, FakeConnection({})
            )
            attempt("wrong operation", {"fn": downgrade, "destination_rev": "0029"})
            attempt("first use", {"fn": upgrade, "destination_rev": "head"})
            attempt("second use", {"fn": upgrade, "destination_rev": "head"})

        self.apply_with(migrator, inner)
        assert outcomes == {
            "other connection": "NXG-A02",
            "wrong operation": "NXG-A02",  # consumes the in-process entry: fail closed
            "first use": "NXG-A03",
            "second use": "NXG-A03",
        }

    def test_correct_use_runs_once_and_target_must_match(self, migrator):
        outcomes = []

        def inner(conn, authorization):
            for destination in ("0028", "head"):
                context = FakeContext(
                    {"fn": upgrade, "destination_rev": destination},
                    {"connection": conn, "nextup_authorization": authorization},
                )
                try:
                    guard.run_alembic(context, None)
                    outcomes.append((destination, context.ran))
                except GuardError as exc:
                    outcomes.append((destination, exc.code))

        self.apply_with(migrator, inner)
        assert outcomes == [("0028", "NXG-A02"), ("head", "NXG-A03")]

    def test_matching_first_use_runs(self, migrator):
        ran = []

        def inner(conn, authorization):
            context = FakeContext(
                {"fn": upgrade, "destination_rev": "head"},
                {"connection": conn, "nextup_authorization": authorization},
            )
            guard.run_alembic(context, None)
            ran.append(context.ran)
            assert context.configured[0]["connection"] is conn

        self.apply_with(migrator, inner)
        assert ran == [1]
        assert guard._ISSUED == {}  # nothing remains usable after apply returns


# ---------- one authorization policy for every entry point ----------


class FakeEngine:
    """Engine-shaped fake: each connect() yields a FakeConnection over shared rows/ledger."""

    def __init__(self, rows):
        self.rows, self.consumed, self.connections = rows, set(), []

    def connect(self):
        from contextlib import contextmanager

        @contextmanager
        def connection():
            conn = FakeConnection(self.rows, consumed=self.consumed)
            self.connections.append(conn)
            yield conn
            self.rows = conn.rows  # an authorized change persists for later connections

        return connection()


class TestSingleAuthorizationPolicy:
    def test_no_alternative_authorization_remains(self):
        source = (
            Path(guard.__file__).read_text()
            + (Path(guard.__file__).parent / "__main__.py").read_text()
        )
        for name in (
            "TestAuthorization",
            "test_authorization",
            "nextup_test",
            "_verify_test_target",
            "single_use",
            "NEXTUP_TEST_DB_PASSWORD_FILE",
        ):
            assert name not in source, name
        assert not hasattr(guard, "test_authorization") and not hasattr(guard, "TestAuthorization")
        env_py = (ALEMBIC_INI.parent / "migrations/env.py").read_text()
        assert "guard.run_alembic(context, Base.metadata)" in env_py and "nextup_test" not in env_py

    def test_former_test_x_argument_is_refused_before_connecting(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        for xargs in (["nextup_test=1"], ["nextup_test=1", "nextup_token=nxa1.a.b"]):
            config = alembic_config()
            config.cmd_opts = argparse.Namespace(x=xargs)
            with pytest.raises(GuardRefused) as caught:
                command.upgrade(config, "head")
            assert caught.value.code == "NXG-A05"

    def test_read_only_commands_need_and_consume_no_authorization(self, migrator):
        connection = FakeConnection(rows_for(migrator.identity))
        stray = Authorization("0" * 64, "0" * 64, "INIT", "0029", NOW + 600)
        guard._register(stray, connection)
        context = FakeContext(
            {"fn": display_version}, {"connection": connection, "nextup_authorization": stray}
        )
        guard.run_alembic(context, None)
        assert connection.events[0] == "SET TRANSACTION READ ONLY" and context.ran == 1
        assert guard._ISSUED[id(stray)].used is False

    def test_cli_and_programmatic_paths_call_the_same_plan_and_apply(self, migrator, monkeypatch):
        from app.guard import __main__ as cli

        calls = []
        engine = argparse.Namespace(dispose=lambda: None)
        monkeypatch.setattr(guard, "migration_engine", lambda settings, **_: engine)
        monkeypatch.setattr(
            guard,
            "plan_migration",
            lambda engine, settings, **kw: (
                calls.append(("plan", engine, kw)) or (guard_decision("INIT"), "nxa1.p.m")
            ),
        )
        monkeypatch.setattr(
            guard,
            "apply_migration",
            lambda engine, settings, token, **kw: (
                calls.append(("apply", engine, token, kw)) or guard_decision("INIT")
            ),
        )
        guard.migrate_programmatically(engine, migrator)
        programmatic = list(calls)
        calls.clear()
        monkeypatch.setattr("sys.stdin", io.StringIO("nxa1.p.m\n"))  # stdin handoff
        assert cli.main(["plan"]) == 0 and cli.main(["apply"]) == 0
        assert [c[0] for c in programmatic] == ["plan", "apply"] == [c[0] for c in calls]
        assert programmatic[1][2] == calls[1][2] == "nxa1.p.m"
        assert programmatic[0][1] is calls[0][1] is engine  # same engine factory and functions

    def test_programmatic_migration_is_planned_applied_once_then_noop(self, migrator, monkeypatch):
        identity = migrator.identity
        engine = FakeEngine(rows_for(identity))
        ran = []

        def alembic_step(connection, authorization, decision):
            ran.append((authorization.operation, decision.target))
            connection.rows = initialized_after(identity, decision.target)

        monkeypatch.setattr(guard, "run_alembic_command", alembic_step)
        first = guard.migrate_programmatically(engine, migrator)
        assert first.mode == "INIT" and ran == [("INIT", "0029")]
        assert len(engine.consumed) == 1
        sql = engine.connections[-1].sql
        assert "SELECT pg_advisory_xact_lock(:key)" in sql and M.CONSUME in sql
        second = guard.migrate_programmatically(engine, migrator)
        assert second.mode == "NOOP" and len(ran) == 1 and len(engine.consumed) == 1
        assert guard._ISSUED == {}

    def test_programmatic_path_has_no_extra_permissions(self, migrator, monkeypatch):
        monkeypatch.setattr(
            guard, "run_alembic_command", lambda *a: pytest.fail("must not migrate")
        )
        runtime = settings(role="runtime")
        engine = FakeEngine(rows_for(runtime.identity))
        for call in (
            lambda: guard.migrate_programmatically(engine, runtime),
            lambda: guard.plan_migration(engine, runtime),
            lambda: guard.apply_migration(engine, runtime, "nxa1.a.b"),
        ):
            with pytest.raises(GuardRefused) as caught:
                call()
            assert caught.value.code == "NXG-I04"
        assert engine.connections == []  # refused before any connection
        at_head = FakeEngine(initialized_after(migrator.identity, "0029"))
        with pytest.raises(GuardRefused) as caught:  # downgrade outside ci/test: same policy as CLI
            guard.migrate_programmatically(at_head, migrator, operation="downgrade", target="0028")
        assert caught.value.code == "NXG-A06"
        with pytest.raises(GuardRefused) as caught:
            guard.apply_migration(at_head, migrator, "nxa1.a.b", operation="downgrade")
        assert caught.value.code == "NXG-A06"
        with pytest.raises(GuardRefused) as caught:  # a token from elsewhere is still verified
            guard.apply_migration(FakeEngine(rows_for(migrator.identity)), migrator, "nxa1.a.b")
        assert caught.value.code == "NXG-A05"

    def test_alembic_compare_ignores_only_the_guard_tables(self):
        assert guard.GUARD_TABLES == {F.MARKER_TABLE, F.LEDGER_TABLE}
        for name in guard.GUARD_TABLES:
            assert guard._include_name(name, "table", {}) is False
        for name, kind in (
            ("jobs", "table"),
            ("alembic_version", "table"),
            ("nextup_environment", "column"),
        ):
            assert guard._include_name(name, kind, {}) is True
        context = FakeContext({"fn": display_version}, {"connection": FakeConnection({})})
        guard._configure_and_run(context, context.config.attributes["connection"], None)
        assert context.configured[0]["include_name"] is guard._include_name


def guard_decision(mode):
    from app.guard.policy import Decision

    return Decision(mode, None, "0029", ("0001",))
