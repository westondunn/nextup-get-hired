"""Entry-point wiring of the database guard.

No database, no Docker, no network. Database access goes through fakes that answer the
guard's catalog queries; subprocesses are limited to `bash` on the first-boot script with
a stub `psql` that only records whether it was called.
"""

import io
import logging
import os
import re
import stat
import subprocess
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from celery.signals import beat_init, worker_init
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from test_env_authorization import INSTANCE, PASSWORD, SENTINEL, SYSID, environ, rows_for, settings

from app import guard
from app.config import load_settings
from app.guard import __main__ as cli
from app.guard import facts as F
from app.guard.errors import ConfigError, GuardRefused

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
INIT_SCRIPT = BACKEND / "docker/initdb/10-nextup-roles.sh"


# ---------- fake DBAPI connection (psycopg-shaped) for the runtime hook ----------


class FakeCursor:
    def __init__(self, connection):
        self.connection, self.description, self._rows = connection, None, []

    def execute(self, sql, params=None):
        self.connection.sql.append(sql)
        if self.connection.fail_on and self.connection.fail_on in sql:
            raise self.connection.failure
        key = self.connection.lookup.get(sql)
        if key == F.TABLE_PRESENT:
            rows = [(self.connection.rows["present"].get(params["table"], False),)]
        elif key is not None:
            rows = self.connection.rows[key]
        elif sql.startswith("SET "):
            rows = None
        else:
            raise AssertionError("unexpected SQL: " + sql[:60])
        self.description = None if rows is None else [("c",)]
        self._rows = rows or []

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeDBAPI:
    def __init__(self, rows, fail_on=None, failure=None):
        self.rows, self.sql, self.events = rows, [], []
        self.fail_on, self.failure, self.closed = fail_on, failure, False
        self.lookup = {guard._BIND.sub(r"%(\1)s", sql): sql for sql in F.STATEMENTS}

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.events.append("ROLLBACK")

    def close(self):
        self.closed = True


def runtime(env="dev", **extra):
    return settings(env=env, role="runtime", **extra)


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except GuardRefused as exc:
        return exc.code
    return "PROCEED"


# ---------- runtime check (acceptance 2) ----------


