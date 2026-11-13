"""Shared test configuration."""

import os

import pytest

from app.config import LEGACY_PATTERN, LEGACY_VARIABLES, libpq_variables

# Tests never inherit legacy or foreign configuration (a copied .env, a deployment shell).
for _name in [k for k in os.environ if k in LEGACY_VARIABLES or LEGACY_PATTERN.search(k)]:
    del os.environ[_name]
# The same for PostgreSQL client variables of a developer shell (the loader refuses them).
for _name in libpq_variables(os.environ):
    del os.environ[_name]

# Modules such as app.celery_app read settings at import. Give unit tests a synthetic,
# test-only identity unless the environment (for example the CI stack) provides one.
os.environ.setdefault("NEXTUP_ENV", "test")
if not any(
    k in os.environ
    for k in ("NEXTUP_DATABASE_URL", "NEXTUP_DATABASE_URL_FILE", "NEXTUP_DB_HOST", "NEXTUP_DB_NAME")
):
    os.environ.update(
        NEXTUP_DB_HOST="postgres",
        NEXTUP_DB_NAME="nextup_ci",
        NEXTUP_DB_USER="nextup_ci_app",
    )
    if not any(k in os.environ for k in ("NEXTUP_DB_PASSWORD", "NEXTUP_DB_PASSWORD_FILE")):
        os.environ["NEXTUP_DB_PASSWORD"] = "unit_test_only_not_a_real_password"

# A developer's live Google credentials must never shape test settings; the suites build
# their own Settings(...) and mock every provider call.
GOOGLE_ENV = tuple(
    prefix + name
    for prefix in ("NEXTUP_", "")
    for name in (
        "GMAIL_SYNC_ENABLED",
        "CALENDAR_SYNC_ENABLED",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "GMAIL_SYNC_INTERVAL_SECONDS",
        "CALENDAR_SYNC_INTERVAL_SECONDS",
    )
) + tuple(
    f"NEXTUP_{n}_FILE"
    for n in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
)


@pytest.fixture(autouse=True)
def _isolate_google_env(monkeypatch):
    for key in GOOGLE_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _fresh_settings():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
