"""Migration-token handoff: standard input only, never an argument.

Covers disclosure (the token never appears in arguments, output or errors), refusal
(tokens in arguments, empty/oversized/multi-line/binary input), expiration and replay
through the real CLI path with the database ledger semantics of ``apply_in_transaction``,
and the Alembic ``-x nextup_token=stdin`` entry point. No database and no network.
"""

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alembic import command
from test_env_authorization import (
    NOW,
    SENTINEL,
    FakeConnection,
    Recorder,
    alembic_config,
    initialized_after,
    no_engine,
    rows_for,
    settings,
    token_for,
)

from app import guard
from app.guard import __main__ as cli
from app.guard.errors import GuardRefused
from app.guard.plan import MAX_TOKEN_LENGTH


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


class Stdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class Untouchable:
    def isatty(self):
        raise AssertionError("stdin must not be consulted")

    read = buffer = isatty


def run(argv, stdin=None, monkeypatch=None):
    if monkeypatch is not None and stdin is not None:
        monkeypatch.setattr("sys.stdin", stdin)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def through_ledger(migrator, monkeypatch):
    """`apply` via the real CLI, ending in apply_in_transaction on a fake connection."""
    state = SimpleNamespace(
        connection=FakeConnection(rows_for(migrator.identity)),
        now=NOW + 5,
        seen=[],
        run=Recorder(after=initialized_after(migrator.identity, "0029")),
    )
    monkeypatch.setattr(
        guard, "migration_engine", lambda *_a, **_k: SimpleNamespace(dispose=lambda: None)
    )

    def apply_migration(_engine, settings, token, *, operation="upgrade", target=None, now=None):
        state.seen.append(token)
        return guard.apply_in_transaction(
            state.connection,
            settings,
            token,
            operation=operation,
            target="0029",
            run=state.run,
            now=state.now,
        )

    monkeypatch.setattr(guard, "apply_migration", apply_migration)
    return state


class TestStdinHandoff:
    def test_apply_takes_the_token_from_stdin_and_never_prints_it(
        self, migrator, through_ledger, monkeypatch
    ):
        _, token = token_for(through_ledger.connection, migrator)
        code, out, err = run(["apply"], Stdin(token + "\n"), monkeypatch)
        assert code == 0 and "APPLIED mode=INIT" in out
        assert through_ledger.seen == [token]
        assert token not in out + err and token.split(".")[2] not in out + err

    def test_a_hidden_terminal_prompt_is_used_on_a_tty(self, migrator, through_ledger, monkeypatch):
        _, token = token_for(through_ledger.connection, migrator)
        prompt = MagicMock(return_value=token)
        monkeypatch.setattr("getpass.getpass", prompt)
        monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("echoing input() used"))
        code, out, err = run(["apply"], Stdin("", tty=True), monkeypatch)
        assert code == 0 and prompt.call_count == 1 and token not in out + err

    def test_plan_never_prints_the_token(self, migrator, monkeypatch):
        token = "nxa1." + "p" * 60 + "." + "m" * 43
        decision = SimpleNamespace(
            mode="INIT", steps=("0001",), data_changing_steps=(), from_revision=None, target="0029"
        )
        monkeypatch.setattr(
            guard, "migration_engine", lambda *_a, **_k: SimpleNamespace(dispose=lambda: None)
        )
        monkeypatch.setattr(guard, "plan_migration", lambda *a, **k: (decision, token))
        code, out, err = run(["plan"], Untouchable(), monkeypatch)
        assert code == 0 and "PLAN mode=INIT" in out and "authorization withheld" in out
        assert "nxa1." not in out + err and "p" * 60 not in out + err and "m" * 43 not in out + err


CODE = "0123456789ab"


