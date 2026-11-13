"""Launcher side of ``python -m app.guard plan-apply``.

The guard plans, prints the plan and a random one-time confirmation code, then waits for
that code on standard input and applies in the same process. The authorization token never
leaves the guard: not on any argument, variable, pipe, log or container metadata.

``plan_apply`` runs the command with pipes, collects the output up to ``awaiting
confirmation``, asks ``decide(lines, code)`` what to send (normally the code; ``None``
cancels), then sends it or simply closes stdin, which applies nothing (NXG-A11).
"""

import re
import subprocess
import threading
from dataclasses import dataclass, field

GUARD_PREFIX = "nextup-guard: "
AWAITING = GUARD_PREFIX + "awaiting confirmation"
CODE = re.compile(r"(?:^| )confirmation=([0-9a-f]{12})(?: |$)")
MAX_LINES = 10_000


@dataclass
class Session:
    lines: list = field(default_factory=list)
    code: str | None = None
    awaited: bool = False
    confirmed: bool = False
    returncode: int | None = None
    timed_out: bool = False

    def guard_lines(self):
        return [line for line in self.lines if line.startswith(GUARD_PREFIX)]


def plan_apply(command, *, decide, cwd=None, env=None, timeout=1800, popen=subprocess.Popen):
    session = Session()
    process = popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def expire():
        session.timed_out = True
        process.kill()

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        for raw in process.stdout:
            line = raw.rstrip("\n")
            if len(session.lines) < MAX_LINES:
                session.lines.append(line)
            if line.startswith(GUARD_PREFIX):
                match = CODE.search(line)
                if match:
                    session.code = match.group(1)
            if line == AWAITING:
                session.awaited = True
                break
        if session.awaited and session.code:
            answer = decide(list(session.lines), session.code)
            if answer is not None:
                try:
                    process.stdin.write(answer + "\n")
                    process.stdin.flush()
                    session.confirmed = True
                except (BrokenPipeError, OSError):
                    session.confirmed = False
        try:
            process.stdin.close()  # EOF: an unconfirmed session applies nothing
        except (BrokenPipeError, OSError):
            pass
        for raw in process.stdout:
            if len(session.lines) < MAX_LINES:
                session.lines.append(raw.rstrip("\n"))
        session.returncode = process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
    return session
