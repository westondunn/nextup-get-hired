"""Exercise real service outages inside a disposable CI project only.

Stopping and starting services is destructive to whatever stack receives the commands,
so this module has no default target. scripts/verify_ci.py injects its own compose and
request functions together with its random `nextup-ci-<12 hex>` project name; anything
else is refused before a single command is issued.
"""

import re
import sys
import time

CI_PROJECT = re.compile(r"^nextup-ci-[0-9a-f]{12}$")
REFUSAL_EXIT = 3


class UnsafeTarget(RuntimeError):
    """The outage exercise was not pointed at a disposable CI project."""


def require_disposable_target(compose_fn, request_fn, project):
    if compose_fn is None or request_fn is None:
        raise UnsafeTarget(
            "Outage checks need the compose and request functions of a disposable CI "
            "stack; run them through scripts/verify_ci.py."
        )
    if not isinstance(project, str) or not CI_PROJECT.fullmatch(project):
        raise UnsafeTarget("Outage checks run only in a nextup-ci-<12 hex> project.")


def wait_for(predicate, description, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise AssertionError(f"Timed out: {description}")


def main(compose_fn=None, request_fn=None, project=None):
    require_disposable_target(compose_fn, request_fn, project)
    compose, request = compose_fn, request_fn
    wait_for(lambda: request("/api/health")[0] == 200, "initial health")
    compose("stop", "worker")
    try:
        code, health = request("/api/health")
        assert code == 503 and health["checks"]["worker"] == "down"
        code, queued = request("/api/diagnostics", "POST")
        assert code == 202
        assert request(f"/api/diagnostics/{queued['id']}")[1]["status"] == "queued"
        print("PASS: stopped worker is unavailable; diagnostic remains queued", flush=True)
    finally:
        compose("start", "worker")
    wait_for(
        lambda: request(f"/api/diagnostics/{queued['id']}")[1]["status"] == "succeeded",
        "queued diagnostic after worker recovery",
    )
    print(
        "PASS: recovered worker consumed and persisted the queued diagnostic",
        flush=True,
    )

    compose("stop", "redis")
    try:
        code, health = request("/api/health")
        assert code == 503 and health["checks"]["broker"] == "down"
        code, failed = request("/api/diagnostics", "POST")
        assert code == 503
        result = request(f"/api/diagnostics/{failed['detail']['id']}")[1]
        assert result["status"] == "publish_failed"
        assert request("/api/job-fetches", "POST", {"source": "adzuna"})[0] == 503
        failed_fetch = request("/api/job-fetches/latest?source=adzuna")[1]
        assert failed_fetch["status"] == "publish_failed"
        assert request("/api/job-fetches", "POST", {"source": "adzuna"})[0] == 409
        print(
            "PASS: stopped broker produces 503 and persisted publication failure",
            flush=True,
        )
    finally:
        compose("start", "redis")
    wait_for(lambda: request("/api/health")[0] == 200, "broker and worker recovery")
    wait_for(
        lambda: (
            request(f"/api/diagnostics/{failed['detail']['id']}")[1]["status"] == "succeeded"
            and request(f"/api/job-fetches/{failed_fetch['id']}")[1]["status"] == "succeeded"
        ),
        "scheduled recovery of unpublished diagnostic and adzuna fetch",
        timeout=120,
    )
    recovered = request(f"/api/job-fetches/{failed_fetch['id']}")[1]
    assert recovered["delivery_attempts"] >= 2 and recovered["stored_count"] == 2
    print(
        "PASS: existing Beat schedule recovered both original task IDs without resubmission",
        flush=True,
    )

    compose("stop", "postgres")
    try:
        code, health = request("/api/health")
        assert code == 503 and health["checks"]["database"] == "down"
        assert request("/api/diagnostics", "POST")[0] == 503
        for path in (
            "/api/profile",
            "/api/career",
            "/api/jobs?source=adzuna",
            "/api/saved-searches",
            "/api/alerts",
        ):
            status, payload = request(path)
            assert status == 503 and payload == {"detail": "Database unavailable"}, path
        print(
            "PASS: stopped database rejects diagnostics, profile, listings, "
            "searches, and inbox reads",
            flush=True,
        )
    finally:
        compose("start", "postgres")
    wait_for(lambda: request("/api/health")[0] == 200, "database recovery")
    print("PASS: all services recovered", flush=True)


if __name__ == "__main__":
    print(
        "Refused: outage checks have no standalone target. They run only inside "
        "scripts/verify_ci.py's disposable project, which needs its own explicit opt-in.",
        file=sys.stderr,
    )
    sys.exit(REFUSAL_EXIT)
