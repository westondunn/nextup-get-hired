"""Resume files and pursuit links on an isolated schema; synthetic bytes only."""

import base64
import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_profile_integration import profile_client as profile_client
from test_profile_integration import profile_database as profile_database

from app.models import PursuitEvent

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL"
)

PDF = b"%PDF-1.4\n% synthetic resume for tests\n%%EOF\n"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def payload(name="resume.pdf", content_type="application/pdf", data=PDF):
    return {
        "file_name": name,
        "content_type": content_type,
        "data_base64": base64.b64encode(data).decode(),
    }


def test_resume_file_round_trip_and_pursuit_link(profile_client, profile_database):
    client, engine = profile_client, profile_database[0]
    resume = client.post(
        "/api/resumes", json={"variant_name": "Director QE", "content": "# Synthetic"}
    ).json()
    rid, path = resume["id"], f"/api/resumes/{resume['id']}/file"
    assert resume["file"] is None
    assert client.get(path).status_code == 404

    # Only PDF or DOCX, bytes must match the declared type, and 5 MB is the ceiling.
    assert client.put(path, json=payload(content_type="text/plain")).status_code == 422
    assert client.put(path, json=payload(data=b"hello")).status_code == 422
    assert client.put(path, json=payload(content_type=DOCX, data=PDF)).status_code == 422
    assert client.put(path, json=payload(data=PDF + b"0" * 5_000_000)).status_code == 413
    assert client.put(path, json={**payload(), "data_base64": "@@"}).status_code == 422

    uploaded = client.put(path, json=payload(name="../Alex Rivera — QE.pdf")).json()
    assert uploaded["file"]["name"] == "Alex Rivera — QE.pdf"
    assert uploaded["file"]["type"] == "application/pdf" and uploaded["file"]["size"] == len(PDF)
    assert uploaded["file"]["uploaded_at"] is not None
    download = client.get(path)
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.headers["content-disposition"] == (
        'attachment; filename="Alex Rivera _ QE.pdf"; '
        "filename*=UTF-8''Alex%20Rivera%20%E2%80%94%20QE.pdf"
    )
    listing = client.get("/api/resumes").json()
    assert listing[0]["file"]["name"] == "Alex Rivera — QE.pdf" and "file_data" not in listing[0]

    docx = client.put(
        path, json=payload(name="resume.docx", content_type=DOCX, data=b"PK\x03\x04zip")
    )
    assert docx.status_code == 200 and docx.json()["file"]["type"] == DOCX

    # A new version starts from the text, never from the previous file.
    second = client.post(f"/api/resumes/{rid}/new-version").json()
    assert second["content"] == "# Synthetic" and second["file"] is None
    assert second["version_number"] == 2

    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO pursuits (id, job_key, job, stage, created_by) VALUES "
                "(gen_random_uuid(), 'resume-synthetic', "
                '\'{"company": "Acme Example", "title": "Director QE"}\', \'preparing\', \'user\')'
            )
        )
        session.commit()
    item = client.get("/api/career").json()["items"][0]
    assert item["resume_version_id"] is None and item["resume_label"] is None
    body = {
        "version": item["version"],
        "stage": item["stage"],
        "notes": item["notes"],
        "application_draft": item["application_draft"],
        "outreach_draft": item["outreach_draft"],
        "next_action_on": item["next_action_on"],
    }
    pursuit_path = f"/api/career/pursuits/{item['id']}"
    missing = client.put(
        pursuit_path, json={**body, "resume_version_id": str(resume["id"])[:-4] + "0000"}
    )
    assert missing.status_code == 404
    linked = client.put(pursuit_path, json={**body, "resume_version_id": rid})
    assert linked.status_code == 200
    assert linked.json()["resume_version_id"] == rid
    assert linked.json()["resume_label"] == "Director QE v1"
    with Session(engine) as session:
        messages = session.scalars(
            select(PursuitEvent.message).order_by(PursuitEvent.created_at)
        ).all()
        assert messages[-1] == "You recorded the resume submitted: Director QE v1"
    assert client.get("/api/career").json()["items"][0]["resume_label"] == "Director QE v1"

    # Removing the file keeps the version row and the pursuit's record of it.
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(f"/api/resumes/{rid}").json()["file"] is None
    assert client.get("/api/career").json()["items"][0]["resume_version_id"] == rid
    cleared = client.put(
        pursuit_path, json={**body, "version": linked.json()["version"], "resume_version_id": None}
    )
    assert cleared.status_code == 200 and cleared.json()["resume_label"] is None
    with Session(engine) as session:
        last = session.scalars(
            select(PursuitEvent.message).order_by(PursuitEvent.created_at.desc())
        ).first()
        assert last == "You removed the submitted resume"
