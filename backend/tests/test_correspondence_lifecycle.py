"""Worker and sync settings lifecycle regressions with mocked providers and storage."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from test_gmail import FakeGmail, fake_session, message_payload
from test_google_calendar import FakeCalendar, event_payload
from test_google_calendar import fake_session as fake_calendar_session
from test_google_credentials import (
    BOTH,
    FALLBACK_ONLY,
    STORED_ONLY,
    calendar_config,
    connection,
    mail_config,
)

from app import application_intake, correspondence, google_connection, google_lifecycle
from app.correspondence_tasks import sync_calendar, sync_gmail
from app.models import Communication, GoogleConnection
from app.sources import gmail, google_calendar

PAST = datetime(2020, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def test_complete_empty_mail_pass_records_success_and_current_generation():
    config = mail_config()
    config.cursor_epoch = 42
    session = fake_session(config, connection=connection())
    with FakeGmail([]).client() as http:
        assert sync_gmail(session, STORED_ONLY, http)["status"] == "ok"
    assert config.cursor_epoch is None  # The unknown old checkpoint was never validated.
    assert session.lifecycle.gmail_attempt_generation == session.lifecycle.generation
    assert session.lifecycle.gmail_last_success_at == config.last_run_at
    assert session.lifecycle.calendar_last_success_at is None


@pytest.mark.parametrize(
    "cause", ["page_count", "id_count", "backlog", "malformed", "failure", "collision"]
)
def test_incomplete_mail_preserves_the_previous_success_and_cursor(monkeypatch, cause):
    config = mail_config()
    config.cursor_epoch = 123
    payload = message_payload("m", "person@example.test", "Synthetic", "", 1_700_000_000_000)
    fake = FakeGmail([payload])
    known = ["m"] if cause == "collision" else []
    session = fake_session(config, connection=connection(), known=known)
    session.lifecycle.gmail_last_success_at = PAST
    session.lifecycle.imports_since = PAST
    if cause == "id_count":
        monkeypatch.setattr("app.correspondence_tasks.MAX_LISTED_IDS", 1)
    if cause == "collision":
        session.scalar.side_effect = lambda stmt: (
            uuid4() if "communications.created_at <" in str(stmt) else None
        )

    def provider(request):
        if request.url.path.endswith("/messages"):
            body = {"messages": [{"id": "m"}]}
            if cause == "page_count":
                body["nextPageToken"] = "synthetic-next"
            if cause == "backlog":
                config.max_messages_per_run = 1
                body["messages"].append({"id": "later"})
            if cause == "malformed":
                body["messages"].append({"id": None})
            return httpx.Response(200, json=body)
        if cause == "failure" and request.url.path.endswith("/messages/m"):
            return httpx.Response(503)
        return fake.handler(request)

    with httpx.Client(transport=httpx.MockTransport(provider)) as http:
        result = sync_gmail(session, STORED_ONLY, http)
    assert result["status"] == ("provider_unavailable" if cause == "failure" else "ok")
    assert session.lifecycle.gmail_attempt_generation == session.lifecycle.generation
    assert session.lifecycle.gmail_last_success_at == PAST and config.cursor_epoch == 123
    if cause == "collision":
        assert not session.added


@pytest.mark.parametrize("transition", ["generation", "pause", "invalid_grant"])
@pytest.mark.parametrize("late_failure", [False, True])
def test_late_message_success_or_failure_cannot_write_or_intake(
    monkeypatch, transition, late_failure
):
    grant = connection()
    config = mail_config()
    config.last_status = "not_run"
    session = fake_session(config, connection=grant)
    intake = MagicMock()
    monkeypatch.setattr(application_intake, "run", intake)
    fake = FakeGmail(
        [
            message_payload(key, "a@example.test", "Synthetic", "Synthetic", 1_700_000_000_000)
            for key in ("a", "b")
        ]
    )
    requests = []

    def provider(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/messages/a"):
            if transition == "generation":
                google_lifecycle.advance_generation(session.lifecycle)
            elif transition == "pause":
                google_lifecycle.invalidate(session.lifecycle)
            else:
                grant.state = "needs_reauthorization"
            if late_failure:
                return httpx.Response(503)
        return fake.handler(request)

    with httpx.Client(transport=httpx.MockTransport(provider)) as http:
        result = sync_gmail(session, BOTH, http, intake=True)
    assert result == {"status": "disabled", "imported": 0}
    assert not any(path.endswith("/messages/b") for path in requests)
    assert not session.added and config.last_status == "not_run"
    assert (
        session.lifecycle.gmail_attempt_generation
        is session.lifecycle.gmail_last_success_at
        is None
    )
    intake.assert_not_called()


@pytest.mark.parametrize("previous_managed", [False, True])
def test_fallback_cursor_and_freshness_after_explicit_resumption(previous_managed):
    config = mail_config()
    config.cursor_epoch = 123
    session = fake_session(config)
    if previous_managed:
        google_lifecycle.invalidate(session.lifecycle)
        session.lifecycle.sync_paused = False
    fake = FakeGmail([])
    with fake.client() as http:
        assert sync_gmail(session, FALLBACK_ONLY, http, now=NOW)["status"] == "ok"
    query = next(r.url.params["q"] for r in fake.requests if r.url.path.endswith("/messages"))
    expected = int((NOW - timedelta(days=30)).timestamp()) if previous_managed else 123
    assert query.endswith(f"after:{expected}")
    assert (
        session.lifecycle.gmail_last_success_at
        is session.lifecycle.gmail_attempt_generation
        is None
    )


@pytest.mark.parametrize(
    "case", ["complete", "continuation", "at_cap", "malformed", "protected", "late"]
)
def test_calendar_only_confirms_complete_current_pass(case):
    config = calendar_config()
    old = Communication(source_id="old", created_at=PAST, subject="Local edit", status="dismissed")
    session = fake_calendar_session(config, connection=connection(), existing=[old])
    session.lifecycle.imports_since = NOW
    session.lifecycle.calendar_last_success_at = PAST
    fake = FakeCalendar([])

    def provider(request):
        if request.url.host == "oauth2.googleapis.com":
            return fake.handler(request)
        body = {"items": []}
        if case == "continuation":
            body["nextPageToken"] = "synthetic-next"
        if case == "at_cap":
            body["items"] = [
                {"id": str(i), "status": "cancelled"} for i in range(google_calendar.MAX_EVENTS)
            ]
        if case == "malformed":
            body["items"] = [{"id": "missing-date"}]
        if case == "protected":
            body["items"] = [event_payload("old", "Do not overwrite", "2026-11-24T12:00:00Z")]
        if case == "late":
            google_lifecycle.invalidate(session.lifecycle)
            body["items"] = [event_payload("new", "Do not import", "2026-11-24T12:00:00Z")]
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(provider)) as http:
        result = sync_calendar(session, STORED_ONLY, http)
    assert result["status"] == ("disabled" if case == "late" else "ok")
    assert not session.added and (old.subject, old.status) == ("Local edit", "dismissed")
    if case == "complete":
        assert session.lifecycle.calendar_last_success_at == config.calendar_last_run_at
    elif case == "late":
        assert session.lifecycle.calendar_last_success_at is config.calendar_last_run_at is None
    else:
        assert session.lifecycle.calendar_last_success_at == PAST


def test_paused_settings_refuse_queue_and_resume_only_selected_eligible_capability(monkeypatch):
    config = mail_config()
    config.calendar_enabled = True
    config.cursor_epoch = 123
    session = fake_session(config)
    google_lifecycle.invalidate(session.lifecycle)
    monkeypatch.setattr(correspondence, "get_settings", lambda: FALLBACK_ONLY)
    queue = MagicMock()
    monkeypatch.setattr(correspondence.sync_gmail_task, "apply_async", queue)
    monkeypatch.setattr(correspondence.sync_calendar_task, "apply_async", queue)
    report = correspondence.read_correspondence(session)
    assert not report["enabled"] and not report["calendar_enabled"]
    with pytest.raises(HTTPException) as refused:
        correspondence.run_sync(session)
    assert refused.value.status_code == 409
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("outbound request"))
    ) as http:
        assert sync_gmail(session, FALLBACK_ONLY, http, intake=True)["status"] == "disabled"
        assert sync_calendar(session, FALLBACK_ONLY, http)["status"] == "disabled"
    queue.assert_not_called()
    updated = correspondence.save_correspondence(
        correspondence.CorrespondenceInput(enabled=True, query=config.query), session
    )
    assert updated["enabled"] and not updated["calendar_enabled"]
    assert not session.lifecycle.sync_paused and updated["cursor_epoch"] is None
    assert correspondence.run_sync(session)["tasks"] == ["gmail"]
    queue.assert_called_once()


def test_ineligible_explicit_resume_keeps_all_syncs_paused(monkeypatch):
    config = mail_config()
    config.calendar_enabled = True
    session = fake_session(config, connection=connection(granted_scopes=[gmail.SCOPE]))
    session.lifecycle.sync_paused = True
    monkeypatch.setattr(correspondence, "get_settings", lambda: BOTH)
    with pytest.raises(HTTPException) as refused:
        correspondence.save_correspondence(
            correspondence.CorrespondenceInput(calendar_enabled=True), session
        )
    assert refused.value.status_code == 409 and session.lifecycle.sync_paused
    session.commit.assert_not_called()
    assert session.get(GoogleConnection, 1).state == "connected"


@pytest.mark.parametrize(
    "http_code, legacy_code",
    [(400, "provider_rejected"), (401, "unauthorized"), (403, "unauthorized")],
)
@pytest.mark.parametrize("capability", ["gmail", "calendar"])
def test_admin_policy_detail_preserves_correspondence_wire_codes(
    monkeypatch, http_code, legacy_code, capability
):
    config = mail_config() if capability == "gmail" else calendar_config()
    session = fake_session(config, connection=connection())
    grant = session.get(GoogleConnection, 1)
    session.execute.return_value.one.return_value = (session.lifecycle, grant, config)
    monkeypatch.setattr(correspondence, "get_settings", lambda: STORED_ONLY)

    def handler(_):
        return httpx.Response(http_code, json={"error": "admin_policy_enforced"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        sync = sync_gmail if capability == "gmail" else sync_calendar
        result = sync(session, STORED_ONLY, http)
    assert result["status"] == legacy_code
    last_status = "last_status" if capability == "gmail" else "calendar_last_status"
    assert correspondence.read_correspondence(session)[last_status] == legacy_code
    report = google_connection.connection_status(session, STORED_ONLY)
    assert report["sync"][capability]["last_status"] == "admin_restricted"
    assert report["sync"][capability]["last_success_at"] is None and grant.state == "connected"
