"""The alternate staging API requires gateway identity before serving any HTTP route."""

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import gateway, guard, local_session, main
from app.local_session import SESSION_REQUIRED
from app.request_boundary import CROSS_ORIGIN_REFUSED, HOST_REFUSED
from app.secrets_files import read_secret_file

HEADER = "X-NextUp-Gateway-Assertion"
ISSUER = "https://issuer.example.test"
AUDIENCE = "nextup-test-gateway"
OPERATOR = "synthetic-operator"
LOOPBACK = "http://127.0.0.1:28000"
POLICY_FILE = "/run/secrets/nextup_gateway_policy"
EXTERNAL_HOST = "workspace.example.test"
EXTERNAL_ORIGIN = "https://" + EXTERNAL_HOST


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def policy_text(key):
    pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return json.dumps(
        {"issuer": ISSUER, "audience": AUDIENCE, "subject": OPERATOR, "public_key": pem.decode()}
    )


def issued(key, *, claims=None, missing=None, typ="nextup-gateway+jwt", algorithm="RS256"):
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUDIENCE, "sub": OPERATOR, "iat": now, "exp": now + 60}
    payload.update(claims or {})
    if missing:
        del payload[missing]
    return jwt.encode(payload, key, algorithm=algorithm, headers={"typ": typ})


def set_identity(monkeypatch, environment, role):
    identity = SimpleNamespace(environment=environment, role=role)
    monkeypatch.setattr(gateway, "get_settings", lambda: SimpleNamespace(identity=identity))


@pytest.fixture
def private_app(monkeypatch, policy_text):
    set_identity(monkeypatch, "staging", "runtime")
    reader = Mock(return_value=policy_text)
    monkeypatch.setattr(gateway, "read_secret_file", reader)
    application = gateway.create_app()
    reader.assert_called_once_with(
        POLICY_FILE, variable="NEXTUP_GATEWAY_POLICY", allowed_owners=(0,)
    )
    return application


@pytest.fixture
def client(private_app):
    return TestClient(private_app, base_url=LOOPBACK)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/live"),
        ("GET", "/api/health"),
        ("GET", "/api/google/connection"),
        ("POST", "/api/diagnostics"),
        ("GET", "/openapi.json"),
    ],
)
def test_anonymous_requests_never_reach_routes(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_real_app_health_is_available_only_after_authorization(client, key, monkeypatch):
    probe = Mock(return_value={"status": "ok", "checks": {"database": "up"}})
    monkeypatch.setattr(main, "probe_health", probe)
    assert client.get("/api/health").status_code == 401
    probe.assert_not_called()
    response = client.get("/api/health", headers={HEADER: issued(key)})
    assert response.status_code == 200
    assert response.json() == probe.return_value
    probe.assert_called_once_with()


def test_ordinary_loopback_entrypoint_remains_usable():
    response = TestClient(main.app, base_url=LOOPBACK).get("/api/live")
    assert response.status_code == 200 and response.json() == {"status": "up"}


def test_verified_identity_preserves_host_origin_and_local_session_checks(client, key):
    headers = {HEADER: issued(key)}
    response = client.get("/api/live", headers={**headers, "Host": "staging.example.test"})
    assert response.status_code == 400 and response.json() == {"detail": HOST_REFUSED}

    response = client.post(
        "/api/diagnostics", headers={**headers, "Origin": "https://other.example.test"}
    )
    assert response.status_code == 403 and response.json() == {"detail": CROSS_ORIGIN_REFUSED}

    response = client.get("/api/google/connection", headers=headers)
    assert response.status_code == 401 and response.json() == {"detail": SESSION_REQUIRED}


@pytest.mark.parametrize("missing", ["iss", "aud", "sub", "iat", "exp"])
def test_required_claims(client, key, missing):
    response = client.get("/api/live", headers={HEADER: issued(key, missing=missing)})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.example.test"},
        {"aud": "other-service"},
        {"aud": [AUDIENCE, "other-service"]},
        {"exp": 1},
    ],
)
def test_wrong_trust_context_and_expiry_are_refused(client, key, claims):
    assert client.get("/api/live", headers={HEADER: issued(key, claims=claims)}).status_code == 401


