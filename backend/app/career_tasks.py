"""Periodic local planning; repeat delivery is idempotent and never sends anything."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import get_engine


@celery_app.task(bind=True, name="app.career_tasks.prepare_plan")
def prepare_plan(self):
    from app.career import reconcile_plan

    try:
        with Session(get_engine()) as session, session.begin():
            return reconcile_plan(session, self.request.hostname)
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Planning storage is unavailable"), countdown=10, max_retries=3
        ) from None
