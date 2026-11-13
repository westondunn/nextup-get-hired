"""Company upsert, linking, status and the classifier's query, on an isolated PostgreSQL schema."""

import os
from uuid import UUID

import pytest
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app.companies import find_company_matches
from app.models import Company

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)

# Verbatim from the external email-labeler workflow; do not edit.
LABELER_QUERY = """
  SELECT c.id, c.name AS company_name, $1::text AS message_id
  FROM companies c
  WHERE c.status <> 'archived'
    AND EXISTS (
      SELECT 1 FROM unnest(string_to_array($2::text, '|')) q
      WHERE length(trim(q)) >= 3
        AND (
          c.name_normalized ILIKE '%' || lower(trim(q)) || '%'
          OR lower(trim(q)) = ANY (SELECT lower(a) FROM unnest(c.aliases) a)
        )
    )
  LIMIT 1
"""


def company(session, name):
    return session.scalar(
        select(Company).where(Company.name_normalized == text("nextup_normalize_company(:n)")),
        {"n": name},
    )


def track(client, company_name, title="Director QE"):
    reference = client.post(
        "/api/job-references",
        json={
            "title": title,
            "company": company_name,
            "location": "US Remote",
            "description": "Synthetic posting for company tests.",
            "url": f"https://example.invalid/{company_name.replace(' ', '-')}",
        },
    ).json()
    tracked = client.post("/api/career/pursuits", json=reference).json()
    return next(
        item for item in client.get("/api/career").json()["items"] if item["id"] == tracked["id"]
    )


def test_writes_upsert_and_link_companies_and_keep_status_current(profile_client, profile_database):
    client, engine = profile_client, profile_database[0]
    riley = client.post(
        "/api/contacts", json={"name": "Riley", "company": "Acme Robotics, Inc."}
    ).json()
    sam = client.post("/api/contacts", json={"name": "Sam", "company": "ACME Robotics"}).json()
    assert riley["company_id"] and riley["company_id"] == sam["company_id"], "one company"
    with Session(engine) as session:
        acme = company(session, "Acme Robotics")
        assert acme.name == "Acme Robotics, Inc." and acme.status == "contact_only"

    pursuit = track(client, "Acme Robotics")
    assert pursuit["company_id"] == riley["company_id"]
    with Session(engine) as session:
        assert company(session, "acme robotics").status == "tracking", "no longer only contacts"

    saved = client.put(
        f"/api/career/pursuits/{pursuit['id']}",
        json={"version": pursuit["version"], "stage": "applied"},
    )
    assert saved.status_code == 200 and saved.json()["company_id"] == riley["company_id"]
    with Session(engine) as session:
        assert company(session, "acme robotics").status == "applied"

    # A status the user chose is never replaced by the derived one.
    with Session(engine) as session, session.begin():
        company(session, "acme robotics").status = "interviewing"
    client.post("/api/contacts", json={"name": "Lee", "company": "Acme Robotics"})
    with Session(engine) as session:
        assert company(session, "acme robotics").status == "interviewing"

    # An alias leads to the existing company instead of a new one.
    with Session(engine) as session, session.begin():
        company(session, "acme robotics").aliases = ["AR Group"]
    alias = client.post("/api/contacts", json={"name": "Kim", "company": "ar group"}).json()
    assert alias["company_id"] == riley["company_id"]

    # Changing or clearing a contact's company relinks it; blanks and placeholders link nothing.
    moved = client.put(f"/api/contacts/{sam['id']}", json={"company": "Initech"}).json()
    assert moved["company_id"] and moved["company_id"] != riley["company_id"]
    cleared = client.put(f"/api/contacts/{sam['id']}", json={"company": " "}).json()
    assert cleared["company_id"] is None
    nameless = client.post("/api/contacts", json={"name": "Pat", "company": "Company not provided"})
    assert nameless.json()["company_id"] is None
    with Session(engine) as session:
        initech = company(session, "initech")
        assert initech.status == "tracking", "an orphaned company falls back to tracking"
        names = session.scalars(select(Company.name_normalized).order_by(Company.name)).all()
        assert names == ["acme robotics", "initech"]

    # Deleting the last contact refreshes the status of its company.
    only = client.post("/api/contacts", json={"name": "Jo", "company": "Globex"}).json()
    assert client.delete(f"/api/contacts/{only['id']}").status_code == 204
    with Session(engine) as session:
        assert company(session, "globex").status == "tracking"


def test_labeler_query_runs_as_written_and_agrees_with_find_company_matches(
    profile_client, profile_database
):
    client, engine = profile_client, profile_database[0]
    for name, contact_company in (
        ("A", "Harlow Northwind Corporation"),
        ("B", "Northwind Bank"),
        ("C", "KVL"),
        ("D", "Initech"),
    ):
        client.post("/api/contacts", json={"name": name, "company": contact_company})
    with Session(engine) as session, session.begin():
        company(session, "kvl").aliases = ["KVL Partners", "Kestrel Valley Lending"]
        company(session, "initech").status = "archived"

    cases = {
        "Northwind": {"harlow northwind", "northwind bank"},  # LIMIT 1 picks one of these
        "Harlow Northwind": {"harlow northwind"},
        "Harlow Northwind Corporation": set(),  # names from mail are not normalized
        "kvl partners": {"kvl"},
        "Kestrel Valley Lending|Hooli": {"kvl"},
        "Initech": set(),  # archived
        "Ha|KV": set(),  # too short
        "Hooli|Globex": set(),
    }
    with Session(engine) as session:
        # The raw psycopg connection sends the text untouched, % signs and all.
        raw = session.connection().connection.driver_connection
        raw.execute(f"PREPARE labeler(text, text) AS {LABELER_QUERY}")
        for names, expected in cases.items():
            # EXECUTE takes no bind parameters; quote the two arguments as literals.
            call = sql.SQL("EXECUTE labeler({}, {})").format(
                sql.Literal("msg-1"), sql.Literal(names)
            )
            found = raw.execute(call).fetchall()
            matched = find_company_matches(session, names.split("|"))
            assert {c.name_normalized for c in matched} == expected, names
            if expected:
                assert len(found) == 1 and found[0][2] == "msg-1"
                assert UUID(str(found[0][0])) in {c.id for c in matched}, names
            else:
                assert found == [], names