@pytest.mark.parametrize(
    ("iat_offset", "exp_offset", "nbf_offset", "expected"),
    [
        (-160, -100, None, 401),
        (30, 60, None, 401),
        (0, 60, 30, 401),
        (0, 121, None, 401),
        (0, 60.5, None, 401),
        (0, 120, None, 200),
    ],
)
def test_short_lifetime_and_dates(client, key, iat_offset, exp_offset, nbf_offset, expected):
    now = int(time.time())
    claims = {"iat": now + iat_offset, "exp": now + exp_offset}
    if nbf_offset is not None:
        claims["nbf"] = now + nbf_offset
    response = client.get("/api/live", headers={HEADER: issued(key, claims=claims)})
    assert response.status_code == expected


@pytest.mark.parametrize(("typ", "algorithm"), [("JWT", "RS256"), ("nextup-gateway+jwt", "PS256")])
def test_only_gateway_assertion_type_and_algorithm_accepted(client, key, typ, algorithm):
    token = issued(key, typ=typ, algorithm=algorithm)
    assert client.get("/api/live", headers={HEADER: token}).status_code == 401


def test_oversized_signed_assertion_refused(client, key):
    token = issued(key, claims={"padding": "p" * 6500})
    assert len(token) > 8192
    assert client.get("/api/live", headers={HEADER: token}).status_code == 401


def test_valid_wrong_operator_distinguished_from_untrusted_assertion(client, key, caplog):
    subject = "synthetic-other-operator"
    trusted = issued(key, claims={"sub": subject})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    untrusted = issued(other_key, claims={"sub": subject})
    for token, expected in [(trusted, 403), (untrusted, 401)]:
        response = client.get("/api/live", headers={HEADER: token})
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
        assert subject not in response.text + caplog.text
        assert token not in response.text + caplog.text


def test_duplicate_assertion_headers_rejected(client, key):
    token = issued(key)
    response = client.get("/api/live", headers=[(HEADER, token), (HEADER, token)])
    assert response.status_code == 401


def test_assertion_is_consumed_and_websockets_closed(key, policy_text):
    inner = FastAPI()

    @inner.get("/")
    def received(request: Request):
        return {"has_assertion": HEADER.lower() in request.headers}

    @inner.websocket("/socket")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.close()

    wrapped = gateway.GatewayAssertionMiddleware(
        inner, gateway.GatewayPolicy.from_json(policy_text)
    )
    client = TestClient(wrapped)
    headers = {HEADER: issued(key)}
    response = client.get("/", headers=headers)
    assert response.status_code == 200 and response.json() == {"has_assertion": False}
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/socket", headers=headers),
    ):
        pytest.fail("WebSocket connected")
    assert closed.value.code == 1008


def test_lifespan_keeps_real_database_startup_guard(private_app, monkeypatch):
    startup = Mock()
    monkeypatch.setattr(guard, "check_service_startup", startup)
    with TestClient(private_app):
        startup.assert_called_once_with()


@pytest.mark.parametrize(
    ("environment", "role"), [("dev", "runtime"), ("ci", "runtime"), ("staging", "migrator")]
)
def test_factory_requires_staging_runtime(monkeypatch, policy_text, environment, role):
    set_identity(monkeypatch, environment, role)
    monkeypatch.setattr(gateway, "read_secret_file", Mock(return_value=policy_text))
    with pytest.raises(RuntimeError):
        gateway.create_app()


@pytest.mark.parametrize("field", ["issuer", "audience", "subject", "public_key"])
def test_invalid_policy_prevents_startup_without_disclosing_values(monkeypatch, policy_text, field):
    set_identity(monkeypatch, "staging", "runtime")
    config = json.loads(policy_text)
    config[field] = "synthetic-invalid-public-key" if field == "public_key" else ""
    monkeypatch.setattr(gateway, "read_secret_file", Mock(return_value=json.dumps(config)))
    with pytest.raises(RuntimeError) as error:
        gateway.create_app()
    assert OPERATOR not in str(error.value)
    assert "synthetic-invalid-public-key" not in str(error.value)


def test_missing_policy_file_aborts_startup_without_disclosing_path(monkeypatch):
    set_identity(monkeypatch, "staging", "runtime")
    reader = Mock(side_effect=FileNotFoundError("/private-directory-for-test"))
    monkeypatch.setattr(gateway, "read_secret_file", reader)
    with pytest.raises(RuntimeError) as error:
        gateway.create_app()
    assert "/private-directory-for-test" not in str(error.value)


