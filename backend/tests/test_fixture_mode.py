"""Fixture data mode: synthetic fixtures only, never a live provider request.

Each test simulates an attempted live provider request while fixture data mode is on and
proves it is refused before any network access: injected HTTP transports record zero
requests, and owned HTTP clients are never even constructed.
"""

import json
import re
from importlib.resources import files
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from app import job_tasks, jobs
from app.config import Settings, load_settings
from app.guard.errors import ConfigError
from app.sources import adzuna, employer_boards, gmail, google_calendar, greenhouse
from app.sources.common import SourceError, require_live_requests

PASSWORD = "unit_test_only_password_0123456789"


def fixture_settings(**extra):
    # Settings built directly skip the loader's cross-checks, so every provider is tried
    # with the most permissive combination: live switch on and credentials present.
    values = dict(
        fixture_data_mode=True,
        live_job_fetch_enabled=True,
        adzuna_app_id=SecretStr("real-looking-id"),
        adzuna_app_key=SecretStr("real-looking-key"),
        gmail_sync_enabled=True,
        calendar_sync_enabled=True,
        google_oauth_client_id=SecretStr("client"),
        google_oauth_client_secret=SecretStr("secret"),
        gmail_refresh_token=SecretStr("refresh"),
    )
    values.update(extra)
    return Settings(**values)


class Recorder:
    def __init__(self):
        self.requests = []

    def client(self):
        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, json={})

        return httpx.Client(transport=httpx.MockTransport(handler))


