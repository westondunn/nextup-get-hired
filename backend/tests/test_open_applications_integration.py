"""One open application per employer: badges, hiding, the tracking check, the planner."""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_career_integration import career as career
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app.career import reconcile_plan
from app.models import Pursuit

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
            "description": "Python test automation for a synthetic product.",
            "url": f"https://example.invalid/{company}/{title}".replace(" ", "-"),
        },
    )
    assert response.status_code == 201
    return response.json()


def board(client, **params):
    page = client.get("/api/jobs", params={"source": "reference", "limit": 50, **params})
    return {(item["company"], item["title"]): item for item in page.json()["items"]}


def stage(client, pursuit_id, new_stage):
    item = next(i for i in client.get("/api/career").json()["items"] if i["id"] == pursuit_id)
    saved = client.put(
        f"/api/career/pursuits/{pursuit_id}", json={"version": item["version"], "stage": new_stage}
    )
    assert saved.status_code == 200


def test_open_application_flags_hides_checks_and_releases_on_close(career):
    client, _ = career
    first = add_reference(client, "Platform Engineer", "Acme Robotics, Inc.")
    second = add_reference(client, "Head of QA", "ACME Robotics")
    tracked = client.post("/api/career/pursuits", json=first)
    assert tracked.status_code == 200
    pursuit_id = tracked.json()["id"]

    # Considering a job is not applying: review and preparing hold nothing.
    for considering in ("review", "preparing"):
        if considering == "preparing":
            stage(client, pursuit_id, "preparing")
        assert all(item["open_applications"] == [] for item in board(client).values())
        assert ("ACME Robotics", "Head of QA") in board(client, hide_open_companies="true")
        assert client.post("/api/career/pursuits", json=second).status_code == 200
        with Session(career[1]) as session, session.begin():
            session.query(Pursuit).filter(Pursuit.job["title"].astext == "Head of QA").delete()

    stage(client, pursuit_id, "applied")
    jobs = board(client)
    mine = jobs[("Acme Robotics, Inc.", "Platform Engineer")]["open_applications"]
    assert [(a["pursuit_id"], a["stage"], a["same_job"]) for a in mine] == [
        (pursuit_id, "applied", True)
    ]
    sibling = jobs[("ACME Robotics", "Head of QA")]["open_applications"]
    assert [(a["title"], a["same_job"]) for a in sibling] == [("Platform Engineer", False)]
    assert jobs[("Synthetic 1", "Director of Quality Engineering")]["open_applications"] == []

    hidden = board(client, hide_open_companies="true")
    assert ("ACME Robotics", "Head of QA") not in hidden
    assert ("Acme Robotics, Inc.", "Platform Engineer") not in hidden
    assert ("Synthetic 1", "Director of Quality Engineering") in hidden

    # Tracking a second job where you applied needs an explicit confirmation.
    refused = client.post("/api/career/pursuits", json=second)
    assert refused.status_code == 409
    assert refused.headers["X-Nextup-Conflict"] == "same_company"
    assert (
        "open application at Acme Robotics, Inc.: Platform Engineer (applied)"
        in (refused.json()["detail"])
    )
    again = client.post("/api/career/pursuits", json=first)
    assert again.status_code == 200 and again.json()["created"] is False, "same job is fine"
    allowed = client.post("/api/career/pursuits", json={**second, "allow_same_company": True})
    assert allowed.status_code == 200 and allowed.json()["created"] is True

    # A decision on the application brings the employer's jobs straight back.
    stage(client, pursuit_id, "rejected")
    back = board(client, hide_open_companies="true")
    assert ("ACME Robotics", "Head of QA") in back
    assert back[("ACME Robotics", "Head of QA")]["open_applications"] == []


def test_planner_skips_employers_where_you_applied(career):
    client, engine = career
    applied = add_reference(client, "Director of Quality Engineering", "Synthetic Twin")
    pursuit_id = client.post("/api/career/pursuits", json=applied).json()["id"]
    stage(client, pursuit_id, "applied")
    # Newer and equally scored, so these would be planned first if the employer were free.
    add_reference(client, "Director of Quality Engineering Platform", "Synthetic Twin")
    add_reference(client, "Director of Quality Engineering Lead", "SYNTHETIC TWIN, Inc.")
    with Session(engine) as session, session.begin():
        assert reconcile_plan(session, "synthetic")["added"] == 3
    with Session(engine) as session:
        planned = [
            p.job["company"]
            for p in session.scalars(select(Pursuit).where(Pursuit.created_by == "automatic"))
        ]
    assert len(planned) == 3
    assert not [c for c in planned if c.casefold().startswith("synthetic twin")], planned