@pytest.mark.parametrize(
    "case",
    [
        "readable",
        "wrong-owner",
        "world-readable",
        "group-writable",
        "directory",
        "symlink",
        "multiline",
    ],
)
def test_factory_reads_only_a_protected_single_line_policy(
    monkeypatch, tmp_path, policy_text, key, case
):
    set_identity(monkeypatch, "staging", "runtime")
    entry = tmp_path / "policy"
    content = json.dumps(json.loads(policy_text), indent=2) if case == "multiline" else policy_text
    entry.write_text(content + "\n", encoding="utf-8")
    mode = {"world-readable": 0o444, "group-writable": 0o460}.get(case, 0o440)
    entry.chmod(mode)
    if case == "directory":
        entry = tmp_path
    elif case == "symlink":
        link = tmp_path / "link"
        link.symlink_to(entry)
        entry = link

    # Map mount and trusted UID to the test sandbox so unprivileged CI exercises the real reader.
    trusted_uid = os.geteuid() + 1 if case == "wrong-owner" else os.geteuid()

    def read_test_mount(path, *, variable, allowed_owners):
        assert (path, variable, allowed_owners) == (POLICY_FILE, "NEXTUP_GATEWAY_POLICY", (0,))
        return read_secret_file(
            str(entry), variable=variable, roots=(str(tmp_path),), allowed_owners=(trusted_uid,)
        )

    monkeypatch.setattr(gateway, "read_secret_file", read_test_mount)
    if case == "readable":
        client = TestClient(gateway.create_app(), base_url=LOOPBACK)
        assert client.get("/api/live", headers={HEADER: issued(key)}).status_code == 200
    else:
        with pytest.raises(RuntimeError) as error:
            gateway.create_app()
        assert str(error.value) == "Cannot read the staging gateway policy."


@pytest.fixture
def origin_app(monkeypatch, policy_text):
    set_identity(monkeypatch, "staging", "runtime")

    def create(origin):
        policy = json.loads(policy_text)
        policy["external_origin"] = origin
        monkeypatch.setattr(gateway, "read_secret_file", Mock(return_value=json.dumps(policy)))
        return gateway.create_app()

    return create


@pytest.fixture
def external_client(origin_app, key):
    # The upstream hop can be plain HTTP. The gateway must preserve the browser's Host.
    return TestClient(
        origin_app(EXTERNAL_ORIGIN),
        base_url="http://" + EXTERNAL_HOST,
        headers={HEADER: issued(key)},
    )


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        42,
        "http://workspace.example.test",
        "https://*.example.test",
        "https://127.0.0.1",
        "https://[::1]",
        "https://example.0x7f",
        "https://bad_label.example.test",
        "https://operator@workspace.example.test",
        EXTERNAL_ORIGIN + "/",
        EXTERNAL_ORIGIN + "/path",
        EXTERNAL_ORIGIN + "?query",
        EXTERNAL_ORIGIN + "#fragment",
        EXTERNAL_ORIGIN + ":0",
        EXTERNAL_ORIGIN + ":0443",
        EXTERNAL_ORIGIN + ":65536",
    ],
)
def test_invalid_external_origin_fails_startup(origin_app, origin):
    with pytest.raises(RuntimeError, match=r"^Invalid staging gateway policy\.$"):
        origin_app(origin)


def test_duplicate_external_origin_fields_are_ambiguous(policy_text, monkeypatch):
    policy = policy_text[:-1] + (
        ',"external_origin":"https://first.example.test",'
        '"external_origin":"https://second.example.test"}'
    )
    set_identity(monkeypatch, "staging", "runtime")
    monkeypatch.setattr(gateway, "read_secret_file", Mock(return_value=policy))
    with pytest.raises(RuntimeError, match=r"^Invalid staging gateway policy\.$"):
        gateway.create_app()


