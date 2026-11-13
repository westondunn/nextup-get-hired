import logging
from datetime import UTC, datetime

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import get_settings
from app.db import get_engine
from app.models import DiagnosticRun
from app.schemas import DiagnosticOut

logger = logging.getLogger(__name__)


def probe_health() -> dict:
    checks = {"api": "up", "database": "down", "broker": "down", "worker": "down"}
    latest = None
    scheduler = "waiting"
    try:
        with Session(get_engine()) as session:
            # Reading the migrated table verifies schema readiness as well as connectivity.
            latest_run = session.scalar(
                select(DiagnosticRun).order_by(DiagnosticRun.created_at.desc()).limit(1)
            )
            scheduled = session.scalar(
                select(DiagnosticRun)
                .where(DiagnosticRun.source == "scheduler", DiagnosticRun.status == "succeeded")
                .order_by(DiagnosticRun.completed_at.desc())
                .limit(1)
            )
            checks["database"] = "up"
            if latest_run:
                latest = DiagnosticOut.model_validate(latest_run).model_dump(mode="json")
            if scheduled:
                age = (datetime.now(UTC) - scheduled.completed_at).total_seconds()
                scheduler = (
                    "recent delivery"
                    if age < get_settings().diagnostic_interval_seconds * 2 + 10
                    else "stale"
                )
    except Exception as exc:
        logger.warning("Database health probe failed (%s)", type(exc).__name__)
    try:
        with Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            if client.ping():
                checks["broker"] = "up"
    except Exception as exc:
        logger.warning("Broker health probe failed (%s)", type(exc).__name__)
    if checks["broker"] == "up":
        try:
            replies = celery_app.control.inspect(timeout=1).ping() or {}
            if any(reply.get("ok") == "pong" for reply in replies.values()):
                checks["worker"] = "up"
        except Exception as exc:
            logger.warning("Worker health probe failed (%s)", type(exc).__name__)
    return {
        "status": "ok" if all(value == "up" for value in checks.values()) else "degraded",
        "checks": checks,
        "scheduler": scheduler,
        "diagnostic_interval_seconds": get_settings().diagnostic_interval_seconds,
        "latest_diagnostic": latest,
        "checked_at": datetime.now(UTC).isoformat(),
    }
