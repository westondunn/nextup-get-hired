"""Exact-value disclosure audit for one disposable CI run.

The launcher registers this run's synthetic secret values and its migration token **in
memory only**. Before secret cleanup it scans:

* the run's evidence directory and e2e output directory (regular files only; links,
  hard links and special files are reported as anomalies, never followed);
* Compose logs of the run's project (full, not the saved tail);
* ``docker inspect`` of containers labelled with the run's project, and each running
  container's ``/proc/1/environ``. Any container whose project label differs is never
  scanned (it is reported as an anomaly and its data is discarded).

Every source is also searched for the migration-token format (``nxa1.<payload>.<mac>``):
the token itself never reaches the launcher (``guard plan-apply``), so this is the check
that it was not disclosed. Each registered value is searched as written and in common
encodings (base64 and base64url at every
byte alignment, hex, UTF-16LE, percent-encoding and JSON escaping where they differ) and
as 16-character head and tail fragments. The report holds categories, counts and
non-sensitive source identifiers only: no value, no fragment, no hash or HMAC of a value.
The report text is itself scanned before it is returned. ``clear()`` drops the values.

A run fails if anything is found, if any source could not be scanned, or if an anomaly
was seen ("complete" and "passed" are separate fields).
"""

import base64
import json
import os
import re
import stat
import urllib.parse

FRAGMENT = 16
CHUNK = 1 << 20
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SAFE_SECRET_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PROJECT_LABEL = "com.docker.compose.project"
CI_PROJECT = re.compile(r"^nextup-ci-[0-9a-f]{12}$")
# Numeric owner of a container's PID 1 (``stat -c %u:%g``); never a name, never root.
PROCESS_OWNER = re.compile(r"^[1-9][0-9]{0,9}:[0-9]{1,10}$")
# The migration token never reaches the launcher (``guard plan-apply`` keeps it in the guard
# process), so its value cannot be registered. Every source is also scanned for its format.
TOKEN_FORMAT = re.compile(rb"nxa1\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")
TOKEN_LABEL = ("migration_token", "token-format")
MAX_TOKEN = 1024


def allowed_engine_command(project, args):
    """The only read-only engine commands the audit may issue (all scoped to ``project``)."""
    if not isinstance(project, str) or not CI_PROJECT.fullmatch(project):
        return False
    args = list(args)
    if args == ["ps", "-aq", "--no-trunc", "--filter", f"label={PROJECT_LABEL}={project}"]:
        return True
    if args[:1] == ["inspect"] and len(args) > 1:
        return all(CONTAINER_ID.fullmatch(a) for a in args[1:])
    if len(args) == 4 and args[0] == "exec" and args[2:] == ["cat", "/proc/1/environ"]:
        return bool(CONTAINER_ID.fullmatch(args[1]))
    # Services that drop privileges after start (postgres, redis): the default exec user is
    # root without CAP_SYS_PTRACE and cannot read PID 1's environment. The audit then asks
    # for PID 1's numeric owner and repeats the same read as that, less privileged, user.
    if len(args) == 6 and args[0] == "exec" and args[2:] == ["stat", "-c", "%u:%g", "/proc/1"]:
        return bool(CONTAINER_ID.fullmatch(args[1]))
    if len(args) == 6 and args[:2] == ["exec", "--user"] and args[4:] == ["cat", "/proc/1/environ"]:
        return bool(PROCESS_OWNER.fullmatch(str(args[2])) and CONTAINER_ID.fullmatch(args[3]))
    return False


def _b64_cores(raw, encode):
    """Encodings of ``raw`` that survive embedding in a longer base64 stream at any
    alignment: the characters determined by ``raw`` alone."""
    cores = {}
    for offset in (0, 1, 2):
        encoded = encode(b"\0" * offset + raw)
        skip = 4 if offset else 0
        tail = 4 if (offset + len(raw)) % 3 else 0
        core = encoded[skip : len(encoded) - tail]
        if len(core) >= FRAGMENT:
            cores[offset] = core
    return cores


def variants(value, parts=()):
    """``{variant name: needle bytes}`` for one secret value (needles that differ only)."""
    raw = value.encode()
    found = {"raw": raw}
    for name, encode in (("base64", base64.b64encode), ("base64url", base64.urlsafe_b64encode)):
        for offset, core in _b64_cores(raw, encode).items():
            found[f"{name}@{offset}"] = core
    found["hex"] = raw.hex().encode()
    found["HEX"] = raw.hex().upper().encode()
    found["utf16le"] = value.encode("utf-16-le")
    found["percent"] = urllib.parse.quote(value, safe="").encode()
    found["json"] = json.dumps(value)[1:-1].encode()
    if len(raw) >= 2 * FRAGMENT:
        found["head16"] = raw[:FRAGMENT]
        found["tail16"] = raw[-FRAGMENT:]
    for index, part in enumerate(parts):
        if len(part) >= FRAGMENT:
            found[f"part{index}"] = part.encode()
    unique, seen = {}, set()
    for name, needle in found.items():
        if needle and needle not in seen and (name == "raw" or needle != raw):
            unique[name] = needle
            seen.add(needle)
    return unique


