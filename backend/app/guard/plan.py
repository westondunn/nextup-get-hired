"""Migration authorization: signed, expiring, single-use tokens bound to database state.

Flow (wired in Batch 2b):

1. ``plan`` (read-only): gather facts, ``decide_migration``, ``binding()`` the result,
   ``issue()`` a token. A human reviews the printed plan and passes the token on.
2. ``apply``: under an advisory lock, gather facts again and call
   ``revalidate_and_consume()``. It recomputes the decision and binding from the
   *current* state, verifies signature, expiry and binding, and consumes the nonce in
   the ledger. Only then may Alembic run (``env.py`` accepts nothing weaker).

Token: ``nxa1.<payload>.<mac>``, both URL-safe base64. The payload holds a 256-bit random
nonce, issue and expiry times, the binding digest, operation and target. The MAC is
HMAC-SHA256 with the migrator-only key (``NEXTUP_MIGRATION_KEY_FILE``), which runtime
containers never receive.

Single use relies on the ledger. ``InMemoryLedger`` is for tests only. The
database-backed ledger is ``app.guard.marker.DatabaseLedger`` (2b): a unique nonce row
inserted in the migration transaction under the guard's advisory lock. **Replay
prevention is not complete until that ledger is tested against a real disposable
database.**
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from typing import Protocol

from app.guard.errors import GuardRefused
from app.guard.facts import Facts
from app.guard.lineage import Lineage
from app.guard.policy import Decision, decide_migration

GUARD_VERSION = "2c.1"
TOKEN_PREFIX = "nxa1"
DEFAULT_TTL_SECONDS = 600
MAX_TTL_SECONDS = 900
MIN_TTL_SECONDS = 60
CLOCK_SKEW_SECONDS = 60
NONCE_BYTES = 32
MAX_TOKEN_LENGTH = 1024


class Ledger(Protocol):
    def consume(self, nonce_id: str, expires_at: int) -> bool:
        """Atomically record ``nonce_id``; False if it was already recorded."""


class InMemoryLedger:
    """Test double. Not shared across processes; never used for real migrations."""

    def __init__(self):
        self._used: dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, nonce_id: str, expires_at: int) -> bool:
        with self._lock:
            if nonce_id in self._used:
                return False
            self._used[nonce_id] = expires_at
            return True


@dataclass(frozen=True)
class Authorization:
    nonce_id: str
    binding_digest: str
    operation: str
    target: str | None
    expires_at: int

    def __repr__(self):
        return f"Authorization(operation={self.operation!r}, target={self.target!r})"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    if not text or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in text
    ):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _key(identity) -> bytes:
    if identity.role != "migrator" or identity.migration_key is None:
        raise GuardRefused("NXG-A01", env=identity.environment)
    secret = identity.migration_key.get_secret_value().encode()
    return hmac.new(b"nextup-migration-authorization-v1", secret, hashlib.sha256).digest()


def binding(facts: Facts, identity, decision: Decision, lineage: Lineage) -> str:
    """Digest of everything the authorization is bound to. Contains no secrets."""
    marker = None
    if facts.markers:
        m = facts.markers[0]
        marker = [
            m.environment,
            m.lineage,
            m.database_name,
            m.cluster_name,
            m.system_identifier,
            m.instance_id,
        ]
    value = {
        "v": 1,
        "env": identity.environment,
        "role": facts.current_user,
        "database": facts.database,
        "cluster": facts.cluster_name,
        "system_identifier": facts.system_identifier,
        "instance_id": None if identity.instance_id is None else str(identity.instance_id),
        "marker": marker,
        "revisions": list(facts.alembic_versions),
        "mode": decision.mode,
        "from": decision.from_revision,
        "target": decision.target,
        "steps": list(decision.steps),
        "lineage": lineage.digest,
        "guard": GUARD_VERSION,
    }
    return hashlib.sha256(_canonical(value)).hexdigest()


def issue(
    digest: str,
    decision: Decision,
    identity,
    *,
    now: int,
    ttl: int = DEFAULT_TTL_SECONDS,
    nonce: bytes | None = None,
) -> str:
    if not decision.changes_schema:
        raise GuardRefused("NXG-A06", env=identity.environment)
    if not MIN_TTL_SECONDS <= ttl <= MAX_TTL_SECONDS:
        raise GuardRefused("NXG-A05", env=identity.environment)
    nonce = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
    payload = {
        "v": 1,
        "nonce": _b64(nonce),
        "iat": int(now),
        "exp": int(now) + int(ttl),
        "digest": digest,
        "op": decision.mode,
        "target": decision.target,
    }
    body = _b64(_canonical(payload))
    signed = f"{TOKEN_PREFIX}.{body}".encode()
    mac = hmac.new(_key(identity), signed, hashlib.sha256).digest()
    return f"{TOKEN_PREFIX}.{body}.{_b64(mac)}"


def verify(
    token: str, *, expected_digest: str, identity, now: int, ledger: Ledger
) -> Authorization:
    env = identity.environment
    key = _key(identity)
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
        raise GuardRefused("NXG-A01" if not token else "NXG-A05", env=env)
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise GuardRefused("NXG-A05", env=env)
    try:
        mac = _unb64(parts[2])
        expected = hmac.new(key, f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise GuardRefused("NXG-A05", env=env)
        payload = json.loads(_unb64(parts[1]))
        nonce = _unb64(payload["nonce"])
        iat, exp, digest = int(payload["iat"]), int(payload["exp"]), str(payload["digest"])
        op, target = str(payload["op"]), payload.get("target")
        if payload.get("v") != 1 or len(nonce) != NONCE_BYTES:
            raise GuardRefused("NXG-A05", env=env)
    except GuardRefused:
        raise
    except (ValueError, KeyError, TypeError):
        raise GuardRefused("NXG-A05", env=env) from None
    if exp - iat > MAX_TTL_SECONDS or exp <= iat:
        raise GuardRefused("NXG-A05", env=env)
    if iat > now + CLOCK_SKEW_SECONDS or now >= exp:
        raise GuardRefused("NXG-A04", env=env)
    if not hmac.compare_digest(digest, expected_digest):
        raise GuardRefused("NXG-A02", env=env)
    nonce_id = hashlib.sha256(nonce).hexdigest()
    if not ledger.consume(nonce_id, exp):
        raise GuardRefused("NXG-A03", env=env)
    return Authorization(nonce_id, digest, op, target, exp)


def plan(
    facts: Facts,
    identity,
    lineage: Lineage,
    *,
    now: int,
    operation="upgrade",
    target=None,
    settings=None,
    ttl=DEFAULT_TTL_SECONDS,
):
    """Read-only: decide, bind and issue. Returns (decision, token or None for NOOP)."""
    decision = decide_migration(
        facts, identity, lineage, operation=operation, target=target, settings=settings
    )
    if not decision.changes_schema:
        return decision, None
    digest = binding(facts, identity, decision, lineage)
    return decision, issue(digest, decision, identity, now=now, ttl=ttl)


def revalidate_and_consume(
    token,
    facts: Facts,
    identity,
    lineage: Lineage,
    *,
    now: int,
    ledger: Ledger,
    operation="upgrade",
    target=None,
    settings=None,
) -> tuple[Decision, Authorization]:
    """Recompute everything from *current* facts; any change since ``plan`` refuses."""
    decision = decide_migration(
        facts, identity, lineage, operation=operation, target=target, settings=settings
    )
    if not decision.changes_schema:
        raise GuardRefused("NXG-A02", env=identity.environment)
    digest = binding(facts, identity, decision, lineage)
    authorization = verify(token, expected_digest=digest, identity=identity, now=now, ledger=ledger)
    if authorization.operation != decision.mode or authorization.target != decision.target:
        raise GuardRefused("NXG-A02", env=identity.environment)
    return decision, authorization