class TestRuntimeCheck:
    def test_proceeds_only_for_the_exact_identity(self):
        current = runtime()
        identity = current.identity
        good = rows_for(identity, initialized=True)
        connection = FakeDBAPI(good)
        assert guard.check_runtime(connection, current).mode == "PROCEED-RUNTIME"
        assert connection.sql[:3] == [
            "SET TRANSACTION READ ONLY",
            "SET LOCAL statement_timeout = '5s'",
            "SET LOCAL lock_timeout = '2s'",
        ]
        assert connection.events == ["ROLLBACK", "ROLLBACK"]
        assert all(s.startswith(("SET ", "SELECT")) for s in connection.sql)

        db, user, cluster = (
            identity.database.name,
            identity.database.user,
            identity.expected_cluster,
        )
        owner = "nextup_dev_owner"
        cases = {
            "other database": (
                {F.IDENTITY: [("otherapp", cluster, user, user, 170004, "public")]},
                "NXG-I02",
            ),
            "other cluster": (
                {F.IDENTITY: [(db, "main", user, user, 170004, "public")]},
                "NXG-I03",
            ),
            "empty cluster_name": (
                {F.IDENTITY: [(db, "", user, user, 170004, "public")]},
                "NXG-I03",
            ),
            "owner credential": (
                {F.IDENTITY: [(db, cluster, owner, owner, 170004, "public")]},
                "NXG-I04",
            ),
            "SET ROLE": (
                {F.IDENTITY: [(db, cluster, user, "nextup_dev_admin", 170004, "public")]},
                "NXG-I04",
            ),
            "superuser": ({F.ROLE_ATTRIBUTES: [(True, False, False, False, False)]}, "NXG-I05"),
            "member of owner": ({F.CREATE_RIGHTS: [(False, False, True)]}, "NXG-I05"),
            "CREATE on schema": ({F.CREATE_RIGHTS: [(False, True, False)]}, "NXG-I05"),
            "app can write alembic_version": ({F.GUARD_TABLE_WRITES: [(True,)]}, "NXG-I05"),
            "no guard-table row": ({F.GUARD_TABLE_WRITES: []}, "NXG-I05"),
            "no system identifier": ({F.SYSTEM_IDENTIFIER: []}, "NXG-I07"),
            "old server": ({F.IDENTITY: [(db, cluster, user, user, 160001, "public")]}, "NXG-I06"),
            "marker from staging": (
                {F.MARKER_ROWS: [("staging", "nextup", db, cluster, SYSID, INSTANCE, "2b.1")]},
                "NXG-M02",
            ),
            "restored into another cluster": ({F.SYSTEM_IDENTIFIER: [("111",)]}, "NXG-M03"),
            "other instance": (
                {
                    F.MARKER_ROWS: [
                        (
                            "dev",
                            "nextup",
                            db,
                            cluster,
                            SYSID,
                            "00000000-0000-4000-8000-000000000000",
                            "2b.1",
                        )
                    ]
                },
                "NXG-M04",
            ),
            "behind head": ({F.ALEMBIC_ROWS: [("0028",)]}, "NXG-L03"),
            "unknown revision": ({F.ALEMBIC_ROWS: [("prv_0030",)]}, "NXG-L01"),
            "n8n role at 0029": ({F.CLASSIFIER: [(True,)]}, "NXG-R01"),
            "foreign grantee": ({F.FOREIGN_GRANTEES: [("PUBLIC",)]}, "NXG-R02"),
            "provisioning never completed": ({F.PROVISIONING: [(None,)]}, "NXG-I10"),
            "provisioning setting absent": ({F.PROVISIONING: []}, "NXG-I10"),
            "unknown provisioning version": ({F.PROVISIONING: [("complete-v0",)]}, "NXG-I10"),
            # The session value alone (SET, set_config(), PGOPTIONS) proves nothing.
            "session value, nothing stored": ({F.PROVISIONING_PERSISTED: []}, "NXG-I10"),
            "stored for one role only": (
                {
                    F.PROVISIONING_PERSISTED: [
                        ("role-in-database", "nextup.provisioning=complete-v1")
                    ]
                },
                "NXG-I10",
            ),
            "stored cluster-wide only": (
                {F.PROVISIONING_PERSISTED: [("cluster", "nextup.provisioning=complete-v1")]},
                "NXG-I10",
            ),
            "wrong stored value": (
                {F.PROVISIONING_PERSISTED: [("database", "nextup.provisioning=complete-v0")]},
                "NXG-I10",
            ),
            "duplicate stored entries": (
                {
                    F.PROVISIONING_PERSISTED: [
                        ("database", "nextup.provisioning=complete-v1"),
                        ("database", "nextup.provisioning=complete-v1"),
                    ]
                },
                "NXG-I10",
            ),
            "stored correctly but the session disagrees": (
                {F.PROVISIONING: [("partial",)]},
                "NXG-I10",
            ),
        }
        for label, (changes, code) in cases.items():
            assert code_of(guard.check_runtime, FakeDBAPI({**good, **changes}), current) == code, (
                label
            )
        populated = rows_for(identity, **{F.APPLICATION_TABLES: [(5,)]})
        assert code_of(guard.check_runtime, FakeDBAPI(populated), current) == "NXG-M01"
        assert code_of(guard.check_runtime, FakeDBAPI(rows_for(identity)), current) == "NXG-M05"

    def test_migrator_identity_is_refused_at_runtime(self):
        current = settings()  # migrator
        rows = rows_for(current.identity, initialized=True)
        assert code_of(guard.check_runtime, FakeDBAPI(rows), current) == "NXG-I04"

    def test_fact_errors_are_classified_without_their_text(self):
        current = runtime()
        rows = rows_for(current.identity, initialized=True)

        class DriverError(Exception):
            sqlstate = "42501"

        connection = FakeDBAPI(
            rows, fail_on="FROM nextup_environment", failure=DriverError(f"denied {SENTINEL}")
        )
        with pytest.raises(GuardRefused) as caught:
            guard.check_runtime(connection, current)
        assert caught.value.code == "NXG-I09"
        rendered = "".join(traceback.format_exception(caught.value))
        assert SENTINEL not in rendered and connection.events[-1] == "ROLLBACK"

    def test_engine_hook_refuses_and_closes_the_connection(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            "sqlalchemy.event.listen", lambda target, name, fn: captured.append((target, name, fn))
        )
        guard.install_runtime_guard("engine")
        ((target, name, hook),) = captured
        assert (target, name) == ("engine", "first_connect")
        bad = rows_for(runtime().identity, initialized=True, **{F.ALEMBIC_ROWS: [("0028",)]})
        connection = FakeDBAPI(bad)
        monkeypatch.setattr("app.config.get_settings", runtime)
        with pytest.raises(GuardRefused) as caught:
            hook(connection, None)
        assert caught.value.code == "NXG-L03" and connection.closed

    def test_runtime_engine_installs_the_hook(self, monkeypatch):
        from app import db

        installed = []
        monkeypatch.setattr("app.config.get_settings", runtime)
        monkeypatch.setattr("app.db.get_settings", runtime)
        monkeypatch.setattr(guard, "install_runtime_guard", installed.append)
        db.get_engine.cache_clear()
        try:
            engine = db.get_engine()
            assert installed == [engine]
            assert engine.url.render_as_string(hide_password=True).count("***") == 1
        finally:
            db.get_engine.cache_clear()