class SecretAudit:
    def __init__(self):
        self._needles = {}  # needle bytes -> (secret name, variant)
        self._registered = {}  # secret name -> number of values
        self._findings = {}  # (secret, variant, source) -> count
        self._failed = {}  # source -> reason (fixed text)
        self._anomalies = []  # (source, kind)
        self._scanned = set()
        self._cleared = False

    def __repr__(self):
        return f"SecretAudit(secrets={len(self._registered)}, findings={len(self._findings)})"

    # ---------- registration (memory only) ----------

    def add(self, name, value):
        if not SAFE_SECRET_NAME.fullmatch(name):
            raise ValueError("secret names are fixed identifiers")
        if not isinstance(value, str) or len(value) < FRAGMENT:
            raise ValueError("refusing to audit a value shorter than the fragment length")
        parts = value.split(".") if name == "migration_token" else ()
        for variant, needle in variants(value, parts).items():
            self._needles[needle] = (name, variant)
        self._registered[name] = self._registered.get(name, 0) + 1

    def clear(self):
        self._needles.clear()
        self._cleared = True

    # ---------- scanning ----------

    def _record(self, source, counts):
        self._scanned.add(source)
        for (name, variant), count in counts.items():
            key = (name, variant, source)
            self._findings[key] = max(self._findings.get(key, 0), count)

    def _count(self, data):
        counts = {}
        for needle, label in self._needles.items():
            n = data.count(needle)
            if n:
                counts[label] = counts.get(label, 0) + n
        n = sum(1 for _ in TOKEN_FORMAT.finditer(data))
        if n:
            counts[TOKEN_LABEL] = counts.get(TOKEN_LABEL, 0) + n
        return counts

    def scan_bytes(self, source, data):
        if self._cleared:
            raise RuntimeError("audit values were already cleared")
        if isinstance(data, str):
            data = data.encode("utf-8", "surrogateescape")
        self._record(source, self._count(data))

    def _scan_descriptor(self, source, descriptor):
        longest = max([len(n) for n in self._needles] + [MAX_TOKEN + 1])
        counts, carry, last = {}, b"", None
        while True:
            chunk = os.read(descriptor, CHUNK)
            if not chunk:
                break
            window = carry + chunk
            # Count only matches that end inside the new chunk, so overlaps are not doubled.
            for needle, label in self._needles.items():
                start, n = 0, 0
                while True:
                    at = window.find(needle, start)
                    if at < 0:
                        break
                    if at + len(needle) > len(carry):
                        n += 1
                    start = at + 1
                if n:
                    counts[label] = counts.get(label, 0) + n
            # A format match touching the window end may be a truncated token: defer it to the
            # next window (or to end of file) so each token is counted exactly once.
            n = sum(1 for m in TOKEN_FORMAT.finditer(window) if len(carry) <= m.end() < len(window))
            if n:
                counts[TOKEN_LABEL] = counts.get(TOKEN_LABEL, 0) + n
            last = (window, len(carry))
            carry = window[-(longest - 1) :]
        if last is not None:
            window, base = last
            n = sum(1 for m in TOKEN_FORMAT.finditer(window) if m.end() == len(window) >= base)
            if n:
                counts[TOKEN_LABEL] = counts.get(TOKEN_LABEL, 0) + n
        self._record(source, counts)

    def scan_file(self, source, path):
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            self._anomalies.append((source, "not a regular file"))
            return
        if info.st_nlink != 1:
            self._anomalies.append((source, "additional hard links"))
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
        try:
            if (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) != (
                info.st_dev,
                info.st_ino,
            ):
                self._anomalies.append((source, "changed while being opened"))
                return
            self._scan_descriptor(source, descriptor)
        finally:
            os.close(descriptor)

    def scan_tree(self, label, root):
        """Every entry below ``root``; links are never followed, anomalies are recorded."""
        root = os.fspath(root)
        if not os.path.lexists(root):
            return
        if os.path.islink(root) or not os.path.isdir(root):
            self._anomalies.append((label, "root is not a real directory"))
            return
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in list(dirs):
                full = os.path.join(current, name)
                if os.path.islink(full):
                    self._anomalies.append(
                        (f"{label}:{os.path.relpath(full, root)}", "symlinked directory")
                    )
                    dirs.remove(name)
            for name in files:
                full = os.path.join(current, name)
                self.scan_file(f"{label}:{os.path.relpath(full, root)}", full)
        self._scanned.add(label)

    def source_failed(self, source, reason):
        self._failed[source] = str(reason)[:80]

    def anomaly(self, source, kind):
        self._anomalies.append((source, kind))

    # ---------- results ----------

    def disclosures(self):
        return sum(self._findings.values())

    def result(self):
        complete = bool(self._registered) and not self._failed and not self._cleared
        return {
            "passed": complete and not self.disclosures() and not self._anomalies,
            "complete": complete,
            "disclosures": self.disclosures(),
            "anomalies": len(self._anomalies),
            "failed_sources": len(self._failed),
        }

    def report(self):
        """Counts, categories and source identifiers only. Self-checked for the values."""
        findings = sorted(
            (
                {"secret": s, "variant": v, "source": src, "count": c}
                for (s, v, src), c in self._findings.items()
                if c
            ),
            key=lambda f: (f["secret"], f["variant"], f["source"]),
        )
        report = {
            "audit": "exact-value disclosure audit",
            **self.result(),
            "secrets_registered": dict(sorted(self._registered.items())),
            "variants_per_secret": sorted({v for _, v in self._needles.values()}),
            "sources_scanned": len(self._scanned),
            "failed_sources": dict(sorted(self._failed.items())),
            "anomalies": [{"source": s, "kind": k} for s, k in self._anomalies],
            "findings": findings,
        }
        if not self._cleared and self._count(json.dumps(report).encode()):
            # Never possible by construction; fail closed without echoing anything.
            return {
                "audit": "exact-value disclosure audit",
                "passed": False,
                "complete": False,
                "disclosures": -1,
                "anomalies": 0,
                "failed_sources": 1,
                "failed_sources_detail": {"report": "self-check failed"},
            }
        return report


