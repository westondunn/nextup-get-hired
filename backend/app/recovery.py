"""Recover durable task intents without replaying terminal or legacy provider work."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import get_engine
from app.models import DiagnosticRun, JobFetch

WINDOW = timedelta(minutes=15)
RESEND_AFTER = timedelta(seconds=60)
FETCH_LEASE = timedelta(seconds=120)
MAX_DELIVERIES = 5
PENDING = ("queued", "running", "publish_failed")


def new_intent():
    now = datetime.now(UTC)
    return {"recovery_deadline": now + WINDOW, "last_dispatched_at": now, "delivery_attempts": 1}


def fail_run(run, message, code="recovery_exhausted", now=None):
    run.status = "failed"
    run.completed_at = now or datetime.now(UTC)
    run.error_message = message
    if isinstance(run, JobFetch):
        run.error_code = code
        run.execution_token = None
        run.lease_expires_at = None


def recover_pending(engine=None, publisher=None, now=None):
    """Claim due rows before publishing. A crash anywhere leaves a recoverable intent."""
    from app.job_tasks import fetch_jobs
    from app.tasks import run_diagnostic

    engine = engine or get_engine()
    now = now or datetime.now(UTC)
    for model, task in ((DiagnosticRun, run_diagnostic), (JobFetch, fetch_jobs)):
        with Session(engine) as session:
            ids = list(
                session.scalars(
                    select(model.id)
                    .where(
                        model.status.in_(PENDING),
                        or_(
                            model.last_dispatched_at.is_(None),
                            model.last_dispatched_at <= now - RESEND_AFTER,
                        ),
                        or_(
                            model.recovery_deadline.is_not(None),
                            and_(
                                model.status.in_(("queued", "running")),
                                model.created_at <= now - WINDOW,
                            ),
                        ),
                    )
                    .order_by(model.created_at, model.id)
                    .limit(100)
                )
            )
        for run_id in ids:
            with Session(engine) as session, session.begin():
                run = session.scalar(
                    select(model).where(model.id == run_id).with_for_update(skip_locked=True)
                )
                if run is None or run.status not in PENDING:
                    continue
                if run.last_dispatched_at and run.last_dispatched_at > now - RESEND_AFTER:
                    continue
                if (
                    isinstance(run, JobFetch)
                    and run.lease_expires_at
                    and run.lease_expires_at > now
                ):
                    continue
                if run.recovery_deadline is None:
                    # Never automatically replay requests accepted by an older version.
                    if run.status != "publish_failed" and run.created_at <= now - WINDOW:
                        fail_run(
                            run,
                            "This older request expired. Submit a new request.",
                            "legacy_expired",
                            now,
                        )
                    continue
                if run.recovery_deadline <= now or run.delivery_attempts >= MAX_DELIVERIES:
                    fail_run(
                        run,
                        "Recovery attempts expired. Check service status and submit a new request.",
                        now=now,
                    )
                    continue
                run.status = "queued"
                run.completed_at = None
                run.error_message = None
                run.delivery_attempts += 1
                run.last_dispatched_at = now
                if isinstance(run, JobFetch):
                    run.error_code = None
                    run.execution_token = None
                    run.lease_expires_at = None
                kwargs = {"source": run.source} if model is DiagnosticRun else {}
            try:
                if publisher is not None:
                    publisher(task, run_id, kwargs)
                else:
                    task.apply_async(task_id=str(run_id), kwargs=kwargs, retry=False)
            except Exception:
                with Session(engine) as session, session.begin():
                    values = {
                        "status": "publish_failed",
                        "error_message": "Delivery unconfirmed; automatic recovery is pending.",
                    }
                    if model is JobFetch:
                        values["error_code"] = "broker_unavailable"
                    session.execute(
                        update(model)
                        .where(
                            model.id == run_id,
                            model.status == "queued",
                            model.last_dispatched_at == now,
                        )
                        .values(**values)
                    )
                # A down broker should not consume the whole backlog's retry budget.
                return


@celery_app.task(bind=True, name="app.recovery.recover_tasks")
def recover_tasks(self):
    try:
        recover_pending()
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Recovery storage is unavailable"), countdown=5, max_retries=3
        ) from None
