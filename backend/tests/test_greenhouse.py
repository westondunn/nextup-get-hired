import json
from importlib.resources import files
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.job_identity import identity_key
from app.sources.common import SourceError
from app.sources.greenhouse import fetch_greenhouse, normalize_greenhouse

PAYLOAD = json.loads(files("app.sources").joinpath("greenhouse.fixture.json").read_text())
QUERY = {"board": "example", "company": "Example Software — synthetic"}


def test_normalizes_board_scoped_ids_encoded_html_and_updated_dates():
    jobs, received, skipped = normalize_greenhouse(PAYLOAD, **QUERY)
    assert (received, skipped) == (2, 0)
    assert jobs[0].external_id == "example:1001"
    assert jobs[0].company == QUERY["company"]
    assert "<p>" not in jobs[0].description and "&lt;" not in jobs[0].description
    assert jobs[0].date_kind == "updated"
    assert jobs[0].posted_at.tzinfo is not None
    other, _, _ = normalize_greenhouse(PAYLOAD, "another-board", QUERY["company"])
    assert other[0].external_id != jobs[0].external_id


def test_no_request_without_opt_in_or_valid_configuration():
    client = MagicMock()
    with pytest.raises(SourceError, match="disabled"):
        fetch_greenhouse(QUERY, Settings(live_job_fetch_enabled=False), client=client)
    for query in ({}, {**QUERY, "board": "../internal"}, {**QUERY, "company": " "}):
        with pytest.raises(SourceError):
            fetch_greenhouse(query, Settings(live_job_fetch_enabled=True), client=client)
    client.get.assert_not_called()
    with pytest.raises(ValidationError):
        Settings(greenhouse_board_token="https://example.com")


def test_official_endpoint_uses_content_parameter_and_no_credentials():
    def handler(request):
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.path == "/v1/boards/example/jobs"
        assert dict(request.url.params) == {"content": "true"}
        assert "authorization" not in request.headers
        return httpx.Response(200, json=PAYLOAD)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, _, _ = fetch_greenhouse(QUERY, Settings(live_job_fetch_enabled=True), client=client)
    assert len(jobs) == 2


@pytest.mark.parametrize(
    "status,code,count",
    [
        (404, "provider_rejected", 1),
        (302, "provider_rejected", 1),
        (429, "rate_limited", 1),
        (503, "provider_unavailable", 3),
    ],
)
def test_errors_are_bounded_and_do_not_expose_response_body(status, code, count):
    handler = MagicMock(return_value=httpx.Response(status, text="private response"))
    sleep = MagicMock()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError) as error:
            fetch_greenhouse(
                QUERY, Settings(live_job_fetch_enabled=True), client=client, sleep=sleep
            )
    assert error.value.code == code and "private" not in str(error.value)
    assert handler.call_count == count
    assert sleep.call_count == count - 1


def test_transport_failure_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ReadTimeout("private transport error")
        return httpx.Response(200, json=PAYLOAD)

    sleep = MagicMock()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, _, _ = fetch_greenhouse(
            QUERY, Settings(live_job_fetch_enabled=True), client=client, sleep=sleep
        )
    assert len(jobs) == 2
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("payload", [None, {"jobs": {}}, {"jobs": [{}]}, {"jobs": [{}] * 5001}])
def test_invalid_documents_fail(payload):
    with pytest.raises(SourceError):
        normalize_greenhouse(payload, **QUERY)


def test_empty_partial_duplicate_and_unsafe_rows():
    assert normalize_greenhouse({"jobs": []}, **QUERY) == ([], 0, 0)
    row = PAYLOAD["jobs"][0]
    jobs, received, skipped = normalize_greenhouse(
        {"jobs": [row, row, {**row, "absolute_url": "javascript:alert(1)"}]}, **QUERY
    )
    assert (len(jobs), received, skipped) == (1, 3, 1)


def test_grouping_normalizes_case_whitespace_and_unicode_but_preserves_distinctions():
    key = identity_key("adzuna", "1", "Example Software", "Head of QA", "Springfield")
    assert key == identity_key(
        "greenhouse", "board:2", "Ｅxample  SOFTWARE", "head of qa", " Springfield "
    )
    assert key != identity_key(
        "greenhouse", "board:2", "Example Software", "Head of QA", "Shelbyville"
    )
    assert key == identity_key(
        "adzuna", "different-id", "Example Software", "Head of QA", "Springfield"
    )
    assert identity_key("adzuna", "1", "Company not provided", "QA", "Springfield") != identity_key(
        "greenhouse", "2", "Company not provided", "QA", "Springfield"
    )
