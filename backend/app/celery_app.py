from celery import Celery
from celery.signals import beat_init, worker_init

from app import guard
from app.config import get_settings

# Worker and scheduler refuse (SystemExit with the guard's exit code) before
# consuming or scheduling any task unless the database identity check passes.
worker_init.connect(guard.celery_startup_check, weak=False)
beat_init.connect(guard.celery_startup_check, weak=False)

settings = get_settings()
celery_app = Celery(
    "nextup",
    broker=settings.redis_url,
    include=[
        "app.tasks",
        "app.job_tasks",
        "app.alert_tasks",
        "app.recovery",
        "app.discovery_tasks",
        "app.career_tasks",
        "app.followup_tasks",
        "app.correspondence_tasks",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    beat_schedule={
        "prepare-career-plan": {
            "task": "app.career_tasks.prepare_plan",
            "schedule": 300.0,
            "options": {"expires": 300},
        },
        "profile-job-discovery": {
            "task": "app.discovery_tasks.discover_due",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "recover-durable-work": {
            "task": "app.recovery.recover_tasks",
            "schedule": 30.0,
            "options": {"expires": 30},
        },
        "local-alert-check": {
            "task": "app.alert_tasks.check_alerts",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        "evaluate-follow-up-rules": {
            "task": "app.followup_tasks.evaluate_rules",
            "schedule": 300.0,
            "options": {"expires": 300},
        },
        "sync-gmail-correspondence": {
            "task": "app.correspondence_tasks.sync_gmail",
            "schedule": settings.gmail_sync_interval_seconds,
            "options": {"expires": settings.gmail_sync_interval_seconds},
        },
        "sync-calendar-events": {
            "task": "app.correspondence_tasks.sync_calendar",
            "schedule": settings.calendar_sync_interval_seconds,
            "options": {"expires": settings.calendar_sync_interval_seconds},
        },
        "foundation-diagnostic": {
            "task": "app.tasks.run_diagnostic",
            "schedule": settings.diagnostic_interval_seconds,
            "kwargs": {"source": "scheduler"},
            "options": {"expires": settings.diagnostic_interval_seconds},
        },
    },
)