@pytest.mark.parametrize(
    ("configured", "host", "origin"),
    [
        (EXTERNAL_ORIGIN, EXTERNAL_HOST, EXTERNAL_ORIGIN + ":443"),
        (EXTERNAL_ORIGIN + ":443", EXTERNAL_HOST + ":443", EXTERNAL_ORIGIN),
        (EXTERNAL_ORIGIN + ":8443", EXTERNAL_HOST + ":8443", EXTERNAL_ORIGIN + ":8443"),
        (EXTERNAL_ORIGIN, EXTERNAL_HOST.upper(), EXTERNAL_ORIGIN.upper()),
    ],
)
def test_matching_effective_https_origin_reaches_handler(
    origin_app, key, configured, host, origin, monkeypatch
):
    store = Mock(spec=local_session.SessionStore)
    monkeypatch.setitem(main.app.dependency_overrides, local_session.get_store, lambda: store)
    client = TestClient(origin_app(configured))
    response = client.delete(
        "/api/session",
        headers={
            HEADER: issued(key),
            "Host": host,
            "Origin": origin,
            "Sec-Fetch-Site": "same-origin",
            "Cookie": "nextup_session=synthetic-session",
        },
    )
    assert response.status_code == 204
    store.end.assert_called_once_with("synthetic-session")


@pytest.mark.parametrize(
    "hosts",
    [
        ["127.0.0.1:28000"],
        [EXTERNAL_HOST + ":8443"],
        ["another.example.test"],
        [EXTERNAL_HOST, EXTERNAL_HOST],
        [EXTERNAL_HOST + ", " + EXTERNAL_HOST],
    ],
)
def test_gateway_requires_one_matching_host_even_with_forwarding_headers(external_client, hosts):
    headers = [("Host", host) for host in hosts]
    headers += [
        ("Forwarded", f"host={EXTERNAL_HOST};proto=https"),
        ("X-Forwarded-Host", EXTERNAL_HOST),
        ("X-Forwarded-Proto", "https"),
    ]
    response = external_client.get("/api/live", headers=headers)
    assert response.status_code == 400 and response.json() == {"detail": HOST_REFUSED}


@pytest.mark.parametrize(
    "browser_headers",
    [
        [],
        [("Origin", "http://" + EXTERNAL_HOST)],
        [("Origin", "https://other.example.test")],
        [("Origin", EXTERNAL_ORIGIN + ":8443")],
        [("Origin", "null")],
        [("Origin", EXTERNAL_ORIGIN + "/path")],
        [("Origin", EXTERNAL_ORIGIN), ("Origin", EXTERNAL_ORIGIN)],
        [("Origin", EXTERNAL_ORIGIN), ("Sec-Fetch-Site", "cross-site")],
        [("Origin", EXTERNAL_ORIGIN), ("Sec-Fetch-Site", "same-site")],
        [("Origin", EXTERNAL_ORIGIN), ("Sec-Fetch-Site", "none"), ("Sec-Fetch-Site", "none")],
        [("X-Forwarded-Host", EXTERNAL_HOST), ("X-Forwarded-Proto", "https")],
    ],
)
def test_gateway_refuses_invalid_write_before_session_change(
    external_client, browser_headers, monkeypatch
):
    store = Mock(spec=local_session.SessionStore)
    monkeypatch.setitem(main.app.dependency_overrides, local_session.get_store, lambda: store)
    response = external_client.delete(
        "/api/session", headers=[*browser_headers, ("Cookie", "nextup_session=synthetic-session")]
    )
    assert response.status_code == 403 and response.json() == {"detail": CROSS_ORIGIN_REFUSED}
    store.end.assert_not_called()


def test_origin_policy_is_scoped_to_one_verified_gateway(external_client, client, key):
    host = {"Host": EXTERNAL_HOST}
    assert external_client.get("/api/live", headers=host).json() == {"status": "up"}
    guarded = external_client.get("/api/google/connection", headers=host)
    assert guarded.status_code == 401 and guarded.json() == {"detail": SESSION_REQUIRED}
    for other in [client, TestClient(main.app)]:
        response = other.get("/api/live", headers={**host, HEADER: issued(key)})
        assert response.status_code == 400 and response.json() == {"detail": HOST_REFUSED}


def test_router_redirect_preserves_verified_https_origin(external_client):
    response = external_client.get("/api/live/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == EXTERNAL_ORIGIN + "/api/live"


def test_unsigned_request_is_refused_before_host_or_origin_checks(origin_app):
    client = TestClient(origin_app(EXTERNAL_ORIGIN), base_url=LOOPBACK)
    for method, path in [("GET", "/api/live"), ("POST", "/api/diagnostics")]:
        response = client.request(method, path)
        assert response.status_code == 401
        assert response.json() == {"detail": "Authentication required."}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_writes_require_an_origin(external_client, method):
    response = external_client.request(method, "/api/live")
    assert response.status_code == 403 and response.json() == {"detail": CROSS_ORIGIN_REFUSED}
