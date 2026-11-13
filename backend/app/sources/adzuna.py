import logging
import time

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.sources.common import NormalizedJob, SourceError, plain_text, require_live_requests

# Adzuna authenticates in query parameters. Never emit request URLs to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def normalize_response(payload: object) -> tuple[list[NormalizedJob], int, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SourceError("invalid_response", "Adzuna returned an invalid results document.")
    raw = payload["results"]
    if len(raw) > 50:
        raise SourceError("invalid_response", "Adzuna returned more results than requested.")
    jobs = {}
    skipped = 0
    for item in raw:
        try:
            job = NormalizedJob(
                external_id=item["id"],
                title=plain_text(item["title"]),
                company=plain_text(
                    item.get("company", {}).get("display_name") or "Company not provided"
                ),
                location=plain_text(item["location"]["display_name"]),
                description=plain_text(item.get("description") or "")[:20000],
                url=item["redirect_url"],
                posted_at=item["created"],
            )
        except (ValidationError, KeyError, TypeError, AttributeError, ValueError):
            skipped += 1
            continue
        jobs[job.external_id] = job
    if raw and not jobs:
        raise SourceError("invalid_response", "Adzuna returned no usable job records.")
    return list(jobs.values()), len(raw), skipped


def fetch_adzuna(query: dict, settings: Settings, *, client=None, sleep=time.sleep):
    require_live_requests(settings)
    if not settings.live_job_fetch_enabled:
        raise SourceError("disabled", "Live job fetching is disabled.")
    if (
        not settings.adzuna_app_id.get_secret_value()
        or not settings.adzuna_app_key.get_secret_value()
    ):
        raise SourceError(
            "missing_credentials", "Configure both Adzuna credentials before fetching."
        )
    if client is None:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as owned_client:
            return fetch_adzuna(query, settings, client=owned_client, sleep=sleep)

    params = {
        "app_id": settings.adzuna_app_id.get_secret_value(),
        "app_key": settings.adzuna_app_key.get_secret_value(),
        "what": query["what"],
        "where": query["where"],
        "results_per_page": 25,
    }
    for attempt in range(3):
        try:
            response = client.get(
                "https://api.adzuna.com/v1/api/jobs/us/search/1",
                params=params,
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError:
            if attempt < 2:
                sleep(2**attempt)
                continue
            raise SourceError(
                "network_error", "Adzuna could not be reached after three attempts."
            ) from None
        if response.status_code in (401, 403):
            raise SourceError("authentication", "Adzuna rejected the configured credentials.")
        if response.status_code == 429:
            # Do not retry early or sleep a worker indefinitely when the provider
            # requests a longer pause. The user can retry after its quota resets.
            raise SourceError(
                "rate_limited", "Adzuna rate limit reached. Wait before trying again."
            )
        if response.status_code >= 500:
            if attempt < 2:
                sleep(2**attempt)
                continue
            raise SourceError("provider_unavailable", "Adzuna is temporarily unavailable.")
        if response.status_code != 200:
            raise SourceError("provider_rejected", "Adzuna rejected this search request.")
        try:
            payload = response.json()
        except ValueError:
            raise SourceError("invalid_response", "Adzuna returned invalid JSON.") from None
        return normalize_response(payload)
    raise AssertionError("Unreachable retry state")