@pytest.fixture
def session(migrator, monkeypatch):
    """`plan-apply` through the real CLI: real token issuing on a fake connection, then the
    real apply_in_transaction (ledger, expiry, binding) on the same fake state."""
    state = SimpleNamespace(
        connection=FakeConnection(rows_for(migrator.identity)),
        now=NOW + 5,
        planned=[],
        applied=[],
        run=Recorder(after=initialized_after(migrator.identity, "0029")),
    )
    monkeypatch.setattr(
        guard, "migration_engine", lambda *_a, **_k: SimpleNamespace(dispose=lambda: None)
    )

    def plan_migration(_engine, settings, *, operation="upgrade", target=None, ttl=None, now=None):
        decision, token = token_for(
            state.connection, settings, operation=operation, target=target, ttl=ttl or 600
        )
        state.planned.append(token)
        return decision, token

    def apply_migration(_engine, settings, token, *, operation="upgrade", target=None, now=None):
        state.applied.append(token)
        return guard.apply_in_transaction(
            state.connection,
            settings,
            token,
            operation=operation,
            target="0029",
            run=state.run,
            now=state.now,
        )

    monkeypatch.setattr(guard, "plan_migration", plan_migration)
    monkeypatch.setattr(guard, "apply_migration", apply_migration)
    monkeypatch.setattr(cli.secrets, "token_hex", lambda n: CODE)
    return state


