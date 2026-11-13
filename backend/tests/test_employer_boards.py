from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app import scoring
from app.config import Settings
from app.discovery import matches_profile
from app.sources.common import NormalizedJob, SourceError
from app.sources.employer_boards import fetch_board, normalize_postings

LIVE = Settings(live_job_fetch_enabled=True)


def posting(**changes):
    return {
        "id": "test-id",
        "text": "Director of Quality Engineering",
        "categories": {"location": "United States"},
        "workplaceType": "remote",
        "descriptionPlain": "Lead test automation and Python teams",
        "createdAt": 1793404800000,
        "hostedUrl": "https://jobs.lever.co/example/test-id",
        **changes,
    }


def test_lever_pagination_and_namespaced_ids_without_profile_transmission():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.lever.co"
        assert set(request.url.params) == {"skip", "limit", "mode"}
        return httpx.Response(
            200,
            json=[
                posting(id=str(n), hostedUrl=f"https://jobs.lever.co/example/{n}")
                for n in range(250)
            ]
            if request.url.params["skip"] == "0"
            else [],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, received, skipped = fetch_board("lever", "example", "Example", LIVE, client=client)
    assert len(requests) == 2 and received == len(jobs) == 250 and skipped == 0
    assert jobs[0].external_id == "example:0" and "remote" in jobs[0].location


def test_ashby_excludes_unlisted_and_preserves_remote_and_secondary_locations():
    entry = {
        "title": "Engineering Director",
        "isListed": True,
        "location": "USA",
        "isRemote": True,
        "secondaryLocations": [{"location": "Springfield"}],
        "descriptionPlain": "Synthetic",
        "publishedAt": "2026-10-01T12:00:00Z",
        "jobUrl": "https://jobs.ashbyhq.com/example/id",
    }
    jobs, count, skipped = normalize_postings(
        {"jobs": [entry, {**entry, "isListed": False}]}, "ashby", "example", "Example"
    )
    assert count == 2 and skipped == 1 and len(jobs) == 1
    assert jobs[0].location == "USA / Springfield / Remote"
    assert jobs[0].external_id == "example:id"


@pytest.mark.parametrize(
    "status,code", [(403, "provider_rejected"), (404, "provider_rejected"), (429, "rate_limited")]
)
def test_provider_refusal_is_not_retried(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError) as caught:
            fetch_board("ashby", "example", "Example", LIVE, client=client)
    assert caught.value.code == code and len(calls) == 1


def test_live_gate_bad_tokens_invalid_json_and_size_limit(monkeypatch):
    with pytest.raises(SourceError, match="disabled"):
        fetch_board("lever", "example", "Example", Settings(live_job_fetch_enabled=False))
    with pytest.raises(SourceError, match="board token"):
        fetch_board("lever", "../private", "Example", LIVE)
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"not json"))
    ) as client:
        with pytest.raises(SourceError, match="invalid JSON"):
            fetch_board("lever", "example", "Example", LIVE, client=client)
    monkeypatch.setattr("app.sources.employer_boards.MAX_BYTES", 5)
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"123456"))
    ) as client:
        with pytest.raises(SourceError, match="response limit"):
            fetch_board("lever", "example", "Example", LIVE, client=client)


def test_missing_provider_date_is_observed_and_invalid_records_fail():
    jobs, _, _ = normalize_postings([posting(createdAt=None)], "lever", "example", "Example")
    assert jobs[0].date_kind == "observed"
    profile = SimpleNamespace(skills=[], target_titles=[], location="", work_preferences=[])
    result = scoring.score_job(jobs[0], profile, scoring.utc_day())
    assert next(c for c in result["components"] if c["key"] == "recency")["points"] == 0
    with pytest.raises(SourceError):
        normalize_postings([{}], "lever", "example", "Example")


def test_profile_matching_requires_relevant_evidence_and_leadership_if_requested():
    profile = SimpleNamespace(
        skills=["Python", "Test automation"],
        target_titles=["Director of Quality Engineering"],
        location="Springfield",
        work_preferences=["remote"],
    )
    job = NormalizedJob(
        external_id="1",
        title="Director of Quality Engineering",
        company="Example",
        location="US Remote",
        description="Python test automation",
        url="https://example.invalid/1",
        posted_at=datetime.now(UTC),
        date_kind="posted",
    )
    assert matches_profile(job, profile, 20)
    assert not matches_profile(job.model_copy(update={"title": "Junior developer"}), profile, 0)
    assert not matches_profile(
        job.model_copy(update={"title": "Director of Sales", "description": "Sales"}), profile, 0
    )
    assert not matches_profile(job, profile, 100)
