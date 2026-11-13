import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import guard
from app.alerts import router as alerts_router
from app.application_intake import router as application_intake_router
from app.campaign import router as campaign_router
from app.career import router as career_router
from app.contacts import router as contacts_router
from app.content import router as content_router
from app.correspondence import router as correspondence_router
from app.db import get_session
from app.discovery_api import router as discovery_router
from app.evidence import router as evidence_router
from app.follow_up_rules import router as follow_up_router
from app.health import probe_health
from app.job_ratings import router as job_ratings_router
from app.jobs import router as jobs_router
from app.models import DiagnosticRun
from app.profiles import router as profile_router
from app.retention import router as retention_router
from app.saved_searches import router as saved_search_router
from app.schemas import DiagnosticOut
from app.seed_import import router as seed_router
from app.tasks import run_diagnostic


@asynccontextmanager
async def lifespan(_app):
    # Refuse to serve unless the database identity check passes (read-only).
    # A refusal raises GuardRefused with a fixed message; startup fails, no route is served.
    guard.check_service_startup()
    yield


app = FastAPI(title="Nextup", version="0.2.0", lifespan=lifespan)
app.include_router(profile_router)
app.include_router(jobs_router)
app.include_router(job_ratings_router)
app.include_router(saved_search_router)
app.include_router(alerts_router)
app.include_router(retention_router)
app.include_router(discovery_router)
app.include_router(career_router)
app.include_router(campaign_router)
app.include_router(evidence_router)
app.include_router(content_router)
app.include_router(contacts_router)
app.include_router(application_intake_router)
app.include_router(follow_up_router)
app.include_router(correspondence_router)
app.include_router(seed_router)
logger = logging.getLogger(__name__)
Database = Annotated[Session, Depends(get_session)]


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request, exc):
    logger.warning("Database request failed (%s)", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.get("/api/live")
def live():
    return {"status": "up"}


@app.get("/api/health")
def health():
    result = probe_health()
    return JSONResponse(status_code=200 if result["status"] == "ok" else 503, content=result)


@app.post("/api/diagnostics", response_model=DiagnosticOut, status_code=202)
def create_diagnostic(session: Database):
    from app.recovery import new_intent

    run = DiagnosticRun(id=uuid4(), source="manual", status="queued", **new_intent())
    session.add(run)
    session.commit()
    session.refresh(run)
    response = DiagnosticOut.model_validate(run)
    try:
        run_diagnostic.apply_async(task_id=str(run.id), kwargs={"source": "manual"}, retry=False)
    except Exception as exc:
        logger.warning("Diagnostic publish failed (%s)", type(exc).__name__)
        # Never overwrite a completion if publication succeeded but its acknowledgment was lost.
        session.execute(
            update(DiagnosticRun)
            .where(DiagnosticRun.id == run.id, DiagnosticRun.status == "queued")
            .values(
                status="publish_failed",
                error_message="Delivery unconfirmed; automatic recovery is pending.",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Delivery unconfirmed; automatic recovery is pending. Do not resubmit.",
                "id": str(run.id),
            },
        ) from exc
    return response


@app.get("/api/diagnostics/{run_id}", response_model=DiagnosticOut)
def get_diagnostic(run_id: UUID, session: Database):
    run = session.get(DiagnosticRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Diagnostic not found")
    return run
