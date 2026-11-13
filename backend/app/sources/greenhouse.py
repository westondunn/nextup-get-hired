"""Read only the official public Job Board API; never scrape HTML pages."""

import re
import time
from html import unescape

import httpx
from pydantic import ValidationError

from app.sources.common import NormalizedJob, SourceError, plain_text, require_live_requests


def normalize_greenhouse(payload: object, board: str, company: str):
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise SourceError("invalid_response", "Greenhouse returned an invalid jobs document.")
    raw = payload["jobs"]
    if len(raw) > 5000:
        raise SourceError("invalid_response", "Greenhouse returned more than 5000 job posts.")
    jobs, skipped = {}, 0
    for item in raw:
        try:
            job_id = item["id"]
            if isinstance(job_id, bool) or not str(job_id).isdigit():
                raise ValueError("Invalid job post ID")
            # The list endpoint provides an update time, not a publication date.
            job = NormalizedJob(
                external_id=f"{board}:{job_id}",
                title=plain_text(item["title"]),
                company=plain_text(company),
                location=plain_text(item["location"]["name"]),
                description=plain_text(unescape(unescape(item.get("content") or "")))[:20000],
                url=item["absolute_url"],
                posted_at=item["updated_at"],
                date_kind="updated",
            )
        except (ValidationError, KeyError, TypeError, AttributeError, ValueError):
            skipped += 1
            continue
        jobs[job.external_id] = job
    if raw and not jobs:
        raise SourceError("invalid_response", "Greenhouse returned no usable job records.")
    return list(jobs.values()), len(raw), skipped


def fetch_greenhouse(query: dict, settings, *, client=None, sleep=time.sleep):
    require_live_requests(settings)
    if not settings.live_job_fetch_enabled:
        raise SourceError("disabled", "Live job fetching is disabled.")
    board, company = query.get("board", ""), query.get("company", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board) or not company.strip():
        raise SourceError(
            "missing_configuration", "Configure a Greenhouse board token and company name."
        )
    if client is None:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as owned_client:
            return fetch_greenhouse(query, settings, client=owned_client, sleep=sleep)
    for attempt in range(3):
        try:
            response = client.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                params={"content": "true"},
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError:
            if attempt < 2:
                sleep(2**attempt)
                continue
            raise SourceError(
                "network_error", "Greenhouse could not be reached after three attempts."
            ) from None
        if response.status_code == 429:
            raise SourceError(
                "rate_limited", "Greenhouse rate limit reached. Wait before trying again."
            )
        if response.status_code >= 500:
            if attempt < 2:
                sleep(2**attempt)
                continue
            raise SourceError("provider_unavailable", "Greenhouse is temporarily unavailable.")
        if response.status_code != 200:
            raise SourceError(
                "provider_rejected", "Greenhouse rejected the request. Check the board token."
            )
        try:
            payload = response.json()
        except ValueError:
            raise SourceError("invalid_response", "Greenhouse returned invalid JSON.") from None
        return normalize_greenhouse(payload, board, company)
    raise AssertionError("Unreachable retry state")
