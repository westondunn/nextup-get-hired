import json
import logging
from importlib.resources import files
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import Settings
from app.sources.adzuna import SourceError, fetch_adzuna, normalize_response

SAMPLE = json.loads(files("app.sources").joinpath("adzuna.fixture.json").read_text())
QUERY = {"what": "Head of QA", "where": "Example City"}


def enabled():
    return Settings(
        live_job_fetch_enabled=True, adzuna_app_id="unit-id", adzuna_app_key="unit-secret"
    )


def test_normalizes_html_dates_and_optional_company():
    row = {**SAMPLE["results"][0], "company": {}}
    jobs, received, skipped = normalize_response({"results": [row]})
    assert jobs[0].title == "Director of Quality Engineering"
    assert jobs[0].company == "Company not provided"
    assert jobs[0].posted_at.tzinfo is not None
    assert received == 1 and skipped == 0


def test_duplicate_ids_are_collapsed_and_bad_rows_are_counted():
    row = SAMPLE["results"][0]
    jobs, received, skipped = normalize_response({"results": [row, row, {"id": "bad"}]})
    assert len(jobs) == 1
    assert received == 3 and skipped == 1


@pytest.mark.parametrize("payload", [None, [], {}, {"results": "wrong"}, {"results": [{}]}])
def test_malformed_provider_payload_fails(payload):
    with pytest.raises(SourceError, match="Adzuna returned"):
        normalize_response(payload)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "https://user:secret@example.com", "file:///etc/passwd"]
)
def test_unsafe_listing_urls_are_rejected(url):
    with pytest.raises(SourceError):
        normalize_response({"results": [{**SAMPLE["results"][0], "redirect_url": url}]})


def test_empty_results_are_a_successful_empty_search():
    assert normalize_response({"results": []}) == ([], 0, 0)


@pytest.mark.parametrize(
    "settings,code",
    [
        (Settings(live_job_fetch_enabled=False), "disabled"),
        (
            Settings(live_job_fetch_enabled=True, adzuna_app_id="", adzuna_app_key=""),
            "missing_credentials",
        ),
    ],
)
def test_disabled_or_unconfigured_never_sends_a_request(settings, code):
    client = MagicMock()
    with pytest.raises(SourceError) as error:
        fetch_adzuna(QUERY, settings, client=client)
    assert error.value.code == code
    client.get.assert_not_called()


def test_request_uses_profile_query_and_does_not_log_credentials(caplog):
    def handler(request):
        assert request.url.host == "api.adzuna.com"
        assert request.url.path == "/v1/api/jobs/us/search/1"
        assert request.url.params["what"] == QUERY["what"]
        assert request.url.params["where"] == QUERY["where"]
        assert request.url.params["results_per_page"] == "25"
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=SAMPLE)

    with (
        caplog.at_level(logging.INFO),
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
    ):
        jobs, _, _ = fetch_adzuna(QUERY, enabled(), client=client)
    assert len(jobs) == 2
    assert "unit-secret" not in caplog.text
    assert "unit-id" not in caplog.text
    assert "unit-secret" not in repr(enabled())


@pytest.mark.parametrize(
    "status,code,calls",
    [
        (401, "authentication", 1),
        (403, "authentication", 1),
        (429, "rate_limited", 1),
        (302, "provider_rejected", 1),
        (500, "provider_unavailable", 3),
    ],
)
def test_provider_errors_are_bounded_and_sanitized(status, code, calls):
    requests = []
    sleep = MagicMock()

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="private credential unit-secret")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError) as error:
            fetch_adzuna(QUERY, enabled(), client=client, sleep=sleep)
    assert error.value.code == code
    assert "unit-secret" not in str(error.value)
    assert len(requests) == calls
    assert sleep.call_count == calls - 1


def test_transient_network_failure_retries_then_succeeds():
    attempts = []
    sleep = MagicMock()

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ReadTimeout("do not expose credentials", request=request)
        return httpx.Response(200, json=SAMPLE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, _, _ = fetch_adzuna(QUERY, enabled(), client=client, sleep=sleep)
    assert len(jobs) == 2
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_invalid_json_response_is_sanitized():
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not JSON"))
    ) as client:
        with pytest.raises(SourceError) as error:
            fetch_adzuna(QUERY, enabled(), client=client)
    assert error.value.code == "invalid_response"


def test_persistent_network_failure_stops_after_three_attempts():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("unit-secret in private transport details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError) as error:
            fetch_adzuna(QUERY, enabled(), client=client, sleep=MagicMock())
    assert error.value.code == "network_error"
    assert "unit-secret" not in str(error.value)
    assert len(attempts) == 3