def _name(item, index):
    name = str(item.get("Name") or "").lstrip("/")
    return name if SAFE_NAME.fullmatch(name) else f"container-{index}"


def collect_engine(audit, project, docker, compose_logs, process_env=True):
    """Scan the run's own engine artefacts. ``docker(args) -> (returncode, bytes)`` must
    refuse anything ``allowed_engine_command`` rejects; ``compose_logs() -> text``."""

    def call(args):
        if not allowed_engine_command(project, args):
            raise PermissionError("audit engine command outside the allowlist")
        return docker(args)

    code, out = call(["ps", "-aq", "--no-trunc", "--filter", f"label={PROJECT_LABEL}={project}"])
    if code:
        audit.source_failed("engine:ps", f"exit {code}")
        return
    ids = [line.strip() for line in out.decode(errors="replace").splitlines() if line.strip()]
    if not all(CONTAINER_ID.fullmatch(i) for i in ids):
        audit.source_failed("engine:ps", "unexpected container id format")
        return
    running = []
    if ids:
        code, out = call(["inspect", *ids])
        if code:
            audit.source_failed("engine:inspect", f"exit {code}")
        else:
            try:
                items = json.loads(out)
            except ValueError:
                audit.source_failed("engine:inspect", "unparseable output")
                items = []
            for index, item in enumerate(items):
                labels = ((item.get("Config") or {}).get("Labels")) or {}
                if labels.get(PROJECT_LABEL) != project:
                    audit.anomaly(f"engine:inspect:container-{index}", "foreign project excluded")
                    continue
                name = _name(item, index)
                audit.scan_bytes(f"engine:inspect:{name}", json.dumps(item, sort_keys=True))
                if (item.get("State") or {}).get("Running") and CONTAINER_ID.fullmatch(
                    str(item.get("Id"))
                ):
                    running.append((item["Id"], name))
    audit.scan_bytes("engine:compose-logs", compose_logs())
    if process_env:
        for container, name in running:
            code, out = call(["exec", container, "cat", "/proc/1/environ"])
            if code:
                # Not readable as the default exec user: retry as PID 1's own numeric user.
                # Every failure on the way is recorded, so the audit stays incomplete.
                owner_code, owner = call(["exec", container, "stat", "-c", "%u:%g", "/proc/1"])
                owner = owner.decode(errors="replace").strip() if not owner_code else ""
                if owner_code:
                    audit.source_failed(
                        f"engine:environ:{name}", f"exit {code}; owner exit {owner_code}"
                    )
                    continue
                if not PROCESS_OWNER.fullmatch(owner):
                    audit.source_failed(f"engine:environ:{name}", f"exit {code}; unexpected owner")
                    continue
                code, out = call(["exec", "--user", owner, container, "cat", "/proc/1/environ"])
            if code:
                audit.source_failed(f"engine:environ:{name}", f"exit {code}")
            else:
                audit.scan_bytes(f"engine:environ:{name}", out)
