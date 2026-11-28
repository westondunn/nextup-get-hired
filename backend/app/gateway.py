"""Alternate staging ASGI factory for an upstream gateway that signs operator assertions."""

import json
import re
from dataclasses import dataclass

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings
from app.gateway_origin import GatewayOrigin
from app.guard.errors import SecretFileError
from app.request_boundary import GATEWAY_ORIGIN_SCOPE_KEY
from app.secrets_files import read_secret_file

POLICY_PATH = "/run/secrets/nextup_gateway_policy"
ASSERTION_HEADER = b"x-nextup-gateway-assertion"
TOKEN_TYPE = "nextup-gateway+jwt"
MAX_ASSERTION_BYTES = 8192
MAX_LIFETIME_SECONDS = 120
COMPACT_JWS = re.compile(rb"(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError
    return fields


@dataclass(frozen=True, repr=False)
class GatewayPolicy:
    issuer: str
    audience: str
    subject: str
    public_key: rsa.RSAPublicKey
    external_origin: GatewayOrigin | None = None

    @classmethod
    def from_json(cls, text: str) -> "GatewayPolicy":
        try:
            fields = json.loads(text, object_pairs_hook=_unique_fields)
            required = {"issuer", "audience", "subject", "public_key"}
            if not isinstance(fields, dict) or fields.keys() not in (
                required,
                required | {"external_origin"},
            ):
                raise ValueError
            for name in ("issuer", "audience", "subject"):
                value = fields[name]
                if (
                    not isinstance(value, str)
                    or not value
                    or not value.isprintable()
                    or value != value.strip()
                ):
                    raise ValueError
            pem = fields["public_key"]
            if not isinstance(pem, str) or pem.count("-----BEGIN ") != 1:
                raise ValueError
            key = serialization.load_pem_public_key(pem.encode("ascii"))
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
                raise ValueError
            origin = (
                GatewayOrigin.parse(fields["external_origin"])
                if "external_origin" in fields
                else None
            )
        except (ValueError, TypeError, RecursionError, UnsupportedAlgorithm):
            raise RuntimeError("Invalid staging gateway policy.") from None
        return cls(fields["issuer"], fields["audience"], fields["subject"], key, origin)

    def verified_subject(self, assertion: bytes) -> str | None:
        """Return a subject only after verifying the dedicated token type, key and claims."""
        if len(assertion) > MAX_ASSERTION_BYTES or not COMPACT_JWS.fullmatch(assertion):
            return None
        try:
            verified = jwt.decode_complete(
                assertion,
                self.public_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["iss", "aud", "sub", "iat", "exp"], "strict_aud": True},
            )
            header = verified["header"]
            if header.get("typ") != TOKEN_TYPE or "crit" in header:
                return None
            claims = verified["payload"]
            dates = [claims["iat"], claims["exp"]]
            if "nbf" in claims:
                dates.append(claims["nbf"])
            if any(type(value) is not int for value in dates):
                return None
            if not 0 < claims["exp"] - claims["iat"] <= MAX_LIFETIME_SECONDS:
                return None
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject.strip():
                return None
            return subject
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError, RecursionError):
            return None


class GatewayAssertionMiddleware:
    def __init__(self, app: ASGIApp, policy: GatewayPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            raise RuntimeError("Unsupported gateway protocol.")

        headers = scope["headers"]
        assertions = [value for name, value in headers if name.lower() == ASSERTION_HEADER]
        subject = self.policy.verified_subject(assertions[0]) if len(assertions) == 1 else None
        if subject is None or subject != self.policy.subject:
            response = JSONResponse(
                {"detail": "Authentication required." if subject is None else "Access denied."},
                status_code=401 if subject is None else 403,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        # The wrapped NextUp app still enforces its own Host, Origin and local-session rules.
        filtered_headers = [
            (name.lower(), value) for name, value in headers if name.lower() != ASSERTION_HEADER
        ]
        verified_scope = {**scope, "headers": filtered_headers}
        if self.policy.external_origin is not None:
            verified_scope[GATEWAY_ORIGIN_SCOPE_KEY] = self.policy.external_origin
        await self.app(verified_scope, receive, send)


def create_app() -> ASGIApp:
    """Load the trusted policy once at startup and wrap the real staging runtime application."""
    identity = get_settings().identity
    if identity.environment != "staging" or identity.role != "runtime":
        raise RuntimeError("Gateway authentication requires the staging runtime.")
    try:
        policy_json = read_secret_file(
            POLICY_PATH, variable="NEXTUP_GATEWAY_POLICY", allowed_owners=(0,)
        )
    except (SecretFileError, OSError):
        raise RuntimeError("Cannot read the staging gateway policy.") from None
    policy = GatewayPolicy.from_json(policy_json)

    from app.main import app

    return GatewayAssertionMiddleware(app, policy)
