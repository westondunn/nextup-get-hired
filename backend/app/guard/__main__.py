"""``python -m app.guard {check,plan,plan-apply,apply,exec}``. One fixed line per outcome; no
tracebacks.

* ``check``: runtime identity check (runtime role). Exit 0 on PROCEED.
* ``plan [--operation upgrade|downgrade] [--target REV] [--ttl S]``: migrator role,
  read-only review. Prints the plan only; the authorization token is **never** printed.
* ``plan-apply [--operation ...] [--target REV] [--ttl S]``: migrator role. Plans exactly
  like ``plan``, prints the plan and a random one-time confirmation code (unrelated to the
  token), waits for that code on standard input and only then applies, in this same
  process, with the token it never let out of memory. A missing or wrong
  code applies nothing (NXG-A11); a late one finds the token expired (NXG-A04).
* ``apply [--operation ...] [--target REV]``: migrator role, for tokens issued in-process
  (tooling and tests; ``plan`` never prints one). Reads the token from
  **standard input** (hidden prompt on a terminal; one line from a pipe), revalidates it
  against the current database state and applies through ``apply_in_transaction``.
  Tokens are never accepted as arguments: an argument that carries one is refused
  (NXG-A10) before anything else runs, and is never echoed.
* ``exec -- CMD ...``: the image ENTRYPOINT for api, worker and scheduler. Runs the
  runtime check, then replaces itself with an allowed service command.

Exit codes: 0 PROCEED, 3 REFUSE, 4 configuration error, 5 database unreachable.
"""

import argparse
import hmac
import os
import secrets
import sys

from app.guard.errors import (
    EXIT_CONFIG,
    EXIT_REFUSE,
    GuardError,
    GuardRefused,
    classify_connection_error,
)
from app.guard.plan import MAX_TOKEN_LENGTH, TOKEN_PREFIX

SERVICE_MODULES = frozenset({"uvicorn", "celery"})


def _line(text: str) -> None:
    print(f"nextup-guard: {text}", flush=True)


def allowed_service_command(argv) -> bool:
    if not argv:
        return False
    head = os.path.basename(argv[0])
    if head in SERVICE_MODULES:
        return True
    # Dev debug overlay: python -m debugpy --listen ADDR -m uvicorn|celery ...
    if head in ("python", "python3") and argv[1:3] == ["-m", "debugpy"]:
        rest = argv[3:]
        return any(rest[i] == "-m" and rest[i + 1] in SERVICE_MODULES for i in range(len(rest) - 1))
    return False


def carries_token(argv) -> bool:
    """True if any argument is (or contains) an authorization token or the retired flag."""
    marker = TOKEN_PREFIX + "."
    return any(arg == "--token" or arg.startswith("--token=") or marker in arg for arg in argv)


def read_token(stream=None) -> str:
    """The token from standard input: a hidden prompt on a terminal, else one line.

    Empty input refuses with NXG-A01; anything oversized, multi-line or non-ASCII with
    NXG-A05. The value is never echoed.
    """
    stream = sys.stdin if stream is None else stream
    if stream is None:
        raise GuardRefused("NXG-A01")
    if stream.isatty():
        import getpass  # noqa: PLC0415

        value = getpass.getpass("nextup-guard: paste the token printed by plan (hidden): ")
        if len(value) > MAX_TOKEN_LENGTH:
            raise GuardRefused("NXG-A05")
    else:
        source = getattr(stream, "buffer", stream)
        raw = source.read(MAX_TOKEN_LENGTH + 3)
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("ascii")
            except UnicodeDecodeError:
                raise GuardRefused("NXG-A05") from None
        if len(raw) > MAX_TOKEN_LENGTH + 2:
            raise GuardRefused("NXG-A05")
        value, _, rest = raw.partition("\n")
        value = value.removesuffix("\r")
        if rest.strip():
            raise GuardRefused("NXG-A05")
    if not value:
        raise GuardRefused("NXG-A01")
    if not value.isascii() or not value.isprintable():
        raise GuardRefused("NXG-A05")
    return value


def _migrator():
    from app.config import get_settings  # noqa: PLC0415
    from app.guard import require_migrator  # noqa: PLC0415

    return require_migrator(get_settings())


def cmd_check(_args) -> int:
    from app.guard import check_service_startup  # noqa: PLC0415

    check_service_startup()
    _line("PROCEED-RUNTIME")
    return 0


MAX_CONFIRMATION_INPUT = 64


def _plan(settings, args):
    from app.guard import migration_engine, plan_migration  # noqa: PLC0415

    engine = migration_engine(settings)
    try:
        return plan_migration(
            engine, settings, operation=args.operation, target=args.target, ttl=args.ttl
        )
    finally:
        engine.dispose()


def _show_plan(decision, identity) -> None:
    steps = ", ".join(decision.steps) or "none"
    _line(
        f"PLAN mode={decision.mode} env={identity.environment} database={identity.database.name} "
        f"from={decision.from_revision or 'empty'} to={decision.target} steps={len(decision.steps)}"
    )
    _line(f"steps: {steps}")
    _line("data-changing steps: " + (", ".join(decision.data_changing_steps) or "none"))


