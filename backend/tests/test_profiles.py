import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app
from app.profiles import ProfileInput

EXAMPLE = json.loads((Path(__file__).parent / "fixtures/profile.synthetic.json").read_text())


def test_normalizes_whitespace_and_duplicates():
    profile = ProfileInput(**{**EXAMPLE, "skills": [" Python ", "python", "SQL"]})
    assert profile.skills == ["Python", "SQL"]


@pytest.mark.parametrize(
    "changes",
    [
        {"skills": []},
        {"skills": [" "]},
        {"skills": [42]},
        {"skills": ["x" * 101]},
        {"skills": ["bad\x00skill"]},
        {"skills": ["Python"] * 51},
        {"target_titles": []},
        {"target_titles": ["x" * 121]},
        {"location": " "},
        {"location": "bad\x00location"},
        {"location": "x" * 161},
        {"work_preferences": []},
        {"work_preferences": ["anywhere"]},
        {"password": "should-not-be-stored"},
    ],
)
def test_rejects_invalid_profiles(changes):
    with pytest.raises(ValidationError):
        ProfileInput(**{**EXAMPLE, **changes})


@pytest.fixture
def database():
    session = MagicMock()
    app.dependency_overrides[get_session] = lambda: session
    yield session
    app.dependency_overrides.clear()


def test_empty_profile_returns_404(database):
    database.get.return_value = None
    assert TestClient(app).get("/api/profile").status_code == 404


def test_invalid_input_never_writes(database):
    response = TestClient(app).put("/api/profile", json={**EXAMPLE, "location": ""})
    assert response.status_code == 422
    database.scalar.assert_not_called()
    database.commit.assert_not_called()


def test_database_failure_does_not_report_saved(database):
    database.scalar.return_value = ProfileInput(**EXAMPLE)
    database.commit.side_effect = OperationalError("commit", {}, Exception("offline"))
    response = TestClient(app).put("/api/profile", json=EXAMPLE)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
