from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.health import probe_health


@pytest.fixture
def probes(monkeypatch):
    session = MagicMock()
    session.scalar.return_value = None
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr("app.health.Session", factory)
    monkeypatch.setattr("app.health.get_engine", lambda: None)
    redis = MagicMock()
    redis.return_value.__enter__.return_value.ping.return_value = True
    monkeypatch.setattr("app.health.Redis.from_url", redis)
    inspect = MagicMock()
    inspect.return_value.ping.return_value = {"worker@test": {"ok": "pong"}}
    monkeypatch.setattr("app.health.celery_app.control.inspect", inspect)
    return session, redis, inspect


@pytest.mark.parametrize("interval", [60, 120])
def test_reports_real_probe_results(probes, monkeypatch, interval):
    monkeypatch.setattr(
        "app.health.get_settings", lambda: Settings(diagnostic_interval_seconds=interval)
    )
    result = probe_health()
    assert result["status"] == "ok"
    assert result["scheduler"] == "waiting"
    assert result["latest_diagnostic"] is None
    assert result["diagnostic_interval_seconds"] == interval


def test_missing_worker_is_degraded(probes):
    probes[2].return_value.ping.return_value = None
    result = probe_health()
    assert result["status"] == "degraded"
    assert result["checks"]["worker"] == "down"


def test_database_error_is_degraded(probes):
    probes[0].scalar.side_effect = ConnectionError()
    assert probe_health()["checks"]["database"] == "down"


def test_broker_error_skips_worker_probe(probes):
    probes[1].side_effect = ConnectionError()
    result = probe_health()
    assert result["checks"]["broker"] == "down"
    assert result["checks"]["worker"] == "down"
    probes[2].assert_not_called()


@pytest.mark.parametrize("age,expected", [(10, "recent delivery"), (10000, "stale")])
def test_scheduler_freshness(probes, age, expected):
    scheduled = MagicMock(completed_at=datetime.now(UTC) - timedelta(seconds=age))
    probes[0].scalar.side_effect = [None, scheduled]
    assert probe_health()["scheduler"] == expected
