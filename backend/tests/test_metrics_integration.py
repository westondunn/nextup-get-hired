"""Funnel metrics on an isolated schema from synthetic pursuits, events, and mail."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)


def test_funnel_counts_conversions_and_medians_from_recorded_events(
    profile_client, profile_database
):
    client, engine = profile_client, profile_database[0]
    now = datetime.now(UTC)
    ids = {key: uuid4() for key in "abcd"}
    with Session(engine) as session:
        for key, stage, applied_days in (
            ("a", "applied", 10),
            ("b", "interview", 9),
            ("c", "offer", 8),
            ("d", "review", None),
        ):
            session.execute(
                text(
                    "INSERT INTO pursuits (id, job_key, job, stage, created_by, applied_at) "
                    "VALUES (:id, :key, CAST(:job AS jsonb), :stage, 'user', :applied)"
                ),
                {
                    "id": ids[key],
                    "key": f"funnel-{key}",
                    "job": '{"company": "Acme Example", "title": "Director QE"}',
                    "stage": stage,
                    "applied": now - timedelta(days=applied_days) if applied_days else None,
                },
            )
        for key, message, days_ago in (
            ("b", "You recorded stage: applied → interview", 5),
            ("c", "You recorded stage: applied → interview", 4),
            ("c", "You recorded stage: interview → offer", 1),
        ):
            session.execute(
                text(
                    "INSERT INTO pursuit_events (id, pursuit_id, message, created_at) "
                    "VALUES (:id, :pid, :message, :created)"
                ),
                {
                    "id": uuid4(),
                    "pid": ids[key],
                    "message": message,
                    "created": now - timedelta(days=days_ago),
                },
            )
        session.commit()
    reply = client.post(
        "/api/communications",
        json={
            "pursuit_id": str(ids["a"]),
            "direction": "inbound",
            "status": "received",
            "subject": "Thanks for applying",
        },
    ).json()
    assert (
        client.put(
            f"/api/communications/{reply['id']}",
            json={"received_at": (now - timedelta(days=7)).isoformat()},
        ).status_code
        == 200
    )

    funnel = client.get("/api/career/metrics?weeks=2").json()["funnel"]
    assert funnel["overall"] == {
        "tracked": 4,
        "applied": 3,
        "replied": 3,
        "interviewed": 2,
        "offers": 1,
        "accepted": 0,
    }
    assert funnel["conversion"] == {
        "applied_to_replied": 100,
        "replied_to_interviewed": 67,
        "interviewed_to_offers": 50,
        "applied_to_offers": 33,
    }
    assert funnel["median_days"] == {
        "applied_to_reply": 3,
        "applied_to_interview": 4,
        "interview_to_offer": 3,
    }
    assert [c["label"] for c in funnel["cohorts"]] == ["Week 1", "This week"]
    week, this_week = funnel["cohorts"]
    assert {k: week[k] for k in ("applied", "replied", "interviewed", "offers", "accepted")} == {
        "applied": 3,
        "replied": 3,
        "interviewed": 2,
        "offers": 1,
        "accepted": 0,
    }
    assert this_week["applied"] == 0 and this_week["replied"] == 0
    assert funnel["notes"]["unknown_is_not_zero"] is True

    # Nothing applied yet: every rate and duration is unknown, never zero.
    with Session(engine) as session:
        session.execute(text("UPDATE pursuits SET applied_at = NULL"))
        session.commit()
    empty = client.get("/api/career/metrics?weeks=1").json()["funnel"]
    assert empty["overall"]["applied"] == 0 and empty["overall"]["tracked"] == 4
    assert all(value is None for value in empty["conversion"].values())
    assert all(value is None for value in empty["median_days"].values())
