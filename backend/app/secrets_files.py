"""Strict reader for ``NEXTUP_*_FILE`` secrets (Docker secrets or operator-provisioned files).

The descriptor is opened with ``O_NOFOLLOW`` and every check runs on ``fstat`` of that
descriptor, so the file that is checked is the file that is read. Errors carry only
the variable name and a fixed code; never the path contents, the value or OS text.
"""

import errno
import os
import stat

from app.guard.errors import SecretFileError

DEFAULT_SECRET_ROOTS = ("/run/secrets",)
MAX_SECRET_BYTES = 4096


def secret_roots(environ) -> tuple[str, ...]:
    """/run/secrets, plus NEXTUP_SECRETS_DIR when an operator provisions files elsewhere."""
    extra = environ.get("NEXTUP_SECRETS_DIR", "")
    roots = list(DEFAULT_SECRET_ROOTS)
    if extra:
        if not os.path.isabs(extra):
            raise SecretFileError("NXG-S02", keys=("NEXTUP_SECRETS_DIR",))
        roots.append(os.path.normpath(extra))
    return tuple(roots)


def _inside(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def read_secret_file(
    path: str,
    *,
    variable: str,
    roots: tuple[str, ...] = DEFAULT_SECRET_ROOTS,
    max_bytes: int = MAX_SECRET_BYTES,
    allowed_owners: tuple[int, ...] | None = None,
) -> str:
    """Return the secret value (one trailing newline removed) or raise SecretFileError."""

    def fail(code):
        raise SecretFileError(code, keys=(variable,)) from None

    if not isinstance(path, str) or not path or not os.path.isabs(path):
        fail("NXG-S01")
    normalized = os.path.normpath(path)
    if not _inside(normalized, roots):
        fail("NXG-S02")
    # Reject symlinks anywhere in the path, not just the final component.
    try:
        if os.path.realpath(normalized) != normalized:
            fail("NXG-S02")
    except OSError:
        fail("NXG-S01")

    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(normalized, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            fail("NXG-S02")
        if exc.errno in (errno.EACCES, errno.EPERM):
            fail("NXG-S05")
        fail("NXG-S01")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            fail("NXG-S01")
        owners = allowed_owners if allowed_owners is not None else (os.geteuid(), 0)
        if info.st_uid not in owners:
            fail("NXG-S07")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_IROTH | stat.S_IXOTH):
            fail("NXG-S03")
        if info.st_size > max_bytes:
            fail("NXG-S04")
        try:
            data = os.read(descriptor, max_bytes + 1)
        except OSError:
            fail("NXG-S05")
    finally:
        os.close(descriptor)

    if len(data) > max_bytes:
        fail("NXG-S04")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        fail("NXG-S04")
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if not text or any(ch in text for ch in ("\x00", "\n", "\r")):
        fail("NXG-S04")
    return text


def read_from_environ(environ, variable: str, *, allowed_owners=None) -> str | None:
    """Value of ``variable`` from ``variable`` or ``variable_FILE``; never both."""
    inline = environ.get(variable)
    file_variable = f"{variable}_FILE"
    file_path = environ.get(file_variable)
    if inline is not None and file_path is not None:
        raise SecretFileError("NXG-C04", keys=(variable, file_variable))
    if file_path is not None:
        return read_secret_file(
            file_path,
            variable=file_variable,
            roots=secret_roots(environ),
            allowed_owners=allowed_owners,
        )
    return inline


__all__ = [
    "DEFAULT_SECRET_ROOTS",
    "MAX_SECRET_BYTES",
    "read_from_environ",
    "read_secret_file",
    "secret_roots",
]
