"""Bounded reads from documented public posting APIs. Never send profile data."""

import json
import re
import time
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from app.sources.common import NormalizedJob, SourceError, plain_text, require_live_requests
from app.sources.greenhouse import normalize_greenhouse

MAX_BYTES = 16_000_000


def read_json(client, url, params, sleep):
    for attempt in range(2):
        try:
            with client.stream(
                "GET", url, params=params, headers={"Accept": "application/json"}
            ) as response:
                if response.status_code == 429:
                    raise SourceError(
                        "rate_limited", "Employer feed rate limited; retry on a later cycle."
                    )
                if response.status_code >= 500 and attempt == 0:
                    sleep(1)
                    continue
                if response.status_code != 200:
                    raise SourceError(
                        "provider_rejected", f"Employer feed returned HTTP {response.status_code}."
                    )
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise SourceError(
                            "too_large", "Employer feed exceeded the 16 MB response limit."
                        )
                    chunks.append(chunk)
                try:
                    return json.loads(b"".join(chunks))
                except (ValueError, UnicodeError):
                    raise SourceError(
                        "invalid_response", "Employer feed returned invalid JSON."
                    ) from None
        except httpx.RequestError:
            if attempt == 0:
                sleep(1)
                continue
            raise SourceError("network_error", "Employer feed could not be reached.") from None
    raise SourceError("provider_unavailable", "Employer feed is temporarily unavailable.")


def normalize_postings(payload, provider, board, company):
    raw = payload.get("jobs") if provider == "ashby" and isinstance(payload, dict) else payload
    if not isinstance(raw, list) or len(raw) > 5000:
        raise SourceError("invalid_response", "Employer feed returned an invalid posting list.")
    jobs, skipped, unlisted = {}, 0, 0
    for item in raw:
        try:
            if provider == "ashby":
                if item.get("isListed") is not True:
                    skipped += 1
                    unlisted += 1
                    continue
                url = item["jobUrl"]
                # The documented public API does not promise a separate posting ID.
                key = url.rstrip("/").rsplit("/", 1)[-1]
                title, location = item["title"], item["location"]
                locations = [location] + [x["location"] for x in item.get("secondaryLocations", [])]
                mode = item.get("workplaceType") or ("Remote" if item.get("isRemote") else "")
                location = " / ".join(locations + ([mode] if mode else []))
                description = item.get("descriptionPlain") or plain_text(
                    item.get("descriptionHtml") or ""
                )
                posted = item["publishedAt"]
                kind = "posted"
            else:
                key, title, url = item["id"], item["text"], item["hostedUrl"]
                location = item.get("categories", {}).get("location") or "Location not specified"
                mode = item.get("workplaceType") or ""
                if mode:
                    location += " / " + mode
                description = " ".join(
                    [
                        item.get("descriptionPlain") or "",
                        *[
                            plain_text(section.get("text", "") + " " + section.get("content", ""))
                            for section in item.get("lists", [])
                        ],
                        item.get("additionalPlain") or "",
                    ]
                )
                created = item.get("createdAt")
                posted = (
                    datetime.fromtimestamp(created / 1000, UTC) if created else datetime.now(UTC)
                )
                kind = "posted" if created else "observed"
            job = NormalizedJob(
                external_id=f"{board}:{key}",
                title=plain_text(title),
                company=company,
                location=plain_text(location)[:500],
                description=plain_text(description)[:20000],
                url=url,
                posted_at=posted,
                date_kind=kind,
            )
            jobs[job.external_id] = job
        except (ValidationError, KeyError, TypeError, AttributeError, ValueError, OverflowError):
            skipped += 1
    if raw and not jobs and unlisted != len(raw):
        raise SourceError("invalid_response", "Employer feed returned no usable job records.")
    return list(jobs.values()), len(raw), skipped


def fetch_board(provider, board, company, settings, *, client=None, sleep=time.sleep):
    require_live_requests(settings)
    if not settings.live_job_fetch_enabled:
        raise SourceError("disabled", "Live job fetching is disabled.")
    if provider not in ("greenhouse", "lever", "ashby") or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,100}", board
    ):
        raise SourceError(
            "invalid_board", "Choose a supported provider and board token, not a URL."
        )
    if client is None:
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as owned:
            return fetch_board(provider, board, company, settings, client=owned, sleep=sleep)
    if provider == "greenhouse":
        payload = read_json(
            client,
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            {"content": "true"},
            sleep,
        )
        return normalize_greenhouse(payload, board, company)
    if provider == "ashby":
        payload = read_json(
            client, f"https://api.ashbyhq.com/posting-api/job-board/{board}", {}, sleep
        )
        return normalize_postings(payload, provider, board, company)
    postings = []
    for page in range(4):
        payload = read_json(
            client,
            f"https://api.lever.co/v0/postings/{board}",
            {"mode": "json", "skip": page * 250, "limit": 250},
            sleep,
        )
        if not isinstance(payload, list) or len(payload) > 250:
            raise SourceError("invalid_response", "Lever returned an invalid page.")
        postings.extend(payload)
        if len(payload) < 250:
            return normalize_postings(postings, provider, board, company)
    raise SourceError(
        "too_large", "Lever feed exceeded four pages; no partial results were stored."
    )
