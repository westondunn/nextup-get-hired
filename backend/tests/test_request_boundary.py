"""Host allowlist and cross-origin refusal (docs/decisions/0001-local-session-boundary.md)."""

import logging

import pytest
import route_helpers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import request_boundary
from app.main import app as real_app
from app.request_boundary import (
    CROSS_ORIGIN_REFUSED,
    HOST_REFUSED,
    RequestBoundaryMiddleware,
    allowed_hosts,
    host_name,
)

METHODS = ("POST", "PUT", "PATCH", "DELETE")


@pytest.fixture
def client(monkeypatch):
    """A minimal app behind the boundary, in the dev environment, with no test host."""
    monkeypatch.setattr(request_boundary, "TEST_HOSTS", frozenset())
    monkeypatch.setattr(request_boundary, "_environment", lambda: "dev")
    inner = FastAPI()

    @inner.api_route("/thing", methods=["GET", *METHODS])
    def thing():
        return {"reached": True}

    inner.add_middleware(RequestBoundaryMiddleware)
    return TestClient(inner, base_url="http://127.0.0.1:18000")


def call(client, method="GET", host="127.0.0.1:18000", **headers):
    names = {"origin": "Origin", "site": "Sec-Fetch-Site"}
    sent = {"Host": host, **{names[k]: v for k, v in headers.items()}}
    return client.request(method, "/thing", headers=sent)


# ---------- layer 1: host allowlist ----------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.1:18000",
        "127.0.0.1:15173",
        "localhost",
        "localhost:15173",
        "LOCALHOST:15173",
    ],
)
def test_local_hosts_are_accepted_on_any_port(client, host):
    response = call(client, host=host)
    assert response.status_code == 200 and response.json() == {"reached": True}


@pytest.mark.parametrize(
    "host",
    [
        "rebind.example",
        "rebind.example:18000",
        "127.0.0.1.rebind.example",
        "localhost.rebind.example:15173",
        "0.0.0.0:18000",
        "192.168.1.20:18000",
        "[::1]:18000",
        "localhost:",
        "localhost:port",
        "localhost:80:80",
        ":18000",
        "",
        "api:8000",
        "frontend:5173",
        "testserver",
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_other_hosts_are_refused_for_every_method(client, host, method):
    response = call(client, method, host=host)
    assert response.status_code == 400
    assert response.json() == {"detail": HOST_REFUSED}


@pytest.mark.parametrize("environment", ["ci", "test"])
@pytest.mark.parametrize("host", ["api:8000", "frontend:5173", "127.0.0.1:8000"])
def test_stack_service_names_are_accepted_in_the_ci_stack(client, monkeypatch, environment, host):
    monkeypatch.setattr(request_boundary, "_environment", lambda: environment)
    assert call(client, host=host).status_code == 200


@pytest.mark.parametrize("environment", ["dev", "staging"])
def test_stack_service_names_are_refused_outside_the_ci_stack(client, monkeypatch, environment):
    monkeypatch.setattr(request_boundary, "_environment", lambda: environment)
    assert call(client, host="api:8000").status_code == 400
    assert call(client, host="frontend:5173").status_code == 400


def test_allowed_hosts_per_environment(monkeypatch):
    monkeypatch.setattr(request_boundary, "TEST_HOSTS", frozenset())
    local = {"localhost", "127.0.0.1"}
    assert allowed_hosts("dev") == local
    assert allowed_hosts("staging") == local
    assert allowed_hosts("ci") == local | {"api", "frontend"}
    assert allowed_hosts("test") == local | {"api", "frontend"}


def test_host_name_parsing():
    assert host_name("localhost") == "localhost"
    assert host_name("localhost:15173") == "localhost"
    assert host_name("[::1]:8000") is None
    assert host_name("localhost:١٢") is None  # non-ASCII digits are not a port


# ---------- layer 2: cross-origin refusal ----------


@pytest.mark.parametrize("method", METHODS)
def test_requests_without_browser_headers_pass(client, method):
    assert call(client, method).status_code == 200


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("site", ["same-origin", "none", "Same-Origin"])
def test_same_origin_fetch_metadata_passes(client, method, site):
    assert call(client, method, site=site).status_code == 200


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("site", ["cross-site", "same-site", "unexpected", ""])
def test_other_fetch_metadata_is_refused(client, method, site):
    response = call(client, method, site=site)
    assert response.status_code == 403
    assert response.json() == {"detail": CROSS_ORIGIN_REFUSED}


@pytest.mark.parametrize(
    "host,origin",
    [
        ("127.0.0.1:15173", "http://127.0.0.1:15173"),
        ("localhost:15173", "http://localhost:15173"),
        ("localhost:15173", "HTTP://LOCALHOST:15173"),
        ("localhost", "http://localhost"),
    ],
)
def test_origin_matching_the_host_passes(client, host, origin):
    assert call(client, "POST", host=host, origin=origin, site="same-origin").status_code == 200
    assert call(client, "POST", host=host, origin=origin).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://other.example",
        "http://127.0.0.1:3000",  # another local port is another origin
        "http://localhost:15173",  # another name for the same address
        "http://127.0.0.1",
        "null",
        "",
        "127.0.0.1:15173",
    ],
)
def test_origin_differing_from_the_host_is_refused(client, origin):
    response = call(client, "POST", host="127.0.0.1:15173", origin=origin)
    assert response.status_code == 403
    assert response.json() == {"detail": CROSS_ORIGIN_REFUSED}


