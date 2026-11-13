"""Rating jobs through the API on an isolated PostgreSQL schema; synthetic data only."""

import os
from types import SimpleNamespace

import pytest
from test_profile_integration import EXAMPLE
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)


def add_reference(client, title, company):
    response = client.post(
        "/api/job-references",
        json={
            "title": title,
            "company": company,
            "location": "US Remote",
            "description": "Lead Python test automation for a synthetic product.",
            "url": f"https://example.invalid/{company}/{title.replace(' ', '-')}",
        },
    )
    assert response.status_code == 201
    return response.json()


def board(client, **params):
    page = client.get("/api/jobs", params={"source": "reference", "limit": 50, **params}).json()
    return {item["company"]: item for item in page["items"]}


def ratings_part(item):
    return next(
        (part for part in item["score_breakdown"]["components"] if part["key"] == "ratings"),
        None,
    )


def test_ratings_reorder_explain_hide_and_clear(profile_client):
    client = profile_client
    assert client.put("/api/profile", json=EXAMPLE).status_code == 200
    liked = add_reference(client, "Director of Quality Engineering", "Acme")
    add_reference(client, "Director of Quality Engineering Platform", "Globex")
    passed = add_reference(client, "Payroll Manager", "Initech")

    before = board(client)
    assert {item["rating"] for item in before.values()} == {None}
    assert ratings_part(before["Globex"]) is None, "no component until something is rated"

    for reference, rating in ((liked, 1), (passed, -1)):
        saved = client.put("/api/job-ratings", json={**reference, "rating": rating})
        assert saved.status_code == 200 and saved.json()["rating"] == rating

    after = board(client)
    assert after["Acme"]["rating"] == 1 and after["Initech"]["rating"] == -1
    assert after["Globex"]["rating"] is None
    similar = ratings_part(after["Globex"])
    assert similar["points"] > 0
    assert similar["evidence"][0].startswith(
        "More like this: Director of Quality Engineering at Acme"
    )
    assert after["Globex"]["score"] > before["Globex"]["score"], "similar jobs move up"
    assert ratings_part(after["Initech"])["points"] == -15
    assert after["Initech"]["score"] == max(0, before["Initech"]["score"] - 15)

    assert "Initech" not in board(client, hide_passed="true"), "passed jobs can be hidden"
    by_score = list(board(client, sort="score"))
    assert by_score.index("Globex") < by_score.index("Initech")

    listed = client.get("/api/job-ratings").json()
    assert {(row["company"], row["rating"]) for row in listed} == {("Acme", 1), ("Initech", -1)}

    # Rating again replaces; 0 clears; a stored rating can be cleared by its key.
    assert client.put("/api/job-ratings", json={**liked, "rating": -1}).json()["rating"] == -1
    assert client.put("/api/job-ratings", json={**liked, "rating": 0}).json()["rating"] == 0
    key = next(row["job_key"] for row in listed if row["company"] == "Initech")
    assert client.delete(f"/api/job-ratings/{key}").status_code == 204
    assert client.delete(f"/api/job-ratings/{key}").status_code == 404
    assert client.get("/api/job-ratings").json() == []
    assert ratings_part(board(client)["Globex"]) is None
    assert (
        client.put(
            "/api/job-ratings", json={"source": "reference", "external_id": "nope", "rating": 1}
        ).status_code
        == 404
    )


def test_a_rating_changes_whether_a_discovered_job_clears_the_minimum():
    from app import scoring
    from app.discovery import matches_profile
    from app.relevance import MatchPreferences

    profile = SimpleNamespace(**{**EXAMPLE, "location": "Springfield"})
    candidate = SimpleNamespace(
        title="Director of Quality Engineering",
        company="Globex",
        location="US Remote",
        description="Quality engineering leadership.",
        posted_at=scoring.datetime(2026, 11, 1, tzinfo=scoring.UTC),
        date_kind="observed",
    )
    preferences = MatchPreferences(leadership="any")
    base = scoring.score_job(candidate, profile, scoring.utc_day(), preferences)["total"]
    minimum = base + 5
    liked = (scoring.RatedJob("Director of Quality Engineering", "Acme", 1),)
    passed = (scoring.RatedJob("Director of Quality Engineering", "Acme", -1),)
    assert not matches_profile(candidate, profile, minimum, preferences)
    assert matches_profile(candidate, profile, minimum, preferences, liked)
    assert matches_profile(candidate, profile, base, preferences)
    assert not matches_profile(candidate, profile, base, preferences, passed)
