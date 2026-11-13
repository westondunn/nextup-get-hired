"""Known migration lineage, pinned so that revisions 0001-0029 can never drift.

Revision identifiers are read statically from the migration files (no Alembic import,
no execution). ``LINEAGE.sha256`` pins every shared revision file; future OSS
revisions must be named ``oss_NNNN`` and are accepted only as descendants
of the pinned head.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.guard.errors import GuardRefused

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
PIN_FILE = "LINEAGE.sha256"
SHARED = tuple(f"{n:04d}" for n in range(1, 30))  # 0001-0029, preserved unchanged
OSS_REVISION = re.compile(r"^oss_\d{4}$")
_REVISION = re.compile(r'^revision\s*(?::\s*str\s*)?=\s*["\']([^"\']+)["\']', re.M)
_DOWN = re.compile(r'^down_revision\s*(?::[^=]*)?=\s*(None|["\']([^"\']*)["\'])', re.M)
GRANTING_REVISION = "0029"  # grants to a pre-existing role named n8n when it exists


@dataclass(frozen=True)
class Lineage:
    order: tuple[str, ...]  # root -> head
    digest: str  # sha256 of the pin file plus any OSS revision files

    @property
    def head(self) -> str:
        return self.order[-1]

    def __contains__(self, revision) -> bool:
        return revision in self.order

    def index(self, revision: str) -> int:
        return self.order.index(revision)

    def crosses(self, current: str | None, target: str, revision: str) -> bool:
        """True when upgrading from ``current`` (None = empty) to ``target`` applies ``revision``."""  # noqa: E501
        start = -1 if current is None else self.index(current)
        return start < self.index(revision) <= self.index(target)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(migrations: Path = MIGRATIONS) -> Lineage:
    versions = migrations / "versions"
    pins: dict[str, str] = {}
    pin_text = (migrations / PIN_FILE).read_text()
    for line in pin_text.splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        pins[name.strip()] = digest

    graph: dict[str, str | None] = {}
    files: dict[str, Path] = {}
    for path in sorted(versions.glob("*.py")):
        text = path.read_text()
        rev, down = _REVISION.search(text), _DOWN.search(text)
        if not rev or not down:
            raise GuardRefused("NXG-L04")
        revision = rev.group(1)
        if revision in graph:
            raise GuardRefused("NXG-L04")
        graph[revision] = None if down.group(1) == "None" else down.group(2)
        files[revision] = path

    # Every shared revision exists, is pinned, and is byte-identical to its pin.
    for revision in SHARED:
        path = files.get(revision)
        if path is None:
            raise GuardRefused("NXG-L04")
        relative = f"versions/{path.name}"
        if pins.get(relative) != _sha256(path):
            raise GuardRefused("NXG-L04")
    if len(pins) != len(SHARED):
        raise GuardRefused("NXG-L04")
    for revision in graph:
        if revision not in SHARED and not OSS_REVISION.fullmatch(revision):
            raise GuardRefused("NXG-L04")

    # Exactly one root and a single linear chain to one head.
    roots = [r for r, d in graph.items() if d is None]
    children: dict[str, list[str]] = {}
    for revision, down in graph.items():
        if down is not None:
            if down not in graph:
                raise GuardRefused("NXG-L04")
            children.setdefault(down, []).append(revision)
    if roots != ["0001"] or any(len(c) > 1 for c in children.values()):
        raise GuardRefused("NXG-L04")
    order = ["0001"]
    while order[-1] in children:
        order.append(children[order[-1]][0])
    if len(order) != len(graph) or tuple(order[:29]) != SHARED:
        raise GuardRefused("NXG-L04")

    digest = hashlib.sha256(pin_text.encode())
    for revision in order[29:]:
        digest.update(revision.encode() + b"\0" + _sha256(files[revision]).encode())
    return Lineage(tuple(order), digest.hexdigest())
