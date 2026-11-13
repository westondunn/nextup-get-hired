"""Create old synthetic history only in the disposable CI database."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import DiagnosticRun, JobFetch


def main():
    settings = get_settings()
    identity = settings.identity
    database = identity.database
    # Identity components only: never compare or print a URL or password.
    # CI runs in fixture data mode: synthetic fixtures only, live fetching off.
    if (
        (identity.environment, identity.role) != ("ci", "runtime")
        or (database.host, database.port, database.name, database.user)
        != ("postgres", 5432, "nextup_ci", "nextup_ci_app")
        or not settings.fixture_data_mode
        or settings.live_job_fetch_enabled
        or not settings.task_history_cleanup_enabled
    ):
        raise RuntimeError("Retention seed requires the isolated CI configuration")
    now = datetime.now(UTC)
    old = now - timedelta(days=40)
    # Current, but outside the fetch rate limit: the browser specs start their own fetch
    # moments later, and a synthetic fetch stamped "now" made that request return 429.
    recent = now - timedelta(minutes=5)
    with Session(get_engine()) as session, session.begin():
        if session.execute(
            text("SELECT current_database(), current_setting('cluster_name')")
        ).one() != ("nextup_ci", "nextup-ci"):
            raise RuntimeError("Refusing to seed a non-CI database")
        for model, source, prefix in ((DiagnosticRun, "manual", "d"), (JobFetch, "adzuna", "f")):
            for index, timestamp in ((1, old), (2, recent)):
                values = dict(
                    id=UUID(f"{prefix * 8}-0000-4000-8000-{index:012d}"),
                    source=source,
                    status="succeeded",
                    created_at=timestamp,
                    completed_at=timestamp,
                )
                if model is JobFetch:
                    values["query"] = {}
                session.add(model(**values))
    print("Seeded two old synthetic history records and two protected current anchors")


if __name__ == "__main__":
    main()
