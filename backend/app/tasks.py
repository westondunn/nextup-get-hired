from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db import get_engine
from app.models import DiagnosticRun
from app.recovery import fail_run


@celery_app.task(
    bind=True,
    name="app.tasks.run_diagnostic",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_diagnostic(self, source: str = "manual") -> None:
    """Persist evidence of real worker execution; duplicate deliveries are harmless."""
    run_id = UUID(self.request.id)
    with Session(get_engine()) as session, session.begin():
        # Manual requests must have a durable API intent. A delayed duplicate must
        # not recreate history that the user has explicitly cleaned up.
        if source == "scheduler":
            session.execute(
                insert(DiagnosticRun)
                .values(id=run_id, source=source, status="queued")
                .on_conflict_do_nothing(index_elements=[DiagnosticRun.id])
            )
        run = session.scalar(
            select(DiagnosticRun).where(DiagnosticRun.id == run_id).with_for_update()
        )
        if run is None or run.status in ("succeeded", "failed"):
            return
        if run.recovery_deadline and run.recovery_deadline <= datetime.now(UTC):
            fail_run(run, "This diagnostic expired before execution. Submit a new request.")
            return
        database = session.scalar(text("SELECT current_database()"))
        run.status = "succeeded"
        run.error_message = None
        run.completed_at = datetime.now(UTC)
        run.worker = self.request.hostname
        run.result = {"message": "Worker reached PostgreSQL", "database": database}
