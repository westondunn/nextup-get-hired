"""Calendar import across daylight-saving boundaries. Synthetic events; no calendar is touched.

America/Chicago changes clocks twice in the period used here:

- 2027-03-14 at 08:00 UTC: 02:00 CST becomes 03:00 CDT, so 02:00 to 02:59 does not exist.
- 2026-11-01 at 07:00 UTC: 02:00 CDT becomes 01:00 CST, so 01:00 to 01:59 happens twice.

UTC has no transitions; the same dates are used for it so that both zones see the same cases.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_google_calendar import CONFIGURED, FakeCalendar, event_payload, fake_session

from app.correspondence_tasks import sync_calendar
from app.models import CorrespondenceSyncSettings
from app.sources import google_calendar as cal

CHICAGO = ZoneInfo("America/Chicago")
SPRING = datetime(2027, 3, 14, 8, 0, tzinfo=UTC)
AUTUMN = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
CST, CDT = timedelta(hours=-6), timedelta(hours=-5)


def utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def timed(event_id, start, end=None, **extra):
    payload = event_payload(event_id, f"Synthetic event {event_id}", start, **extra)
    payload["end"] = {"dateTime": end or start}
    return payload


def all_day(event_id, day):
    following = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": f"Synthetic all-day event {event_id}",
        "start": {"date": day},
        "end": {"date": following},
    }


def test_the_fixture_instants_are_the_chicago_transitions():
    second = timedelta(seconds=1)
    assert (SPRING - second).astimezone(CHICAGO).utcoffset() == CST
    assert SPRING.astimezone(CHICAGO).utcoffset() == CDT
    assert (AUTUMN - second).astimezone(CHICAGO).utcoffset() == CDT
    assert AUTUMN.astimezone(CHICAGO).utcoffset() == CST
    # The wall clock jumps from 01:59:59 to 03:00:00, and from 01:59:59 back to 01:00:00.
    assert (SPRING - second).astimezone(CHICAGO).time().isoformat() == "01:59:59"
    assert SPRING.astimezone(CHICAGO).time().isoformat() == "03:00:00"
    assert (AUTUMN - second).astimezone(CHICAGO).time().isoformat() == "01:59:59"
    assert AUTUMN.astimezone(CHICAGO).time().isoformat() == "01:00:00"


# Stamps as a provider writes them for a Chicago calendar: local time with its offset.
CHICAGO_TIMES = [
    pytest.param("2027-03-14T01:00:00-06:00", utc(2027, 3, 14, 7), id="spring-hour-before"),
    pytest.param(
        "2027-03-14T01:59:59-06:00", utc(2027, 3, 14, 7, 59, 59), id="spring-last-second-before"
    ),
    pytest.param("2027-03-14T03:00:00-05:00", utc(2027, 3, 14, 8), id="spring-first-instant-after"),
    pytest.param("2027-03-14T03:59:59-05:00", utc(2027, 3, 14, 8, 59, 59), id="spring-hour-after"),
    pytest.param("2026-11-01T00:30:00-05:00", utc(2026, 11, 1, 5, 30), id="autumn-hour-before"),
    pytest.param(
        "2026-11-01T01:30:00-05:00", utc(2026, 11, 1, 6, 30), id="autumn-repeated-hour-first"
    ),
    pytest.param(
        "2026-11-01T01:30:00-06:00", utc(2026, 11, 1, 7, 30), id="autumn-repeated-hour-second"
    ),
    pytest.param("2026-11-01T02:30:00-06:00", utc(2026, 11, 1, 8, 30), id="autumn-hour-after"),
]


@pytest.mark.parametrize(("stamp", "instant"), CHICAGO_TIMES)
def test_a_chicago_event_keeps_its_instant_around_a_transition(stamp, instant):
    event = cal.parse_event(timed("e", stamp))
    assert event.starts_at == instant
    assert event.starts_at.utcoffset() == timedelta(0) and not event.all_day
    # The stored instant shows the same wall-clock time again when read in Chicago.
    assert event.starts_at.astimezone(CHICAGO).isoformat() == stamp


@pytest.mark.parametrize(
    ("stamp", "instant", "chicago_wall_clock"),
    [
        # 02:30 does not exist on this day. A stamp that names it is still one exact instant,
        # decided by its offset, and Chicago reads that instant on either side of the gap.
        pytest.param(
            "2027-03-14T02:30:00-06:00",
            utc(2027, 3, 14, 8, 30),
            "2027-03-14T03:30:00-05:00",
            id="old-offset",
        ),
        pytest.param(
            "2027-03-14T02:30:00-05:00",
            utc(2027, 3, 14, 7, 30),
            "2027-03-14T01:30:00-06:00",
            id="new-offset",
        ),
    ],
)
def test_a_time_in_the_skipped_hour_resolves_by_its_offset(stamp, instant, chicago_wall_clock):
    event = cal.parse_event(timed("e", stamp))
    assert event.starts_at == instant
    assert event.starts_at.astimezone(CHICAGO).isoformat() == chicago_wall_clock


@pytest.mark.parametrize(
    "stamp",
    [
        "2027-03-14T01:59:59Z",
        "2027-03-14T02:30:00Z",
        "2027-03-14T08:00:00Z",
        "2026-11-01T01:30:00Z",
        "2026-11-01T07:00:00Z",
        "2026-11-01T01:30:00+00:00",
    ],
)
def test_a_utc_event_is_unchanged_on_the_same_dates(stamp):
    event = cal.parse_event(timed("e", stamp))
    assert event.starts_at == datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert event.starts_at.utcoffset() == timedelta(0)


def test_the_two_passes_of_the_repeated_hour_stay_distinct_and_ordered():
    first = cal.parse_event(timed("first", "2026-11-01T01:30:00-05:00"))
    second = cal.parse_event(timed("second", "2026-11-01T01:30:00-06:00"))
    assert second.starts_at - first.starts_at == timedelta(hours=1)
    assert sorted([second, first], key=lambda e: e.starts_at) == [first, second]
    # Both read 01:30 on a Chicago wall clock; only the offset tells them apart.
    assert first.starts_at.astimezone(CHICAGO).time() == second.starts_at.astimezone(CHICAGO).time()


@pytest.mark.parametrize(
    ("start", "end", "length"),
    [
        pytest.param(
            "2027-03-14T01:30:00-06:00",
            "2027-03-14T03:30:00-05:00",
            timedelta(hours=1),
            id="spring-across-the-gap",
        ),
        pytest.param(
            "2026-11-01T01:30:00-05:00",
            "2026-11-01T01:30:00-06:00",
            timedelta(hours=1),
            id="autumn-across-the-repeat",
        ),
        pytest.param(
            "2027-03-14T00:00:00-06:00",
            "2027-03-15T00:00:00-05:00",
            timedelta(hours=23),
            id="spring-local-day",
        ),
        pytest.param(
            "2026-11-01T00:00:00-05:00",
            "2026-11-02T00:00:00-06:00",
            timedelta(hours=25),
            id="autumn-local-day",
        ),
    ],
)
def test_an_event_spanning_a_transition_keeps_its_real_length(start, end, length):
    event = cal.parse_event(timed("e", start, end))
    assert event.ends_at - event.starts_at == length


@pytest.mark.parametrize("day", ["2027-03-13", "2027-03-14", "2027-03-15", "2026-11-01"])
def test_an_all_day_event_keeps_its_calendar_date(day):
    event = cal.parse_event(all_day("e", day))
    assert event.all_day
    # The adapter encodes an all-day event as midnight UTC of its date, with the flag set.
    assert event.starts_at == datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)
    assert event.starts_at.date().isoformat() == day
    # The provider's end date is exclusive: one day later, whatever the local day's length.
    assert event.ends_at - event.starts_at == timedelta(days=1)


@pytest.mark.xfail(
    strict=True,
    reason="The adapter ignores start.timeZone and reads an offset-less dateTime as UTC. "
    "Defect: https://github.com/westondunn/nextup-get-hired/issues/39",
)
@pytest.mark.parametrize(
    ("local", "instant"),
    [
        pytest.param("2027-03-14T01:30:00", utc(2027, 3, 14, 7, 30), id="spring-before"),
        pytest.param("2027-03-14T03:30:00", utc(2027, 3, 14, 8, 30), id="spring-after"),
        pytest.param("2026-11-01T02:30:00", utc(2026, 11, 1, 8, 30), id="autumn-after"),
    ],
)
def test_a_time_without_an_offset_is_read_in_the_named_zone(local, instant):
    # The Calendar API allows dateTime to omit the offset when timeZone is given.
    payload = timed("e", local)
    payload["start"] = {"dateTime": local, "timeZone": "America/Chicago"}
    assert cal.parse_event(payload).starts_at == instant


def test_a_time_without_an_offset_or_zone_is_read_as_utc():
    assert cal.parse_event(timed("e", "2027-03-14T02:30:00")).starts_at == utc(2027, 3, 14, 2, 30)


@pytest.mark.parametrize(
    ("now", "start", "end"),
    [
        # The sync passes the current time in UTC, so the window is measured in elapsed time and
        # does not stretch or shrink with the clocks.
        pytest.param(
            utc(2027, 3, 14, 7, 30), utc(2027, 3, 13, 7, 30), utc(2027, 3, 28, 7, 30), id="spring"
        ),
        pytest.param(
            utc(2026, 11, 1, 6, 30), utc(2026, 10, 31, 6, 30), utc(2026, 11, 15, 6, 30), id="autumn"
        ),
    ],
)
def test_the_sync_window_is_elapsed_time_across_a_transition(now, start, end):
    assert cal.window(now, 14) == (start, end)
    assert end - start == timedelta(days=15)


@pytest.mark.parametrize(
    ("start", "end", "time_min", "time_max"),
    [
        pytest.param(
            datetime(2027, 3, 14, 1, 30, tzinfo=CHICAGO),
            datetime(2027, 3, 14, 3, 30, tzinfo=CHICAGO),
            "2027-03-14T07:30:00Z",
            "2027-03-14T08:30:00Z",
            id="spring",
        ),
        pytest.param(
            datetime(2026, 11, 1, 1, 30, tzinfo=CHICAGO, fold=0),
            datetime(2026, 11, 1, 1, 30, tzinfo=CHICAGO, fold=1),
            "2026-11-01T06:30:00Z",
            "2026-11-01T07:30:00Z",
            id="autumn",
        ),
    ],
)
def test_the_listing_request_sends_utc_for_chicago_bounds(start, end, time_min, time_max):
    fake = FakeCalendar([])
    with fake.client() as client:
        assert cal.list_events(client, "token", start, end) == []
    params = fake.requests[-1].url.params
    assert (params["timeMin"], params["timeMax"]) == (time_min, time_max)


SPRING_EVENTS = [
    timed("before", "2027-03-14T01:30:00-06:00", "2027-03-14T01:45:00-06:00"),
    timed("across", "2027-03-14T01:50:00-06:00", "2027-03-14T03:10:00-05:00"),
    timed("after", "2027-03-14T03:30:00-05:00", "2027-03-14T04:00:00-05:00"),
    all_day("day", "2027-03-14"),
]
SPRING_STORED = {
    "before": (utc(2027, 3, 14, 7, 30), utc(2027, 3, 14, 7, 45)),
    "across": (utc(2027, 3, 14, 7, 50), utc(2027, 3, 14, 8, 10)),
    "after": (utc(2027, 3, 14, 8, 30), utc(2027, 3, 14, 9, 0)),
}
AUTUMN_EVENTS = [
    timed("before", "2026-11-01T00:30:00-05:00", "2026-11-01T00:45:00-05:00"),
    timed("first", "2026-11-01T01:30:00-05:00", "2026-11-01T01:45:00-05:00"),
    timed("second", "2026-11-01T01:30:00-06:00", "2026-11-01T01:45:00-06:00"),
    timed("after", "2026-11-01T02:30:00-06:00", "2026-11-01T03:00:00-06:00"),
    all_day("day", "2026-11-01"),
]
AUTUMN_STORED = {
    "before": (utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 5, 45)),
    "first": (utc(2026, 11, 1, 6, 30), utc(2026, 11, 1, 6, 45)),
    "second": (utc(2026, 11, 1, 7, 30), utc(2026, 11, 1, 7, 45)),
    "after": (utc(2026, 11, 1, 8, 30), utc(2026, 11, 1, 9, 0)),
}


def as_utc(events):
    """The same events as a provider would write them for a calendar kept in UTC."""

    def moved(when):
        if "date" in when:
            return dict(when)
        instant = datetime.fromisoformat(when["dateTime"]).astimezone(UTC)
        return {"dateTime": instant.isoformat().replace("+00:00", "Z")}

    return [
        {**event, "start": moved(event["start"]), "end": moved(event["end"])} for event in events
    ]


def run_sync(items, now, existing=()):
    config = CorrespondenceSyncSettings(id=1, calendar_enabled=True, calendar_lookahead_days=14)
    session = fake_session(config, existing=existing)
    fake = FakeCalendar(items)
    with fake.client() as client:
        result = sync_calendar(session, CONFIGURED, client=client, now=now)
    return result, session, fake


@pytest.mark.parametrize(
    ("events", "stored", "day", "now"),
    [
        pytest.param(SPRING_EVENTS, SPRING_STORED, "2027-03-14", utc(2027, 3, 13, 12), id="spring"),
        pytest.param(
            AUTUMN_EVENTS, AUTUMN_STORED, "2026-11-01", utc(2026, 10, 31, 12), id="autumn"
        ),
    ],
)
@pytest.mark.parametrize("written_in", ["chicago", "utc"])
def test_import_stores_instants_and_is_stable_across_a_transition(
    events, stored, day, now, written_in
):
    items = events if written_in == "chicago" else as_utc(events)
    result, session, fake = run_sync(items, now)
    assert result == {"status": "ok", "imported": len(events), "updated": 0}
    rows = {row.source_id: row for row in session.added}

    for event_id, (starts_at, ends_at) in stored.items():
        row = rows[event_id]
        assert row.received_at == starts_at
        # The note states the time in UTC with an explicit offset, so it cannot be misread.
        when = f"When: {starts_at.isoformat()} to {ends_at.isoformat()}"
        assert row.body.splitlines()[0] == when and when.count("+00:00") == 2

    # Stored order is the order the events happen in, including through the repeated hour.
    timed_rows = [rows[event_id] for event_id in stored]
    assert sorted(timed_rows, key=lambda row: row.received_at) == timed_rows

    # An all-day event is stored at midnight UTC of its date; "all day" survives only in the note.
    assert rows["day"].received_at == datetime.combine(
        date.fromisoformat(day), datetime.min.time(), UTC
    )
    assert rows["day"].body.splitlines()[0] == "When: all day"

    listing = next(r for r in fake.requests if r.url.host == "www.googleapis.com")
    assert listing.url.params["timeMin"] == (now - timedelta(days=1)).isoformat().replace(
        "+00:00", "Z"
    )
    assert listing.url.params["timeMax"] == (now + timedelta(days=14)).isoformat().replace(
        "+00:00", "Z"
    )

    # Delivering the same events again changes nothing, after the transition and in either
    # notation: a row is updated only when its instant, title or note really differs.
    stored_rows = list(session.added)
    for again in (events, as_utc(events)):
        for later in (now, now + timedelta(days=1)):
            result, session, _ = run_sync(again, later, existing=stored_rows)
            assert result == {"status": "ok", "imported": 0, "updated": 0}
            assert session.added == []


def test_a_one_hour_move_across_the_transition_updates_the_stored_instant():
    result, session, _ = run_sync(SPRING_EVENTS, utc(2027, 3, 13, 12))
    stored = {row.source_id: row for row in session.added}
    moved = [timed("before", "2027-03-14T03:30:00-05:00", "2027-03-14T03:45:00-05:00")]
    result, session, _ = run_sync(moved, utc(2027, 3, 13, 12), existing=[stored["before"]])
    assert result == {"status": "ok", "imported": 0, "updated": 1}
    # 01:30 CST to 03:30 CDT looks like two hours on the wall clock and is one hour later.
    assert stored["before"].received_at == utc(2027, 3, 14, 8, 30)
    assert session.added == []
