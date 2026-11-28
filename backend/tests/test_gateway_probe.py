"""Docker liveness succeeds only on the unsigned gateway response from container loopback."""

from http.client import HTTPConnection, RemoteDisconnected
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import gateway, gateway_probe, main

REFUSAL = b'{"detail":"Authentication required."}'


@pytest.fixture
def serve_response(monkeypatch):
    def run(status, cache_control, body, *, declared_length=None):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, {name.lower() for name in self.headers}))
                self.send_response(status)
                if cache_control is not None:
                    self.send_header("Cache-Control", cache_control)
                if status == 302:
                    self.send_header("Location", "/elsewhere")
                self.send_header("Content-Type", "application/json")
                length = len(body) if declared_length is None else declared_length
                self.send_header("Content-Length", str(length))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:

            def connect(host, port, timeout):
                assert (host, port, timeout) == ("127.0.0.1", 8000, 3)
                return HTTPConnection(*server.server_address, timeout=timeout)

            monkeypatch.setattr(gateway_probe, "HTTPConnection", connect)
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                result = gateway_probe.main()
            finally:
                server.shutdown()
                thread.join()

        assert len(requests) == 1
        path, headers = requests[0]
        assert path == "/api/live"
        assert headers.isdisjoint({"authorization", "cookie", "x-nextup-gateway-assertion"})
        return result

    return run


def test_unsigned_response_from_gateway_is_live(serve_response):
    policy = Mock(spec=gateway.GatewayPolicy)
    client = TestClient(gateway.GatewayAssertionMiddleware(main.app, policy))
    response = client.get("/api/live")
    assert (
        serve_response(response.status_code, response.headers["cache-control"], response.content)
        == 0
    )
    policy.verified_subject.assert_not_called()


def test_maximum_response_size_is_inclusive(serve_response):
    assert serve_response(401, "no-store", REFUSAL.ljust(256)) == 0


def test_truncated_refusal_fails(serve_response):
    assert serve_response(401, "no-store", REFUSAL, declared_length=len(REFUSAL) + 1) == 1


@pytest.mark.parametrize(
    ("status", "cache_control", "body"),
    [
        (200, None, b'{"status":"up"}'),
        (302, "no-store", REFUSAL),
        (403, "no-store", REFUSAL),
        (503, "no-store", REFUSAL),
        (401, None, REFUSAL),
        (401, "public", REFUSAL),
        (401, "no-store", b'{"detail":"synthetic-sensitive-value"}'),
        (401, "no-store", b'{"detail":"Authentication required.","extra":true}'),
        (401, "no-store", b"invalid JSON"),
        (401, "no-store", REFUSAL.ljust(257)),
    ],
)
def test_other_responses_fail(serve_response, capsys, status, cache_control, body):
    assert serve_response(status, cache_control, body) == 1
    output = capsys.readouterr()
    assert "synthetic-sensitive-value" not in output.out + output.err


@pytest.mark.parametrize("error", [ConnectionRefusedError, TimeoutError, RemoteDisconnected])
def test_transport_failure_is_quiet(monkeypatch, capsys, error):
    def unavailable(self):
        raise error("synthetic-sensitive-value")

    monkeypatch.setattr(HTTPConnection, "connect", unavailable)
    assert gateway_probe.main() == 1
    output = capsys.readouterr()
    assert "synthetic-sensitive-value" not in output.out + output.err
