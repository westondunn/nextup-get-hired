"""Local profile matching and durable, per-employer discovery intents."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import scoring
from app.config import get_settings
from app.job_ratings import load_ratings
from app.models import DiscoverySettings, JobFetch, Profile
from app.recovery import new_intent
from app.relevance import MatchPreferences, location_matches, role_matches, title_tokens
from app.sources.common import SourceError


def profile_ready(profile):
    return bool(
        profile
        and profile.skills
        and profile.target_titles
        and profile.location.strip().casefold() != "example city"
    )


def matches_profile(job, profile, minimum, preferences=None, ratings=()):
    preferences = preferences or MatchPreferences()
    aliases = preferences.title_aliases
    if not location_matches(job.location, preferences) or not role_matches(
        job.title, profile, preferences.leadership, aliases, preferences.other_specialties
    ):
        return False
    title_words = set(title_tokens(job.title, aliases))
    text_words = scoring.tokens(job.title + " " + job.description)
    leaders = {"director", "head", "vp", "president", "manager"}
    skills = any(
        scoring.contains_phrase(text_words, scoring.tokens(skill)) for skill in profile.skills
    )
    titles = False
    for title in profile.target_titles:
        words = set(title_tokens(title, aliases)) - scoring.TITLE_STOP_WORDS
        # A generic leadership word alone is not evidence of matching the discipline.
        substantive = words - leaders - {"senior", "associate", "chief"}
        if substantive & title_words and len(words & title_words) >= max(1, len(words) / 2):
            titles = True
    # Your ratings move the score, so similar jobs clear (or miss) the minimum next ingest.
    return (skills or titles) and scoring.score_job(
        job, profile, scoring.utc_day(), preferences, ratings
    )["total"] >= minimum


def load_context(engine, source, query):
    with Session(engine) as session:
        config = session.get(DiscoverySettings, 1)
        profile = session.get(Profile, 1)
        selected = config and any(
            b["provider"] == source and b["board"] == query["board"] for b in config.boards
        )
        if not selected or (query.get("automatic") and not config.enabled):
            raise SourceError(
                "discovery_paused", "This employer is no longer enabled for this request."
            )
        if not profile_ready(profile):
            raise SourceError(
                "profile_required", "Save your actual profile before discovering jobs."
            )
        return (
            SimpleNamespace(
                skills=list(profile.skills),
                target_titles=list(profile.target_titles),
                location=profile.location,
                work_preferences=list(profile.work_preferences),
            ),
            config.min_score,
            MatchPreferences.model_validate(config.match_preferences),
            load_ratings(session),
        )


def enqueue_discovery(engine, *, automatic=False, publisher=None, now=None):
    from app.job_tasks import fetch_jobs

    now = now or datetime.now(UTC)
    settings = get_settings()
    if not settings.live_job_fetch_enabled:
        if automatic:
            return []
        raise SourceError("disabled", "Enable live job fetching in local configuration first.")
    accepted = []
    with Session(engine) as session, session.begin():
        config = session.scalar(
            select(DiscoverySettings)
            .where(DiscoverySettings.id == 1)
            .with_for_update(skip_locked=True)
        )
        if config is None:
            if automatic:
                return []
            raise SourceError(
                "configuration_required", "Save employer sources before discovering jobs."
            )
        if automatic and (not config.enabled or (config.next_run_at and config.next_run_at > now)):
            return []
        if not profile_ready(session.get(Profile, 1)):
            if automatic:
                return []
            raise SourceError(
                "profile_required", "Replace the demo profile with your actual skills and location."
            )
        for board in config.boards:
            previous = session.scalar(
                select(JobFetch)
                .where(JobFetch.source == board["provider"], JobFetch.board_key == board["board"])
                .order_by(JobFetch.created_at.desc())
                .limit(1)
            )
            if previous and (
                previous.status in ("queued", "running")
                or (previous.status == "publish_failed" and previous.recovery_deadline)
                or previous.created_at
                > now - timedelta(seconds=settings.job_fetch_min_interval_seconds)
            ):
                continue
            run = JobFetch(
                id=uuid4(),
                source=board["provider"],
                board_key=board["board"],
                status="queued",
                query={
                    "board": board["board"],
                    "company": board["company"],
                    "discovery": True,
                    "automatic": automatic,
                },
                **new_intent(),
            )
            session.add(run)
            accepted.append(
                {
                    "id": str(run.id),
                    "source": run.source,
                    "board_key": run.board_key,
                    "status": "queued",
                }
            )
        config.last_run_at = now
        config.next_run_at = now + timedelta(hours=config.interval_hours)
    for run in accepted:
        try:
            if publisher:
                publisher(run["id"])
            else:
                fetch_jobs.apply_async(task_id=run["id"], retry=False)
        except Exception:
            from uuid import UUID

            with Session(engine) as session, session.begin():
                session.execute(
                    update(JobFetch)
                    .where(JobFetch.id == UUID(run["id"]), JobFetch.status == "queued")
                    .values(
                        status="publish_failed",
                        error_code="broker_unavailable",
                        error_message="Delivery unconfirmed; automatic recovery is pending.",
                    )
                )
            run["status"] = "publish_failed"
    return accepted
