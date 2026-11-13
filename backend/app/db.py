from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import guard
from app.config import get_settings, refuse_client_environment


@lru_cache
def get_engine():
    """Runtime engine (api, worker, scheduler). The URL is a ``sqlalchemy.engine.URL``
    built from the validated identity; it is never formatted into a string. The first
    connection runs the read-only guard check; a refusal raises and nothing is served."""
    settings = get_settings()
    refuse_client_environment()  # libpq would read PG* for every parameter not passed here
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_timeout=3,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )
    guard.install_runtime_guard(engine)
    return engine


def get_session():
    with Session(get_engine()) as session:
        yield session