def no_owned_clients(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("an HTTP client was constructed in fixture data mode")

    for module in (adzuna, greenhouse, employer_boards, gmail, google_calendar):
        monkeypatch.setattr(module.httpx, "Client", refuse)


PROVIDER_CALLS = {
    "adzuna": lambda s, c: adzuna.fetch_adzuna({"what": "QA", "where": "Remote"}, s, client=c),
    "greenhouse": lambda s, c: greenhouse.fetch_greenhouse(
        {"board": "example", "company": "Example"}, s, client=c
    ),
    "employer-greenhouse": lambda s, c: employer_boards.fetch_board(
        "greenhouse", "x", "X", s, client=c
    ),
    "employer-lever": lambda s, c: employer_boards.fetch_board("lever", "x", "X", s, client=c),
    "employer-ashby": lambda s, c: employer_boards.fetch_board("ashby", "x", "X", s, client=c),
    "gmail-token": lambda s, c: gmail.refresh_access_token(c, s),
    "calendar-token": lambda s, c: google_calendar.refresh_access_token(c, s),
}


@pytest.mark.parametrize("provider", sorted(PROVIDER_CALLS))
def test_live_provider_requests_are_refused_before_network_access(provider, monkeypatch):
    recorder = Recorder()
    with recorder.client() as client:
        with pytest.raises(SourceError) as caught:
            PROVIDER_CALLS[provider](fixture_settings(), client)
    assert caught.value.code == "fixture_mode"
    assert recorder.requests == []
    no_owned_clients(monkeypatch)  # the owned-client path refuses before construction too
    if not provider.endswith("-token"):
        with pytest.raises(SourceError) as caught:
            PROVIDER_CALLS[provider](fixture_settings(), None)
        assert caught.value.code == "fixture_mode"


def test_chokepoint_is_inert_outside_fixture_mode():
    require_live_requests(Settings())
    require_live_requests(Settings(live_job_fetch_enabled=True))
    with pytest.raises(SourceError):
        require_live_requests(Settings(fixture_data_mode=True))


@pytest.mark.parametrize("source", ["adzuna", "greenhouse"])
def test_worker_serves_bundled_fixtures_without_any_provider_call(source, monkeypatch):
    for name in ("fetch_adzuna", "fetch_greenhouse"):
        monkeypatch.setattr(job_tasks, name, MagicMock(side_effect=AssertionError("live call")))
    jobs_found, received, skipped = job_tasks.fixture_listings(source, {"what": "QA"})
    assert received >= 1 and skipped == 0 and jobs_found
    assert all("example.invalid" in str(job.url) for job in jobs_found)


def test_worker_never_falls_back_to_live_providers(monkeypatch):
    """fetch_and_store in fixture mode: only fixture_listings; discovery is refused outright."""
    live = MagicMock(side_effect=AssertionError("live provider called"))
    monkeypatch.setattr(job_tasks, "fetch_adzuna", live)
    monkeypatch.setattr(job_tasks, "fetch_greenhouse", live)
    monkeypatch.setattr(employer_boards, "fetch_board", live)
    monkeypatch.setattr(job_tasks, "get_settings", lambda: fixture_settings())
    monkeypatch.setattr(job_tasks, "Session", MagicMock(side_effect=AssertionError("db used")))
    for query in ({"discovery": True, "board": "x", "company": "X"},):
        with pytest.raises(SourceError) as caught:
            job_tasks.fetch_and_store(None, "run", "token", "greenhouse", query)
        assert caught.value.code == "fixture_mode"
    with pytest.raises(SourceError):
        job_tasks.fixture_listings("lever", {})
    live.assert_not_called()


def test_bundled_fixtures_are_synthetic():
    for name in job_tasks.FIXTURE_FILES.values():
        text = files("app.sources").joinpath(name).read_text()
        json.loads(text)
        hosts = set(re.findall(r"https?://([^/\"]+)", text))
        assert hosts <= {"example.invalid"}, name
    assert "synthetic" in job_tasks.FIXTURE_GREENHOUSE_COMPANY


def test_source_status_is_ready_on_fixtures_without_credentials(monkeypatch):
    settings = load_settings(
        {
            "NEXTUP_ENV": "ci",
            "NEXTUP_DB_HOST": "postgres",
            "NEXTUP_DB_NAME": "nextup_ci",
            "NEXTUP_DB_USER": "nextup_ci_app",
            "NEXTUP_DB_PASSWORD": PASSWORD,
            "NEXTUP_FIXTURE_DATA_MODE": "true",
        }
    )
    assert settings.fixture_data_mode and not settings.live_job_fetch_enabled
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    session = MagicMock()
    session.get.return_value = MagicMock(target_titles=["Head of QA"], location="Example City")
    adzuna_status = jobs.source_status(session, "adzuna")
    assert adzuna_status["ready"] and adzuna_status["query"] == {
        "what": "Head of QA",
        "where": "Example City",
    }
    greenhouse_status = jobs.source_status(session, "greenhouse")
    assert greenhouse_status["ready"]
    assert greenhouse_status["query"] == {
        "board": job_tasks.FIXTURE_GREENHOUSE_BOARD,
        "company": job_tasks.FIXTURE_GREENHOUSE_COMPANY,
    }
    session.get.return_value = None
    assert jobs.source_status(session, "adzuna")["ready"] is False


class TestConfiguration:
    def env(self, name="ci", **extra):
        prefix = {"dev": "nextup_dev", "ci": "nextup_ci", "test": "nextup_ci"}[name]
        values = {
            "NEXTUP_ENV": name,
            "NEXTUP_DB_HOST": "postgres",
            "NEXTUP_DB_NAME": prefix,
            "NEXTUP_DB_USER": f"{prefix}_app",
            "NEXTUP_DB_PASSWORD": PASSWORD,
            "NEXTUP_FIXTURE_DATA_MODE": "true",
        }
        values.update(extra)
        return values

    def refused(self, code, values):
        with pytest.raises(ConfigError) as caught:
            load_settings(values)
        assert caught.value.code == code
        return caught.value

    def test_only_ci_and_test(self):
        load_settings(self.env("ci"))
        load_settings(self.env("test"))
        self.refused("NXG-C08", self.env("dev"))

    def test_rejects_live_switch_credentials_boards_and_sync(self):
        for extra in (
            {"NEXTUP_LIVE_JOB_FETCH_ENABLED": "true"},
            {"NEXTUP_ADZUNA_APP_ID": "SENTINEL_adzuna_id"},
            {"NEXTUP_ADZUNA_APP_KEY": "SENTINEL_adzuna_key"},
            {"NEXTUP_GREENHOUSE_BOARD_TOKEN": "SENTINELboard"},
            {"NEXTUP_GREENHOUSE_COMPANY_NAME": "SENTINEL Company"},
            {
                "NEXTUP_GMAIL_SYNC_ENABLED": "true",
                "NEXTUP_GOOGLE_OAUTH_CLIENT_ID": "SENTINEL_client_id",
                "NEXTUP_GOOGLE_OAUTH_CLIENT_SECRET": "SENTINEL_client_secret",
                "NEXTUP_GMAIL_REFRESH_TOKEN": "SENTINEL_refresh_token",
            },
            {"NEXTUP_GOOGLE_OAUTH_CLIENT_ID": "SENTINEL_client_id"},
        ):
            error = self.refused("NXG-C17", self.env("ci", **extra))
            for value in extra.values():
                if value not in ("true",):
                    assert value not in str(error)

    def test_strict_boolean_and_default_off(self):
        self.refused("NXG-C14", self.env("ci", NEXTUP_FIXTURE_DATA_MODE="yes"))
        values = self.env("ci")
        values.pop("NEXTUP_FIXTURE_DATA_MODE")
        assert load_settings(values).fixture_data_mode is False
        assert Settings().fixture_data_mode is False