def test_mismatched_origin_is_refused_even_with_same_origin_fetch_metadata(client):
    response = call(client, "POST", host="127.0.0.1:15173", origin="http://x.example", site="none")
    assert response.status_code == 403


def test_matching_origin_does_not_excuse_cross_site_fetch_metadata(client):
    response = call(
        client, "POST", host="127.0.0.1:15173", origin="http://127.0.0.1:15173", site="cross-site"
    )
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reads_are_not_subject_to_the_cross_origin_check(client, method):
    response = call(client, method, origin="http://other.example", site="cross-site")
    assert response.status_code != 403


def test_host_is_checked_before_origin(client):
    response = call(client, "POST", host="rebind.example", origin="http://rebind.example")
    assert response.status_code == 400


# ---------- value-free refusals ----------


def test_refusals_never_repeat_header_values(client, caplog):
    caplog.set_level(logging.DEBUG)
    bad_host = call(client, host="leak-host.example")
    bad_origin = call(client, "POST", origin="http://leak-origin.example", site="leak-site")
    text = bad_host.text + bad_origin.text + caplog.text
    assert bad_host.status_code == 400 and bad_origin.status_code == 403
    assert "leak-" not in text
    assert "host not allowed" in caplog.text and "cross-origin" in caplog.text


# ---------- the real application ----------


def test_the_application_is_behind_the_boundary(monkeypatch):
    monkeypatch.setattr(request_boundary, "TEST_HOSTS", frozenset())
    monkeypatch.setattr(request_boundary, "_environment", lambda: "dev")
    client = TestClient(real_app, base_url="http://127.0.0.1:18000")
    assert client.get("/api/live").json() == {"status": "up"}
    assert client.get("/api/live", headers={"Host": "rebind.example"}).status_code == 400
    assert client.get("/api/live", headers={"Host": "testserver"}).status_code == 400
    refused = client.post("/api/diagnostics", headers={"Sec-Fetch-Site": "cross-site"})
    assert refused.status_code == 403 and refused.json() == {"detail": CROSS_ORIGIN_REFUSED}


def test_environment_comes_from_the_deployment_identity():
    assert request_boundary._environment() == "test"


def test_every_route_method_is_a_read_or_covered_by_the_cross_origin_check():
    """A route added with an unlisted method would bypass layer 2; fail here instead."""
    covered = request_boundary.STATE_CHANGING_METHODS | {"GET", "HEAD", "OPTIONS"}
    routes = route_helpers.api_routes(real_app)
    assert len(routes) > 50  # the walk reached the feature routers
    for route in routes:
        assert set(getattr(route, "methods", None) or ()) <= covered, route.path
