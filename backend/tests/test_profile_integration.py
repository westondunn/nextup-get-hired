"""Exercise profile persistence in an isolated PostgreSQL schema, never user data."""

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import integration_db
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires running PostgreSQL"
)
EXAMPLE = json.loads((Path(__file__).parent / "fixtures/profile.synthetic.json").read_text())


@pytest.fixture
def profile_database():
    # The owner creates the schema and INITs it through the guard (plan + apply);
    # the code under test gets a runtime (app-role) engine with the runtime guard installed.
    schema = integration_db.create_schema()
    engine = None
    try:
        integration_db.migrate_schema(schema)
        engine = integration_db.runtime_engine(schema)
        yield engine, schema
    finally:
        if engine is not None:
            engine.dispose()
        integration_db.drop_schema(schema)


@pytest.fixture
def profile_client(profile_database, monkeypatch):
    def sessions():
        with Session(profile_database[0]) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    # The FastAPI lifespan runs the guard against app.db.get_engine().
    monkeypatch.setattr("app.db.get_engine", lambda: profile_database[0])
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_import_update_and_retrieve(profile_client, profile_database):
    assert profile_client.get("/api/profile").status_code == 404
    response = profile_client.put("/api/profile", json=EXAMPLE)
    assert response.status_code == 200
    assert response.json() == EXAMPLE
    updated = {**EXAMPLE, "location": "Another Example City", "skills": [" SQL ", "sql"]}
    assert profile_client.put("/api/profile", json=updated).status_code == 200
    expected = {**updated, "skills": ["SQL"]}
    assert profile_client.get("/api/profile").json() == expected
    with profile_database[0].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM profiles")) == 1


def test_invalid_import_preserves_saved_profile(profile_client):
    assert profile_client.put("/api/profile", json=EXAMPLE).status_code == 200
    response = profile_client.put("/api/profile", json={**EXAMPLE, "work_preferences": ["invalid"]})
    assert response.status_code == 422
    assert profile_client.get("/api/profile").json() == EXAMPLE


@contextmanager
def isolated_api(schema):
    # Bind before spawning to avoid port races. The subprocess serves the real app
    # with only its engine redirected to a test schema. Restarting loses all memory.
    server_code = (
        integration_db.SUBPROCESS_ENGINE
        + """
import uvicorn
from app.main import app
uvicorn.run(app, fd=int(os.environ['NEXTUP_TEST_SOCKET']), log_level='error')
"""
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        environment = integration_db.schema_runtime_environment(
            schema, NEXTUP_TEST_SOCKET=str(listener.fileno())
        )
        process = subprocess.Popen(
            [sys.executable, "-c", server_code],
            env=environment,
            pass_fds=(listener.fileno(),),
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, "Isolated API exited before startup"
                    try:
                        if client.get("/api/live").status_code == 200:
                            break
                    except httpx.TransportError:
                        time.sleep(0.1)
                else:
                    pytest.fail("Isolated API did not start")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_profile_survives_real_api_process_restart(profile_database):
    with isolated_api(profile_database[1]) as first:
        assert first.put("/api/profile", json=EXAMPLE).status_code == 200
    with isolated_api(profile_database[1]) as restarted:
        response = restarted.get("/api/profile")
        assert response.status_code == 200
        assert response.json() == EXAMPLE
