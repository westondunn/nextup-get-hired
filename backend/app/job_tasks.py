import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import get_settings
from app.db import get_engine
from app.job_identity import identity_key
from app.models import Job, JobFetch
from app.recovery import FETCH_LEASE, WINDOW, fail_run
from app.sources.adzuna import SourceError, fetch_adzuna, normalize_response
from app.sources.greenhouse import fetch_greenhouse, normalize_greenhouse

TERMINAL = {"succeeded", "failed"}


def execute_fetch(run_id: UUID, worker: str):
    engine = get_engine()
    token = uuid4()
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        run = session.scalar(select(JobFetch).where(JobFetch.id == run_id).with_for_update())
        if run is None or run.status in TERMINAL:
            return
        if run.lease_expires_at and run.lease_expires_at > now:
            return
        if run.recovery_deadline is None:
            fail_run(run, "This older live request needs a new manual request.", "legacy_expired")
            return
        if (run.recovery_deadline or run.created_at + WINDOW) <= now:
            fail_run(run, "This fetch expired before execution. Submit a new request.")
            return
        source, query = run.source, dict(run.query)
        run.status = "running"
        run.started_at = now
        run.worker = worker
        run.execution_token = token
        run.lease_expires_at = now + FETCH_LEASE
        run.error_code = run.error_message = None

    try:
        fetch_and_store(engine, run_id, token, source, query)
    except SQLAlchemyError:
        # The claim expires even if a database outage prevents releasing it now.
        raise
    except Exception as exc:
        with Session(engine) as session, session.begin():
            run = session.scalar(select(JobFetch).where(JobFetch.id == run_id).with_for_update())
            if run and run.status not in TERMINAL and run.execution_token == token:
                if isinstance(exc, SourceError):
                    fail_run(run, exc.message, exc.code)
                else:
                    fail_run(run, "The worker could not complete this fetch.", "unexpected_error")


# Bundled synthetic fixtures (fixture data mode). The fixture's own board and company keep
# the two sources' "Head of QA" listings identical so cross-source grouping is exercised.
FIXTURE_FILES = {"adzuna": "adzuna.fixture.json", "greenhouse": "greenhouse.fixture.json"}
FIXTURE_GREENHOUSE_BOARD = "example"
FIXTURE_GREENHOUSE_COMPANY = "Example Software — synthetic"


def fixture_listings(source, query):
    """Fixture data mode: synthetic listings only, never a live request and no fallback.
    Employer-board discovery has no synthetic fixture, so it is refused outright."""
    if query.get("discovery") or source not in FIXTURE_FILES:
        raise SourceError(
            "fixture_mode", "Live provider requests are disabled in fixture data mode."
        )
    payload = json.loads(files("app.sources").joinpath(FIXTURE_FILES[source]).read_text())
    if source == "greenhouse":
        return normalize_greenhouse(payload, FIXTURE_GREENHOUSE_BOARD, FIXTURE_GREENHOUSE_COMPANY)
    return normalize_response(payload)


def fetch_and_store(engine, run_id, token, source, query):
    settings = get_settings()
    if settings.fixture_data_mode:
        jobs, received, skipped = fixture_listings(source, query)
    elif query.get("discovery"):
        from app.discovery import load_context, matches_profile
        from app.sources.employer_boards import fetch_board

        profile, minimum, preferences, ratings = load_context(engine, source, query)
        jobs, received, skipped = fetch_board(source, query["board"], query["company"], settings)
        # Recheck pause/removal and use the latest profile after the network read, too.
        profile, minimum, preferences, ratings = load_context(engine, source, query)
        jobs = [job for job in jobs if matches_profile(job, profile, minimum, preferences, ratings)]
    elif source == "greenhouse":
        jobs, received, skipped = fetch_greenhouse(query, settings)
    else:
        jobs, received, skipped = fetch_adzuna(query, settings)

    with Session(engine) as session, session.begin():
        run = session.scalar(select(JobFetch).where(JobFetch.id == run_id).with_for_update())
        if run is None or run.status in TERMINAL or run.execution_token != token:
            return
        now = datetime.now(UTC)
        for job in jobs:
            values = job.model_dump()
            values.update(score=None, score_breakdown=None, score_signature=None)
            values["dedupe_key"] = identity_key(
                source, job.external_id, job.company, job.title, job.location
            )
            session.execute(
                insert(Job)
                .values(source=source, **values, fetched_at=now)
                .on_conflict_do_update(
                    index_elements=[Job.source, Job.external_id], set_={**values, "fetched_at": now}
                )
            )
        run.status = "succeeded"
        run.received_count, run.stored_count, run.skipped_count = received, len(jobs), skipped
        run.completed_at = now
        run.lease_expires_at = None
        run.execution_token = None


@celery_app.task(bind=True, name="app.job_tasks.fetch_jobs")
def fetch_jobs(self):
    try:
        execute_fetch(UUID(self.request.id), self.request.hostname)
    except SQLAlchemyError:
        # Avoid logging SQL parameters, which may contain profile-derived queries.
        raise self.retry(
            exc=RuntimeError("Job storage is unavailable"), countdown=5, max_retries=3
        ) from None
    except Exception:
        with Session(get_engine()) as session, session.begin():
            run = session.get(JobFetch, UUID(self.request.id), with_for_update=True)
            if run and run.status == "queued":
                run.status = "failed"
                run.error_code = "unexpected_error"
                run.error_message = "The worker could not complete this fetch."
                run.completed_at = datetime.now(UTC)