def cmd_plan(args) -> int:
    settings = _migrator()
    decision, token = _plan(settings, args)
    _show_plan(decision, settings.identity)
    if token is None:
        _line("nothing to apply")
        return 0
    del token  # never printed, never handed out
    _line("authorization withheld: apply with plan-apply (confirmation on standard input)")
    return 0


def read_confirmation(stream=None) -> str:
    """One line from standard input (a visible prompt on a terminal; the code is not secret)."""
    stream = sys.stdin if stream is None else stream
    if stream is None:
        return ""
    if stream.isatty():
        try:
            return input(
                "nextup-guard: type the confirmation code to apply (anything else cancels): "
            )
        except EOFError:
            return ""
    source = getattr(stream, "buffer", stream)
    raw = source.readline(MAX_CONFIRMATION_INPUT + 1)
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    return raw.strip() if len(raw) <= MAX_CONFIRMATION_INPUT else ""


def cmd_plan_apply(args) -> int:
    from app.guard import apply_migration, migration_engine  # noqa: PLC0415

    settings = _migrator()
    env = settings.identity.environment
    if args.target is None and args.operation != "upgrade":
        raise GuardRefused("NXG-A06", env=env)  # before any engine
    decision, token = _plan(settings, args)
    _show_plan(decision, settings.identity)
    if token is None:
        _line("nothing to apply")
        return 0
    try:
        code = secrets.token_hex(6)  # unrelated to the token; reveals nothing about it
        _line(f"confirmation={code} expires_in={args.ttl}s single-use")
        _line("awaiting confirmation")
        typed = read_confirmation()
        if not hmac.compare_digest(typed.encode("ascii", "replace"), code.encode()):
            raise GuardRefused("NXG-A11", env=env)
        engine = migration_engine(settings)
        try:
            applied = apply_migration(
                engine, settings, token, operation=args.operation, target=decision.target
            )
        finally:
            engine.dispose()
    finally:
        del token
    _line(f"APPLIED mode={applied.mode} to={applied.target} env={env}")
    return 0


def cmd_apply(args) -> int:
    from app.guard import apply_migration, migration_engine  # noqa: PLC0415

    settings = _migrator()
    if args.target is None and args.operation != "upgrade":
        raise GuardRefused("NXG-A06", env=settings.identity.environment)  # before any engine
    token = read_token()  # before any engine: nothing to connect for an empty handoff
    engine = migration_engine(settings)
    try:
        decision = apply_migration(
            engine, settings, token, operation=args.operation, target=args.target
        )
    finally:
        del token
        engine.dispose()
    _line(f"APPLIED mode={decision.mode} to={decision.target} env={settings.identity.environment}")
    return 0


def cmd_exec(args) -> int:
    from app.guard import check_service_startup  # noqa: PLC0415

    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not allowed_service_command(command):
        raise GuardRefused("NXG-X01")
    check_service_startup()
    from app.db import get_engine  # noqa: PLC0415

    get_engine().dispose()
    _line("PROCEED-RUNTIME")
    os.execvp(command[0], command)
    return EXIT_REFUSE  # not reached


class _Parser(argparse.ArgumentParser):
    """Usage errors print one fixed line: arguments are never echoed (they may hold a token)."""

    def error(self, message):  # noqa: ARG002 - the message quotes the arguments
        print("nextup-guard: CONFIG NXG-C14 invalid command-line arguments", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)


def parser() -> argparse.ArgumentParser:
    root = _Parser(
        prog="python -m app.guard",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = root.add_subparsers(dest="action", required=True)
    sub.add_parser("check")
    for name in ("plan", "plan-apply", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--operation", choices=("upgrade", "downgrade"), default="upgrade")
        p.add_argument("--target")
        if name != "apply":
            p.add_argument("--ttl", type=int, default=600)
    p = sub.add_parser("exec")
    p.add_argument("command", nargs=argparse.REMAINDER)
    return root


ACTIONS = {
    "check": cmd_check,
    "plan": cmd_plan,
    "plan-apply": cmd_plan_apply,
    "apply": cmd_apply,
    "exec": cmd_exec,
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if carries_token(argv):
        print(GuardRefused("NXG-A10").line(), file=sys.stderr, flush=True)
        return EXIT_REFUSE
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:  # argparse usage errors: configuration class
        return 4 if exc.code else 0
    try:
        return ACTIONS[args.action](args)
    except GuardError as exc:
        print(exc.line(), file=sys.stderr, flush=True)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - never print driver or library text
        from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

        if isinstance(exc, SQLAlchemyError):
            error = classify_connection_error(exc)
            print(error.line(), file=sys.stderr, flush=True)
            return error.exit_code
        print(
            f"nextup-guard: REFUSE unexpected failure ({type(exc).__name__})",
            file=sys.stderr,
            flush=True,
        )
        return EXIT_REFUSE


def _excepthook(exc_type, _exc, _tb) -> None:
    print(
        f"nextup-guard: REFUSE unexpected failure ({exc_type.__name__})",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    sys.excepthook = _excepthook
    sys.exit(main())
