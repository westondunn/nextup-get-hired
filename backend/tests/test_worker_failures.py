"""Worker retry/error contracts without real database or provider access."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from celery.exceptions import Retry
from sqlalchemy.exc import OperationalError

from app.alert_tasks import check_alerts
from app.job_tasks import fetch_jobs
from app.models import JobFetch


@pytest.mark.parametrize(
    "task,operation",
    [
        (fetch_jobs, "app.job_tasks.execute_fetch"),
        (check_alerts, "app.alert_tasks.evaluate_alerts"),
    ],
)
def test_storage_failures_retry_with_bounded_safe_messages(monkeypatch, task, operation):
    monkeypatch.setattr(
        operation, MagicMock(side_effect=OperationalError("private SQL", {}, Exception("secret")))
    )
    retry = MagicMock(side_effect=Retry())
    monkeypatch.setattr(task, "retry", retry)
    task.push_request(id=str(uuid4()), hostname="worker@test")
    try:
        with pytest.raises(Retry):
            task.run()
    finally:
        task.pop_request()
    kwargs = retry.call_args.kwargs
    assert kwargs["max_retries"] == 3 and kwargs["countdown"] == 5
    assert "private" not in str(kwargs["exc"]) and "secret" not in str(kwargs["exc"])


@pytest.mark.parametrize("status", ["queued", "succeeded"])
def test_unexpected_fetch_failure_is_safe_and_never_overwrites_success(monkeypatch, status):
    run = JobFetch(id=uuid4(), source="adzuna", status=status, query={})
    session = MagicMock()
    session.get.return_value = run
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr("app.job_tasks.Session", factory)
    monkeypatch.setattr("app.job_tasks.get_engine", lambda: None)
    monkeypatch.setattr(
        "app.job_tasks.execute_fetch", MagicMock(side_effect=ValueError("private provider data"))
    )
    fetch_jobs.push_request(id=str(run.id), hostname="worker@test")
    try:
        fetch_jobs.run()
    finally:
        fetch_jobs.pop_request()
    if status == "succeeded":
        assert run.status == "succeeded" and run.error_message is None
    else:
        assert run.status == "failed" and run.error_code == "unexpected_error"
        assert "private" not in run.error_message
        assert run.completed_at is not None