class TestPlanApply:
    def test_confirmed_session_applies_and_the_token_never_leaves_the_process(
        self, session, monkeypatch
    ):
        code, out, err = run(["plan-apply"], Stdin(CODE + "\n"), monkeypatch)
        assert code == 0 and "APPLIED mode=INIT to=0029" in out
        assert f"confirmation={CODE} " in out and "awaiting confirmation" in out
        token = session.planned[0]
        assert session.applied == [token] and len(session.run.calls) == 1
        for part in [token, *token.split(".")[1:]]:
            assert part not in out + err
        assert "nxa1." not in out + err

    @pytest.mark.parametrize(
        "typed", ["", "\n", "0123456789AB\n", "0123456789a\n", "x" * 200 + "\n", "nope\n"]
    )
    def test_anything_but_the_code_applies_nothing(self, session, monkeypatch, typed):
        code, out, err = run(["plan-apply"], Stdin(typed), monkeypatch)
        assert code == 3 and "NXG-A11" in err and "APPLIED" not in out
        assert session.applied == [] and session.run.calls == []
        assert "nxa1." not in out + err

    def test_nothing_to_apply_never_reads_stdin(self, migrator, monkeypatch):
        decision = SimpleNamespace(
            mode="NOOP", steps=(), data_changing_steps=(), from_revision="0029", target="0029"
        )
        monkeypatch.setattr(
            guard, "migration_engine", lambda *_a, **_k: SimpleNamespace(dispose=lambda: None)
        )
        monkeypatch.setattr(guard, "plan_migration", lambda *a, **k: (decision, None))
        code, out, _ = run(["plan-apply"], Untouchable(), monkeypatch)
        assert code == 0 and "nothing to apply" in out and "awaiting" not in out

    def test_a_late_confirmation_finds_the_token_expired(self, session, monkeypatch):
        session.now = NOW + 10_000
        code, out, err = run(["plan-apply", "--ttl", "60"], Stdin(CODE + "\n"), monkeypatch)
        assert code == 3 and "NXG-A04" in err and session.run.calls == []
        assert "nxa1." not in out + err

    def test_each_session_has_its_own_random_code_unrelated_to_the_token(
        self, migrator, monkeypatch
    ):
        import hashlib

        from app.guard import __main__ as module

        codes = {module.secrets.token_hex(6) for _ in range(50)}
        assert len(codes) == 50
        token = "nxa1." + "p" * 60 + "." + "m" * 43
        assert all(c not in hashlib.sha256(token.encode()).hexdigest() for c in codes)

    def test_terminal_confirmation_uses_a_prompt(self, session, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_: CODE)
        code, out, err = run(["plan-apply"], Stdin("", tty=True), monkeypatch)
        assert code == 0 and "APPLIED" in out and "nxa1." not in out + err

    def test_refusals_before_planning(self, monkeypatch):
        from test_guard_entrypoints import runtime

        current = runtime()
        monkeypatch.setattr("app.config.get_settings", lambda: current)
        code, _, err = run(["plan-apply"], Untouchable(), monkeypatch)
        assert code == 3 and "NXG-I04" in err

    def test_downgrade_needs_a_target_before_any_engine(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        code, _, err = run(["plan-apply", "--operation", "downgrade"], Untouchable(), monkeypatch)
        assert code == 3 and "NXG-A06" in err

    def test_tokens_in_arguments_are_refused_for_plan_apply_too(self, monkeypatch):
        code, out, err = run(
            ["plan-apply", "--target", "nxa1.payload.mac"], Untouchable(), monkeypatch
        )
        assert code == 3 and "NXG-A10" in err and "payload" not in out + err

    def test_same_plan_and_apply_path_as_the_programmatic_migration(self, migrator, monkeypatch):
        calls = []
        engine = SimpleNamespace(dispose=lambda: None)
        decision = SimpleNamespace(
            mode="INIT",
            steps=("0001",),
            data_changing_steps=(),
            from_revision=None,
            target="0029",
            changes_schema=True,
        )
        monkeypatch.setattr(guard, "migration_engine", lambda settings, **_: engine)
        monkeypatch.setattr(
            guard,
            "plan_migration",
            lambda engine, settings, **kw: (
                calls.append(("plan", kw.get("operation"))) or (decision, "nxa1.p.m")
            ),
        )
        monkeypatch.setattr(
            guard,
            "apply_migration",
            lambda engine, settings, token, **kw: (
                calls.append(("apply", token, kw["target"])) or decision
            ),
        )
        guard.migrate_programmatically(engine, migrator)
        programmatic = list(calls)
        calls.clear()
        monkeypatch.setattr(cli.secrets, "token_hex", lambda n: CODE)
        assert run(["plan-apply"], Stdin(CODE + "\n"), monkeypatch)[0] == 0
        assert programmatic == calls == [("plan", "upgrade"), ("apply", "nxa1.p.m", "0029")]


class TestRefusal:
    @pytest.mark.parametrize(
        "argv",
        [
            ["apply", "--token", "nxa1.payload.mac"],
            ["apply", "--token=nxa1.payload.mac"],
            ["apply", "--token"],
            ["apply", "nxa1.payload.mac"],
            ["apply", "--target", "nxa1.payload.mac"],
            ["plan", "--target=0029nxa1.payload.mac"],
            ["exec", "--", "uvicorn", "nxa1.payload.mac"],
        ],
    )
    def test_tokens_in_arguments_are_refused_first_and_never_echoed(self, argv, monkeypatch):
        monkeypatch.setattr("app.config.get_settings", lambda: pytest.fail("settings were read"))
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        code, out, err = run(argv, Untouchable(), monkeypatch)
        assert code == 3 and "NXG-A10" in err
        assert "payload" not in out + err and "nxa1." not in out + err

    @pytest.mark.parametrize(
        "argv",
        [
            ["apply", "--bogus", SENTINEL],
            ["plan", "--ttl", SENTINEL],
            [SENTINEL],
            ["apply", SENTINEL],
        ],
    )
    def test_usage_errors_print_a_fixed_line_without_the_arguments(self, argv):
        code, out, err = run(argv)
        assert code == 4 and SENTINEL not in out + err
        assert "NXG-C14 invalid command-line arguments" in err

    @pytest.mark.parametrize(
        "data, expected",
        [
            ("", "NXG-A01"),
            ("\n", "NXG-A01"),
            ("\r\n", "NXG-A01"),
            ("x" * (MAX_TOKEN_LENGTH + 5), "NXG-A05"),
            ("nxa1.a.b\nsecond line\n", "NXG-A05"),
            ("nxa1.a.b\x00\n", "NXG-A05"),
            ("nxa1.é.b\n", "NXG-A05"),
        ],
    )
    def test_bad_stdin_is_refused_before_any_connection(
        self, migrator, monkeypatch, data, expected
    ):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        code, out, err = run(["apply"], Stdin(data), monkeypatch)
        assert code == 3 and expected in err
        for fragment in ("second line", "x" * 40, "é"):
            assert fragment not in out + err

    def test_binary_stdin_is_refused(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        stream = SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(b"\xff\xfenxa1.a.b\n"))
        code, _, err = run(["apply"], stream, monkeypatch)
        assert code == 3 and "NXG-A05" in err

    def test_the_runtime_role_is_refused_before_stdin_is_read(self, monkeypatch):
        from test_guard_entrypoints import runtime

        current = runtime()
        monkeypatch.setattr("app.config.get_settings", lambda: current)
        code, _, err = run(["apply"], Untouchable(), monkeypatch)
        assert code == 3 and "NXG-I04" in err


class TestExpirationAndReplay:
    def test_an_expired_token_is_refused_through_stdin(self, migrator, through_ledger, monkeypatch):
        _, token = token_for(through_ledger.connection, migrator, ttl=60)
        through_ledger.now = NOW + 10_000
        code, out, err = run(["apply"], Stdin(token + "\n"), monkeypatch)
        assert code == 3 and "NXG-A04" in err and token not in out + err
        assert through_ledger.run.calls == []

    def test_a_replayed_token_is_refused_through_stdin(self, migrator, through_ledger, monkeypatch):
        connection = through_ledger.connection
        _, token = token_for(connection, migrator)
        assert run(["apply"], Stdin(token + "\n"), monkeypatch)[0] == 0
        # Identical pre-state, same ledger: only single use stops it.
        through_ledger.connection = FakeConnection(
            rows_for(migrator.identity), consumed=connection.consumed
        )
        through_ledger.now = NOW + 7
        code, out, err = run(["apply"], Stdin(token + "\n"), monkeypatch)
        assert code == 3 and "NXG-A03" in err and token not in out + err
        assert len(through_ledger.run.calls) == 1

    def test_a_token_bound_to_another_state_is_refused(self, migrator, through_ledger, monkeypatch):
        _, token = token_for(through_ledger.connection, migrator)
        through_ledger.connection = FakeConnection(initialized_after(migrator.identity, "0028"))
        code, _, err = run(["apply"], Stdin(token + "\n"), monkeypatch)
        assert code == 3 and "NXG-A02" in err


class TestAlembicEntryPoint:
    def config(self, *xargs):
        config = alembic_config()
        config.cmd_opts = argparse.Namespace(x=list(xargs))
        return config

    def test_a_literal_token_argument_is_refused_before_connecting(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        monkeypatch.setattr("sys.stdin", Untouchable())
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(self.config("nextup_token=nxa1.payload.mac"), "head")
        assert caught.value.code == "NXG-A10" and "payload" not in str(caught.value)

    def test_stdin_token_reaches_the_single_apply_path(self, migrator, monkeypatch):
        seen = []
        engine = MagicMock()
        monkeypatch.setattr(guard, "migration_engine", lambda *_a, **_k: engine)
        monkeypatch.setattr(
            guard,
            "apply_in_transaction",
            lambda connection, settings, token, **kw: seen.append((token, kw["operation"])),
        )
        monkeypatch.setattr("sys.stdin", Stdin("nxa1.payload.mac\n"))
        command.upgrade(self.config("nextup_token=stdin"), "head")
        assert seen == [("nxa1.payload.mac", "upgrade")]

    def test_write_without_a_token_and_empty_stdin_are_refused(self, migrator, monkeypatch):
        monkeypatch.setattr(guard, "migration_engine", no_engine)
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(self.config(), "head")
        assert caught.value.code == "NXG-A01"
        monkeypatch.setattr("sys.stdin", Stdin(""))
        with pytest.raises(GuardRefused) as caught:
            command.upgrade(self.config("nextup_token=stdin"), "head")
        assert caught.value.code == "NXG-A01"

    def test_read_only_commands_never_read_stdin(self, migrator, monkeypatch):
        engine, read_only = MagicMock(), []
        monkeypatch.setattr(guard, "migration_engine", lambda *_a, **_k: engine)
        monkeypatch.setattr(
            guard, "_read_only", lambda context, connection, metadata: read_only.append(1)
        )
        monkeypatch.setattr("sys.stdin", Untouchable())
        command.current(self.config("nextup_token=stdin"))
        assert read_only == [1]
