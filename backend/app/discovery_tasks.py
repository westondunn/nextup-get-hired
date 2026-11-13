from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.db import get_engine
from app.discovery import enqueue_discovery


@celery_app.task(bind=True, name="app.discovery_tasks.discover_due")
def discover_due(self):
    try:
        enqueue_discovery(get_engine(), automatic=True)
    except SQLAlchemyError:
        raise self.retry(
            exc=RuntimeError("Discovery storage is unavailable"), countdown=5, max_retries=3
        ) from None
