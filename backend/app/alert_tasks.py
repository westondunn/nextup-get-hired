"""Local inbox delivery; no network provider or external notification calls."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import get_engine
from app.job_identity import identity_key
from app.models import JobAlert, Profile, SavedSearch


def evaluate_alerts(worker: str, search_id: UUID | None = None):
    # Late import avoids the jobs router/task registration cycle.
    from app.jobs import query_jobs

    with Session(get_engine()) as session:
        query = select(SavedSearch.id).where(SavedSearch.alerts_enabled.is_(True))
        if search_id is not None:
            query = query.where(SavedSearch.id == search_id)
        ids = list(session.scalars(query))
    for current_id in ids:
        with Session(get_engine()) as session, session.begin():
            search = session.scalar(
                select(SavedSearch)
                .where(SavedSearch.id == current_id)
                .with_for_update(skip_locked=True)
            )
            if search is None or not search.alerts_enabled:
                continue
            search.alert_checked_at = datetime.now(UTC)
            search.alert_worker = worker
            if session.get(Profile, 1) is None:
                search.alert_check_status = "profile_required"
                continue
            filters = dict(search.filters)
            filters["min_score"] = max(filters.get("min_score") or 0, search.alert_min_score)
            filters["sort"] = "score"
            page = query_jobs(
                session,
                source=search.source,
                include_expired=False,
                limit=None,
                commit_scores=False,
                **filters,
            )
            seen = set(
                session.scalars(select(JobAlert.job_key).where(JobAlert.search_id == search.id))
            )
            count = 0
            for job in page["items"]:
                key = identity_key(
                    job.source, job.external_id, job.company, job.title, job.location
                )
                if key in seen:
                    continue
                session.execute(
                    insert(JobAlert)
                    .values(
                        id=uuid4(),
                        search_id=search.id,
                        job_key=key,
                        search_name=search.name,
                        job=job.model_dump(mode="json"),
                    )
                    .on_conflict_do_nothing(constraint="alert_search_job_key")
                )
                seen.add(key)
                count += 1
                if count >= 10:
                    break
            search.alert_check_status = "ok"


@celery_app.task(bind=True, name="app.alert_tasks.check_alerts")
def check_alerts(self, search_id: str | None = None):
    try:
        evaluate_alerts(self.request.hostname, UUID(search_id) if search_id else None)
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Alert storage is unavailable"), countdown=5, max_retries=3
        ) from None