# ---------- service entry points (acceptance 2 and 8) ----------


def refusing(code="NXG-I02"):
    def check():
        raise GuardRefused(code, env="dev")

    return check


class TestServices:
    def test_api_does_not_serve_when_the_guard_refuses(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(guard, "check_service_startup", refusing())
        with pytest.raises(GuardRefused) as caught:
            with TestClient(app):
                pass
        assert caught.value.code == "NXG-I02"

    def test_api_serves_after_proceed(self, monkeypatch):
        from app.main import app

        calls = []
        monkeypatch.setattr(guard, "check_service_startup", lambda: calls.append(1))
        with TestClient(app) as client:
            assert client.get("/api/live").status_code == 200
        assert calls == [1]

    @pytest.mark.parametrize("signal", [worker_init, beat_init], ids=["worker", "scheduler"])
    def test_worker_and_scheduler_exit_before_work(self, monkeypatch, signal):
        import app.celery_app  # noqa: F401 - connects the handlers

        assert any(receiver is guard.celery_startup_check for _, receiver in signal.receivers)
        monkeypatch.setattr(guard, "check_service_startup", refusing("NXG-M02"))
        stderr = io.StringIO()
        with redirect_stderr(stderr), pytest.raises(SystemExit) as caught:
            signal.send(sender=None)
        assert caught.value.code == 3
        assert stderr.getvalue().startswith("nextup-guard: REFUSE NXG-M02")

    def test_connection_failures_map_to_codes_without_text(self, monkeypatch):
        class Orig(Exception):
            def __init__(self, text, sqlstate):
                super().__init__(text)
                self.sqlstate = sqlstate

        for sqlstate, code in ((None, "NXG-C05"), ("28P01", "NXG-C06"), ("3D000", "NXG-I02")):
            failure = OperationalError(
                f"connect to {SENTINEL}", {}, Orig(f"host {SENTINEL}", sqlstate)
            )

            class Engine:
                def connect(self, failure=failure):
                    raise failure

            monkeypatch.setattr("app.db.get_engine", lambda: Engine())
            with pytest.raises(GuardRefused) as caught:
                guard.check_service_startup()
            assert caught.value.code == code
            assert SENTINEL not in "".join(traceback.format_exception(caught.value))


# ---------- guard command line ----------


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCommandLine:
    def test_exec_allows_only_service_commands_and_checks_first(self, monkeypatch):
        executed, checked = [], []
        monkeypatch.setattr(os, "execvp", lambda path, argv: executed.append(argv))
        monkeypatch.setattr(guard, "check_service_startup", lambda: checked.append(1))
        monkeypatch.setattr(
            "app.db.get_engine", lambda: type("E", (), {"dispose": lambda self: None})()
        )
        for argv in (
            ["alembic", "upgrade", "head"],
            ["python", "-m", "alembic", "upgrade", "head"],
            ["python", "-c", "print(1)"],
            ["sh", "-c", "uvicorn x"],
            ["pytest"],
            [],
            ["python", "-m", "debugpy", "--listen", "0.0.0.0:5690", "-m", "alembic"],
        ):
            code, _, err = run_cli(["exec", "--", *argv])
            assert code == 3 and "NXG-X01" in err, argv
        assert executed == [] and checked == []
        allowed = (
            ["uvicorn", "app.main:app"],
            ["celery", "-A", "app.celery_app:celery_app", "worker"],
            [
                "python",
                "-m",
                "debugpy",
                "--listen",
                "0.0.0.0:5690",
                "-m",
                "uvicorn",
                "app.main:app",
            ],
        )
        for argv in allowed:
            _, out, _ = run_cli(["exec", "--", *argv])  # execvp is mocked, so it returns here
            assert out == "nextup-guard: PROCEED-RUNTIME\n"
        assert executed == list(allowed) and len(checked) == 3

    def test_exec_never_starts_the_service_on_refusal(self, monkeypatch):
        executed = []
        monkeypatch.setattr(os, "execvp", lambda path, argv: executed.append(argv))
        monkeypatch.setattr(guard, "check_service_startup", refusing("NXG-I04"))
        code, out, err = run_cli(["exec", "--", "uvicorn", "app.main:app"])
        assert (code, executed, out) == (3, [], "")
        assert err.strip() == (
            "nextup-guard: REFUSE NXG-I04 connected role is not the role this process requires "
            "(env=dev)"
        )

    def test_exit_codes(self, monkeypatch):
        monkeypatch.setattr(guard, "check_service_startup", lambda: None)
        assert run_cli(["check"])[0] == 0
        monkeypatch.setattr(guard, "check_service_startup", refusing())
        assert run_cli(["check"])[0] == 3

        def config_error():
            raise ConfigError("NXG-C01")

        monkeypatch.setattr(guard, "check_service_startup", config_error)
        assert run_cli(["check"])[0] == 4

        def unreachable():
            raise OperationalError(SENTINEL, {}, Exception(SENTINEL))

        monkeypatch.setattr(guard, "check_service_startup", unreachable)
        code, out, err = run_cli(["check"])
        assert code == 5 and SENTINEL not in out + err

        def unexpected():
            raise RuntimeError(SENTINEL)

        monkeypatch.setattr(guard, "check_service_startup", unexpected)
        code, out, err = run_cli(["check"])
        assert code == 3 and SENTINEL not in out + err and "RuntimeError" in err
        assert run_cli(["no-such-action"])[0] == 4

    def test_plan_and_apply_require_the_migrator_role(self, monkeypatch):
        current = runtime()
        monkeypatch.setattr("app.config.get_settings", lambda: current)
        monkeypatch.setattr(
            guard, "migration_engine", lambda *_: (_ for _ in ()).throw(AssertionError("connected"))
        )
        for argv in (["plan"], ["plan-apply"], ["apply"]):  # role refused before stdin is read
            code, _, err = run_cli(argv)
            assert code == 3 and "NXG-I04" in err

    def test_downgrade_apply_needs_an_explicit_target(self, monkeypatch):
        current = settings()
        monkeypatch.setattr("app.config.get_settings", lambda: current)
        monkeypatch.setattr(
            guard, "migration_engine", lambda *_: (_ for _ in ()).throw(AssertionError("connected"))
        )
        code, _, err = run_cli(["apply", "--operation", "downgrade"])
        assert code == 3 and "NXG-A06" in err


# ---------- secrets never appear ----------


class TestNoSecretsInOutput:
    def test_sentinel_secret_never_appears(self, monkeypatch, caplog):
        root = os.path.realpath(tempfile.mkdtemp())
        try:
            secret = os.path.join(root, "db_app_password")
            with open(secret, "w") as handle:
                handle.write(SENTINEL + "\n")
            os.chmod(secret, 0o600)
            values = environ(role="runtime", NEXTUP_SECRETS_DIR=root, NEXTUP_DB_PASSWORD=None)
            values = {k: v for k, v in values.items() if v is not None}
            values["NEXTUP_DB_PASSWORD_FILE"] = secret
            current = load_settings(values)
            assert current.identity.database.password.get_secret_value() == SENTINEL
            outputs = [
                repr(current),
                str(current),
                repr(current.identity),
                repr(current.identity.database),
                current.database_url.render_as_string(hide_password=True),
            ]
            caplog.set_level(logging.DEBUG)
            bad = rows_for(current.identity, initialized=True, **{F.ALEMBIC_ROWS: [("0028",)]})
            for attempt in (
                lambda: guard.check_runtime(FakeDBAPI(bad), current),
                lambda: load_settings({**values, "NEXTUP_UNKNOWN_KEY": SENTINEL}),
                lambda: load_settings({**values, "NEXTUP_DB_HOST": SENTINEL}),
                lambda: load_settings({**values, "NEXTUP_DB_PORT": SENTINEL}),
                lambda: load_settings({**values, "DATABASE_URL": f"postgresql://u:{SENTINEL}@h/d"}),
                lambda: load_settings({**values, "NEXTUP_DB_PASSWORD": SENTINEL}),
            ):
                with pytest.raises((GuardRefused, ConfigError)) as caught:
                    attempt()
                outputs += [
                    str(caught.value),
                    repr(caught.value),
                    "".join(traceback.format_exception(caught.value)),
                ]
            monkeypatch.setattr("app.config.get_settings", lambda: current)
            monkeypatch.setattr(
                guard, "check_service_startup", lambda: guard.check_runtime(FakeDBAPI(bad), current)
            )
            outputs += list(run_cli(["check"])[1:])
            outputs += [record.getMessage() for record in caplog.records]
            assert all(SENTINEL not in text for text in outputs)
            assert PASSWORD not in "".join(outputs)
        finally:
            for name in os.listdir(root):
                os.unlink(os.path.join(root, name))
            os.rmdir(root)


# ---------- no startup path migrates (acceptance 8) ----------


class TestNoSilentMigration:
    def test_only_the_guard_cli_invokes_alembic_commands(self):
        offenders = []
        for path in sorted((BACKEND / "app").rglob("*.py")):
            text = path.read_text()
            if re.search(
                r"\bcommand\.(upgrade|downgrade|stamp)\(|from alembic import command", text
            ):
                offenders.append(path.relative_to(BACKEND).as_posix())
        assert offenders == ["app/guard/__init__.py"]
        # ... and only inside run_alembic_command, which only apply_migration passes on.
        source = (BACKEND / "app/guard/__init__.py").read_text()
        body = source[source.index("def run_alembic_command") : source.index("def plan_migration")]
        assert (
            len(re.findall(r"\bcommand\.(upgrade|downgrade|stamp)\(", source))
            == len(re.findall(r"\bcommand\.(upgrade|downgrade|stamp)\(", body))
            == 2
        )
        assert re.findall(r"run=run_alembic_command", source) == ["run=run_alembic_command"]
        assert "run_alembic_command" not in (BACKEND / "app/guard/__main__.py").read_text()
        for name in ("main.py", "db.py", "celery_app.py", "health.py"):
            assert "alembic" not in (BACKEND / "app" / name).read_text()

    def test_image_entrypoint_is_the_guard(self):
        text = (BACKEND / "Dockerfile").read_text()
        assert 'ENTRYPOINT ["python", "-m", "app.guard", "exec", "--"]' in text
        assert 'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in text
        assert "alembic" not in text

    def test_startup_check_is_read_only(self):
        source = Path(guard.__file__).read_text()
        start = source.index("def check_runtime")
        body = source[start : source.index("def install_runtime_guard")]
        assert "apply" not in body and "marker." not in body


# ---------- first-boot script ----------


class TestInitScript:
    def run(self, env):
        with tempfile.TemporaryDirectory() as stub:
            log = Path(stub) / "psql.log"
            psql = Path(stub) / "psql"
            psql.write_text(f"#!/bin/sh\necho called >> {log}\nexit 0\n")
            psql.chmod(0o700)
            result = subprocess.run(
                ["/bin/bash", str(INIT_SCRIPT)],
                env={"PATH": f"{stub}:/usr/bin:/bin", **env},
                capture_output=True,
                text=True,
                timeout=20,
            )
            return result, log.exists()

    def test_refuses_foreign_bootstrap_identities_before_psql(self):
        for env in (
            {},
            {"POSTGRES_USER": "postgres", "POSTGRES_DB": "postgres"},
            {"POSTGRES_USER": "nextup", "POSTGRES_DB": "postgres"},
            {"POSTGRES_USER": "otherapp_admin", "POSTGRES_DB": "postgres"},
            {"POSTGRES_USER": "nextup_dev_admin", "POSTGRES_DB": "nextup_dev"},
            {"POSTGRES_USER": "nextup_dev_admin", "POSTGRES_DB": "postgres"},  # no password files
        ):
            result, called = self.run(env)
            assert result.returncode == 1 and not called, env
            assert result.stderr.startswith("nextup-initdb: refusing:")
            assert SENTINEL not in result.stdout + result.stderr

    def test_static_contract(self):
        text = INIT_SCRIPT.read_text()
        assert INIT_SCRIPT.stat().st_mode & stat.S_IXUSR
        subprocess.run(["/bin/bash", "-n", str(INIT_SCRIPT)], check=True)
        assert "set +x" in text and "<<'SQL'" in text  # no tracing; no shell expansion in SQL
        assert "log_min_error_statement = 'panic'" in text and "log_statement = 'none'" in text
        for role_line in (
            "NOSUPERUSER NOCREATEROLE :createdb NOBYPASSRLS NOREPLICATION",
            "NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS NOREPLICATION NOINHERIT",
        ):
            assert role_line in text
        assert (
            "REVOKE ALL ON DATABASE" in text and "REVOKE ALL ON SCHEMA public FROM PUBLIC" in text
        )
        assert "GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system()" in text
        assert "SUPERUSER " not in text.replace("NOSUPERUSER", "")
        assert "CREATEROLE" not in text.replace("NOCREATEROLE", "")
        # Passwords only via psql backticks from the tmpfs copies; never on a command line.
        assert re.findall(r"\\set (\w+) `cat (\S+)`", text) == [
            ("owner_pw", "/run/nextup-initdb/db_owner_password"),
            ("app_pw", "/run/nextup-initdb/db_app_password"),
        ]
        assert "PASSWORD '" not in text and '-c "' not in text
        statements = sql_statements(text)
        # No marker, no schema objects: the first authorized `guard apply` (INIT) does that.
        assert "nextup_environment" not in statements and "alembic" not in statements
        assert "CREATE TABLE" not in statements

    def test_provisioning_is_idempotent_non_destructive_and_completes_last(self):
        """Re-runnable as the operator repair step; completion is explicit and last."""
        statements = [s for s in sql_statements(INIT_SCRIPT.read_text()).split(";") if s.strip()]
        assert (
            statements[-1].strip()
            == "ALTER DATABASE :\"db\" SET nextup.provisioning = 'complete-v1'"
        )
        body = "\n".join(statements)
        reset = body.index("RESET nextup.provisioning")
        assert reset < body.index("CREATE ROLE") < body.index("CREATE DATABASE")
        # Roles and the database are created only if missing; nothing is ever dropped.
        assert "WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner') \\gexec" in body
        assert "WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \\gexec" in body
        assert not re.search(r"\bDROP\b|\bTRUNCATE\b|--clean|pg_terminate", body)
        assert "foreign owner" in body  # an existing database owned by anyone else is refused
        # CI only: template1 gets the extension and identifier grant for disposable databases.
        ci_block = body[body.index("\\if :ci") : body.index("\\endif")]
        assert "\\connect template1" in ci_block and "pg_control_system" in ci_block

    def test_parameter_privilege_is_ci_only_and_exact(self):
        """One cluster-wide privilege, for one parameter and one role, granted
        only in the disposable CI instance. Any broadening must fail here."""
        text = INIT_SCRIPT.read_text()
        body = sql_statements(text)
        ci_block = body[body.index("\\if :ci") : body.index("\\endif")]
        outside = body.replace(ci_block, "")
        grant = 'GRANT SET ON PARAMETER nextup.provisioning TO "nextup_ci_owner"'
        parameter_statements = [
            s.strip() for s in body.split(";") if re.search(r"\bPARAMETER\b", s, re.I)
        ]
        assert [s.splitlines()[-1].strip() for s in parameter_statements] == [grant]
        assert grant in ci_block and "PARAMETER" not in outside.upper()
        # the CI branch exists exactly once and is entered only for the nextup_ci bootstrap user
        assert body.count("\\if :ci") == 1 and body.count("\\endif") == 1
        assert re.search(
            r'createdb=NOCREATEDB\nci=0\nif \[ "\$prefix" = nextup_ci \]; then\n'
            r"  createdb=CREATEDB\n  ci=1\nfi",
            text,
        )
        assert text.count("ci=1") == 1 and '-v ci="$ci"' in text
        # nothing broader: no PUBLIC, app, dev or staging recipient, no option to pass it on,
        # no ALTER SYSTEM, no role-administration attribute
        statement = parameter_statements[0]
        for forbidden in (
            "PUBLIC",
            ':"app"',
            "_app",
            "nextup_dev",
            "nextup_stg",
            "ALL",
            "GRANT OPTION",
            ",",
        ):
            assert forbidden not in statement.splitlines()[-1], forbidden
        assert not re.search(r"ALTER\s+SYSTEM|\bCREATEROLE\b(?<!NOCREATEROLE)", body)
        assert not re.search(r"(?<!NO)SUPERUSER|(?<!NO)BYPASSRLS|(?<!NO)REPLICATION", body)
        # the role attributes of both roles are untouched by the fix
        assert (
            "NOSUPERUSER NOCREATEROLE :createdb NOBYPASSRLS NOREPLICATION INHERIT" in body
            and "NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS NOREPLICATION NOINHERIT" in body
        )
        # a GRANT is repeatable, so re-running the script stays non-destructive
        assert "REVOKE SET ON PARAMETER" not in body

    def test_disposable_database_fixture_follows_the_provisioning_contract(self):
        """The migration fixture stores the sentinel for its database; it never fakes it in
        the session, which the guard would now refuse anyway."""
        source = (Path(__file__).parent / "integration_db.py").read_text()
        start = source.index("def create_database()")
        fixture = source[start : source.index("\ndef ", start + 1)]
        assert "CREATE DATABASE" in fixture and "TEMPLATE template1" in fixture
        assert 'ALTER DATABASE \\"{name}\\" SET nextup.provisioning' in fixture
        assert "migrator_settings()" in fixture  # the owner role, never the admin
        for forbidden in ("set_config", "SET nextup.provisioning =", "PGOPTIONS", "-c nextup"):
            assert forbidden not in fixture.replace(
                'ALTER DATABASE \\"{name}\\" SET nextup.provisioning =', ""
            )
        assert "nextup.provisioning" not in source.replace(fixture, "")

    def test_provisioning_refuses_client_session_options(self):
        result, sql = self.run_namespaced(
            psql_exit=0, extra_env={"PGOPTIONS": "-c x.y=SENTINELVALUE"}
        )
        assert result.returncode == 1 and sql is None, "refused before psql is started"
        assert "PGOPTIONS is not allowed" in result.stderr
        assert "SENTINELVALUE" not in result.stdout + result.stderr
        result, sql = self.run_namespaced(psql_exit=0, extra_env={"PGOPTIONS": ""})
        assert result.returncode == 1 and sql is None

    def test_provisioning_refuses_every_client_variable_by_name(self):
        """psql is a libpq client; nothing may point it at another server."""
        for name in (
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGSYSCONFDIR",
            "PGPASSFILE",
            "PGSSLMODE",
            "PGTZ",
            "PGNEWTHING",
        ):
            result, sql = self.run_namespaced(psql_exit=0, extra_env={name: "SENTINELVALUE"})
            assert result.returncode == 1 and sql is None, name
            assert f"{name} is not allowed" in result.stderr, name
            assert "SENTINELVALUE" not in result.stdout + result.stderr, name

    def test_provisioning_keeps_what_the_server_image_needs(self):
        """PGDATA is the server's data directory; PGPASSWORD is exported by the official
        image's entrypoint for the init phase; PG_MAJOR and PG_VERSION are image metadata."""
        server = {
            "PGDATA": "/var/lib/postgresql/data",
            "PGPASSWORD": "p" * 32,
            "PG_MAJOR": "17",
            "PG_VERSION": "17.11-1.pgdg12+2",
            "POSTGRES_PASSWORD_FILE": "/run/secrets/db_admin_password",
            "LANG": "en_US.utf8",
        }
        result, sql = self.run_namespaced(psql_exit=0, extra_env=server)
        assert result.returncode == 0 and sql is not None, result.stderr
        assert "provisioning of nextup_dev complete" in result.stdout
        assert "p" * 32 not in result.stdout + result.stderr + sql
        body = INIT_SCRIPT.read_text()
        assert "PGDATA | PGPASSWORD) ;;" in body and "PG[A-Z]*) refuse" in body
        assert body.index("compgen -e") < body.index("psql --no-psqlrc")

    def run_namespaced(self, psql_exit, owner="o" * 32, app="a" * 32, extra_env=None):
        """Run the real script with tmpfs password files in a throwaway user+mount namespace."""
        if subprocess.run(["unshare", "-rm", "true"], capture_output=True).returncode:
            pytest.skip("user and mount namespaces are unavailable here")
        with tempfile.TemporaryDirectory() as stub:
            sql = Path(stub) / "sql.txt"
            psql = Path(stub) / "psql"
            psql.write_text(f"#!/bin/sh\ncat > {sql}\nexit {psql_exit}\n")
            psql.chmod(0o700)
            setup = (
                "mount -t tmpfs -o mode=0755 tmpfs /run && mkdir -m 0700 /run/nextup-initdb && "
                f"printf '%s\\n' {owner} > /run/nextup-initdb/db_owner_password && "
                f"printf '%s\\n' {app} > /run/nextup-initdb/db_app_password && "
                f"exec /bin/bash {INIT_SCRIPT}"
            )
            result = subprocess.run(
                ["unshare", "-rm", "/bin/bash", "-c", setup],
                env={
                    "PATH": f"{stub}:/usr/bin:/bin",
                    "POSTGRES_USER": "nextup_dev_admin",
                    "POSTGRES_DB": "postgres",
                    **(extra_env or {}),
                },
                capture_output=True,
                text=True,
                timeout=20,
            )
            return result, sql.read_text() if sql.exists() else None

    def test_interrupted_provisioning_fails_closed(self):
        for code in (1, 3):
            result, sql = self.run_namespaced(psql_exit=code)
            assert result.returncode != 0, "a failed provisioning must fail the container start"
            assert "provisioning of" not in result.stdout
            assert sql is not None and "SET nextup.provisioning = 'complete-v1'" in sql
            for secret in ("o" * 32, "a" * 32):
                assert secret not in result.stdout + result.stderr + sql
        result, sql = self.run_namespaced(psql_exit=0)
        assert result.returncode == 0 and "provisioning of nextup_dev complete" in result.stdout
        result, sql = self.run_namespaced(psql_exit=0, owner="s" * 32, app="s" * 32)
        assert result.returncode == 1 and sql is None and "must differ" in result.stderr


def sql_statements(text):
    """The heredoc SQL without comments."""
    body = text[text.index("<<'SQL'") + len("<<'SQL'") : text.rindex("\nSQL\n")]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
