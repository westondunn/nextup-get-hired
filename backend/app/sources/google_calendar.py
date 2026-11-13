"""Read-only Google Calendar adapter sharing the Gmail OAuth client.

Only ``calendar.readonly`` is used. Nothing here creates, edits, or responds to
events. Network access is explicit and bounded so tests can inject a mocked client.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx

from app.config import Settings
from app.sources.common import SourceError, plain_text, require_live_requests
from app.sources.gmail import _read_json, credentials_present

API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
MAX_EVENTS = 100
MAX_BODY_CHARS = 100_000  # whole descriptions; the UI shows them in full


@dataclass(frozen=True)
class ParsedEvent:
    source_id: str
    summary: str
    description: str
    location: str
    link: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    organizer_email: str
    organizer_name: str
    attendee_emails: tuple[str, ...] = field(default_factory=tuple)
    attendee_names: tuple[str, ...] = field(default_factory=tuple)


def refresh_access_token(client: httpx.Client, settings: Settings) -> str:
    """Refresh the shared Google token and require the calendar read-only scope."""
    require_live_requests(settings)
    if not credentials_present(settings):
        raise SourceError("not_configured", "Google credentials are not configured.")
    payload = _read_json(
        client,
        "POST",
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_oauth_client_id.get_secret_value(),
            "client_secret": settings.google_oauth_client_secret.get_secret_value(),
            "refresh_token": settings.gmail_refresh_token.get_secret_value(),
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token")
    scope = payload.get("scope", "")
    if not isinstance(token, str) or not token:
        raise SourceError("unauthorized", "Google did not return an access token.")
    if SCOPE not in str(scope).split():
        raise SourceError(
            "wrong_scope",
            "The stored token lacks the Calendar read-only scope; re-authorize Google access.",
        )
    return token


def list_events(
    client: httpx.Client, token: str, start: datetime, end: datetime, max_events: int = MAX_EVENTS
) -> list[dict]:
    payload = _read_json(
        client,
        "GET",
        API_BASE,
        params={
            "timeMin": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(max_events, MAX_EVENTS)),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise SourceError("invalid_response", "Calendar returned an unexpected payload.")
    return [item for item in items if isinstance(item, dict)]


def _when(value: dict | None) -> tuple[datetime | None, bool]:
    if not isinstance(value, dict):
        return None, False
    stamp = value.get("dateTime")
    if isinstance(stamp, str) and stamp:
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return None, False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC), False
    day = value.get("date")
    if isinstance(day, str) and day:
        try:
            return datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC), True
        except ValueError:
            return None, False
    return None, False


def parse_event(payload: dict) -> ParsedEvent | None:
    """Return the event, or None for cancelled, malformed, or undated items."""
    event_id = payload.get("id")
    if not isinstance(event_id, str) or not event_id or payload.get("status") == "cancelled":
        return None
    starts_at, all_day = _when(payload.get("start"))
    if starts_at is None:
        return None
    ends_at, _ = _when(payload.get("end"))
    organizer = payload.get("organizer") if isinstance(payload.get("organizer"), dict) else {}
    emails, names = [], []
    for attendee in payload.get("attendees") or []:
        if not isinstance(attendee, dict) or attendee.get("self"):
            continue
        email = str(attendee.get("email") or "").strip().lower()
        if email:
            emails.append(email[:320])
            names.append(str(attendee.get("displayName") or "").strip()[:200])
    description = plain_text(str(payload.get("description") or ""))[:MAX_BODY_CHARS]
    return ParsedEvent(
        source_id=event_id,
        summary=str(payload.get("summary") or "").replace("\x00", "").strip()[:500],
        description=description,
        location=str(payload.get("location") or "").strip()[:500],
        link=str(payload.get("hangoutLink") or payload.get("htmlLink") or "").strip()[:500],
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        organizer_email=str(organizer.get("email") or "").strip().lower()[:320],
        organizer_name=str(organizer.get("displayName") or "").strip()[:200],
        attendee_emails=tuple(emails),
        attendee_names=tuple(names),
    )


def window(now: datetime, lookahead_days: int) -> tuple[datetime, datetime]:
    """Yesterday through the lookahead, so recently finished interviews are kept."""
    return now - timedelta(days=1), now + timedelta(days=lookahead_days)
