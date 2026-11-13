"""Run real Alembic CLI upgrades/downgrades only in newly owned synthetic databases.

Every upgrade/downgrade is authorized exactly like production: a read-only guard
plan in this process, then ``python -m alembic -x nextup_token=stdin`` with the token on
standard input (never an argument; single use, bound to the database state).
``alembic check`` is read-only and needs no token. Downgrade to
``base`` cannot be authorized (no lineage revision), so the 0001 round trip is covered by
INIT plus the head <-> 0001 chain, and a test proves the refusal.
"""

import os
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import integration_db
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app import guard
from app.guard.errors import GuardRefused

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1", reason="Requires PostgreSQL with CREATEDB"
)
PAIRS = [(f"{n:04d}", f"{n - 1:04d}" if n > 1 else "base") for n in range(1, 30)]
# Downgrade to base is not authorizable; 0001 is covered by INIT and the head <-> 0001 chain.
ROUND_TRIPS = PAIRS[1:]
TABLES = {
    "career_settings": (11, "id preferences checked_at worker status"),
    "pursuits": (
        11,
        "id job_key job stage notes application_draft outreach_draft "
        "next_action_on created_by version applied_at created_at updated_at",
    ),
    "pursuit_events": (11, "id pursuit_id message created_at"),
    "discovery_settings": (9, "id enabled interval_hours min_score boards next_run_at last_run_at"),
    "diagnostic_runs": (1, "id source status created_at completed_at worker result"),
    "profiles": (2, "id skills target_titles location work_preferences created_at updated_at"),
    "job_fetches": (
        3,
        "id source status query created_at started_at completed_at worker "
        "received_count stored_count skipped_count error_code error_message",
    ),
    "jobs": (3, "source external_id title company location description url posted_at fetched_at"),
    "saved_searches": (6, "id name name_key source include_expired filters created_at updated_at"),
    "job_alerts": (7, "id search_id job_key search_name job created_at read_at"),
    "campaigns": (
        13,
        "id campaign_key title start_date end_date timezone "
        "daily_capacity_minutes preferences is_active created_at updated_at",
    ),
    "campaign_tasks": (
        13,
        "id campaign_id seed_key title category status priority due_date "
        "estimated_minutes depends_on suggested_after completion_criteria "
        "notes pursuit_id completed_at created_at updated_at",
    ),
    "evidence": (
        14,
        "id seed_key topic detail verification_status source scope dates "
        "personal_contribution permitted_wording instruction created_at updated_at",
    ),
    "resume_versions": (
        14,
        "id variant_name content version_number is_active notes created_at updated_at",
    ),
    "content_items": (
        15,
        "id seed_key kind state topic title body outline "
        "campaign_task_id published_at public_url notes created_at updated_at",
    ),
    "contacts": (
        16,
        "id name company title email phone linkedin_url relationship "
        "notes do_not_contact introduced_by last_contacted_at created_at updated_at",
    ),
    "communications": (
        16,
        "id contact_id pursuit_id campaign_task_id channel direction "
        "subject body status sent_at received_at notes created_at updated_at",
    ),
    "follow_up_rules": (
        16,
        "id rule_key trigger delay_business_days action "
        "contact_required_for_outreach enabled config created_at updated_at",
    ),
    "email_classifications": (
        29,
        "gmail_message_id thread_id classification companies company_id confidence model "
        "prompt_version classified_at applied_at",
    ),
    "job_ratings": (
        28,
        "id job_key source external_id title company rating created_at updated_at",
    ),
    "companies": (
        27,
        "id name name_normalized aliases domains status notes created_at updated_at",
    ),
    "correspondence_sync_settings": (
        21,
        "id enabled query max_messages_per_run cursor_epoch last_run_at "
        "last_status last_error last_imported updated_at",
    ),
}
ADDED = {
    4: {"jobs": "dedupe_key date_kind"},
    5: {"jobs": "score score_breakdown score_signature"},
    7: {
        "saved_searches": (
            "alerts_enabled alert_min_score alert_check_status alert_checked_at alert_worker"
        )
    },
    8: {
        "diagnostic_runs": ("recovery_deadline last_dispatched_at delivery_attempts error_message"),
        "job_fetches": (
            "recovery_deadline last_dispatched_at delivery_attempts "
            "execution_token lease_expires_at"
        ),
    },
    9: {"job_fetches": "board_key"},
    10: {"discovery_settings": "match_preferences"},
    12: {
        "pursuits": "prep_data offer_data",
        "career_settings": "application_template outreach_template",
    },
    17: {
        "pursuit_events": "event_date actor source evidence",
    },
    18: {
        "pursuit_events": "attachments",
    },
    20: {
        "content_items": "target_date series",
    },
    21: {
        "communications": "source source_id thread_id sender suggested_pursuit_id",
    },
    22: {
        "correspondence_sync_settings": (
            "calendar_enabled calendar_lookahead_days calendar_last_run_at "
            "calendar_last_status calendar_last_error calendar_last_imported"
        ),
    },
    24: {
        "resume_versions": "file_name file_type file_size file_uploaded_at file_data",
        "pursuits": "resume_version_id",
    },
    25: {"campaign_tasks": "communication_id"},
    26: {
        "communications": "detection",
        "correspondence_sync_settings": "auto_create_applications",
    },
    27: {"pursuits": "company_id", "contacts": "company_id"},
}
DIAGNOSTIC_ID = "11111111-1111-4111-8111-111111111111"
FETCH_ID = "22222222-2222-4222-8222-222222222222"
SEARCH_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def migration_database():
    # The owner (CREATEDB in CI only) creates and later drops only a newly generated
    # database; no IF EXISTS, FORCE, role grants or schema fallback.
    name = integration_db.create_database()
    settings = integration_db.database_settings(name)
    engine = guard.migration_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_database()")) == name
            assert (
                connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'"))
                == 0
            )
        yield engine
    finally:
        engine.dispose()
        integration_db.drop_database(name)


def cli(engine, action, target=None, expected_error=None):
    # Do not expose a generic downgrade helper that can target the working database.
    name = engine.url.database or ""
    if not re.fullmatch(r"nextup_migration_test_[0-9a-f]{32}", name):
        raise RuntimeError("Refusing migration outside a generated test database")
    with engine.connect() as connection:
        if connection.scalar(text("SELECT current_database()")) != name:
            raise RuntimeError("Connected database does not match the owned test database")
    args = [sys.executable, "-m", "alembic"]
    token = None
    if action in ("upgrade", "downgrade"):
        # Same authorization as production: plan (read-only) -> single-use token -> apply.
        _, token = integration_db.plan_token(
            name, operation=action, target=None if target == "head" else target
        )
        if token is None:
            assert expected_error is None, "Nothing to apply, so nothing could be refused"
            return
        args += ["-x", "nextup_token=stdin"]  # the token itself travels on stdin
    args.append(action)
    if target is not None:
        args.append(target)
    # The password stays a file (NEXTUP_DB_PASSWORD_FILE); only the database name differs.
    assert token is None or not any(token in arg for arg in args)
    result = subprocess.run(
        args,
        env={**os.environ, "NEXTUP_DB_NAME": name},
        input="" if token is None else token + "\n",
        capture_output=True,
        text=True,
        timeout=45,
    )
    if expected_error is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, "Unsafe downgrade unexpectedly succeeded"
        assert expected_error in result.stdout + result.stderr


def execute(engine, statement, **parameters):
    with engine.begin() as connection:
        connection.execute(text(statement), parameters)


def snapshot(engine):
    with engine.connect() as connection:
        names = (
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            )
            .scalars()
            .all()
        )
        # The guard's marker and ledger are not application tables (the ledger gains a row
        # per authorized apply, so it is excluded from round-trip comparisons).
        names = [name for name in names if name not in guard.GUARD_TABLES]
        assert set(names) <= {*TABLES, "alembic_version"}
        rows = {
            name: connection.execute(
                text(f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text')
            )
            .scalars()
            .all()
            for name in names
        }
        definitions = {}
        for name, query in {
            "columns": "SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod), "
            "a.attnotnull,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid=a.attrelid "
            "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
            "WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' "
            "AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attname",
            "constraints": "SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid) "
            "FROM pg_constraint WHERE connamespace='public'::regnamespace "
            "ORDER BY conrelid::regclass::text,conname",
            "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename,indexname",
        }.items():
            definitions[name] = [tuple(row) for row in connection.execute(text(query))]
        return {"rows": rows, **definitions}


def assert_revision(engine, revision):
    state = snapshot(engine)
    assert state["rows"]["alembic_version"] == (
        [] if revision == "base" else [{"version_num": revision}]
    )
    number = 0 if revision == "base" else int(revision)
    expected = {
        name: set(columns.split())
        for name, (introduced, columns) in TABLES.items()
        if introduced <= number
    }
    for introduced, tables in ADDED.items():
        if introduced <= number:
            for name, columns in tables.items():
                expected[name].update(columns.split())
    assert set(state["rows"]) == {*expected, "alembic_version"}
    for table, columns in expected.items():
        assert {row[1] for row in state["columns"] if row[0] == table} == columns


def seed_company_sources(engine):
    """Pursuits and contacts whose company spellings 0027 must collapse and link."""
    for key, company, applied in (
        ("acme-1", "Acme Robotics, Inc.", "2026-10-01T12:00:00Z"),
        ("acme-2", "ACME Robotics", None),
        ("globex-1", "The Globex Corporation", None),
        ("blank-1", "  ", None),
        ("adzuna-1", "Company not provided", None),
    ):
        execute(
            engine,
            "INSERT INTO pursuits (id,job_key,job,stage,created_by,applied_at,created_at)"
            " VALUES (gen_random_uuid(),:key,jsonb_build_object('company',CAST(:company AS text),"
            "'title','Synthetic role'),'review','manual',CAST(:applied AS timestamptz),"
            "'2026-09-01T00:00:00Z')",
            key=key,
            company=company,
            applied=applied,
        )
    for name, company in (
        ("Riley", "Acme Robotics"),
        ("Sam", "Initech LLC"),
        ("Pat", "Initech"),
        ("Lee", "Initech"),
        ("Kim", None),
    ):
        execute(
            engine,
            "INSERT INTO contacts (id,name,company,created_at)"
            " VALUES (gen_random_uuid(),:name,:company,'2026-09-02T00:00:00Z')",
            name=name,
            company=company,
        )


def seed_legacy(engine, revision):
    """Synthetic rows valid at the old revision, independent of current ORM models."""
    number = 0 if revision == "base" else int(revision)
    if number == 26:
        seed_company_sources(engine)
    if number >= 1:
        execute(
            engine,
            "INSERT INTO diagnostic_runs (id,source,status,result) "
            "VALUES (:id,'manual','succeeded','{\"message\":\"synthetic history\"}')",
            id=DIAGNOSTIC_ID,
        )
    if number >= 2:
        execute(
            engine,
            "INSERT INTO profiles (id,skills,target_titles,location,work_preferences) "
            "VALUES (1,ARRAY['Python','SQL'],ARRAY['Example role'],'Example city',ARRAY['remote'])",
        )
    if number >= 3:
        execute(
            engine,
            "INSERT INTO job_fetches (id,source,status,query,received_count,stored_count) "
            "VALUES (:id,'adzuna','succeeded','{\"what\":\"Synthetic QA\"}',2,2)",
            id=FETCH_ID,
        )
        extra_columns = ",dedupe_key,date_kind" if number >= 4 else ""
        extra_values = ",'synthetic-identity','posted'" if number >= 4 else ""
        execute(
            engine,
            "INSERT INTO jobs (source,external_id,title,company,location,description,url,posted_at"
            f"{extra_columns}) VALUES ('adzuna','migration-example','Synthetic QA',"
            "'Example Company',"
            "'Example City','Synthetic description','https://example.invalid/role','2026-10-01T12:00:00Z'"
            f"{extra_values})",
        )
    if number >= 6:
        execute(
            engine,
            "INSERT INTO saved_searches (id,name,name_key,source,include_expired,filters) "
            "VALUES (:id,'Synthetic search','synthetic search','adzuna',false,'{\"q\":\"QA\"}')",
            id=SEARCH_ID,
        )


@pytest.mark.parametrize("revision,previous", ROUND_TRIPS)
def test_each_revision_round_trip_preserves_compatible_data(migration_database, revision, previous):
    engine = migration_database
    cli(engine, "upgrade", previous)
    seed_legacy(engine, previous)
    assert_revision(engine, previous)
    before = snapshot(engine)
    cli(engine, "upgrade", revision)
    assert_revision(engine, revision)
    upgraded = snapshot(engine)
    # Every old field/row must survive the upgrade; new columns may have backfilled values.
    for table, rows in before["rows"].items():
        if table != "alembic_version" and rows:
            fields = rows[0].keys()
            assert [{key: row[key] for key in fields} for row in upgraded["rows"][table]] == rows
    cli(engine, "downgrade", previous)
    assert snapshot(engine) == before
    cli(engine, "upgrade", revision)
    assert snapshot(engine) == upgraded


def test_empty_database_full_chain_and_model_agreement(migration_database):
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["0029"], "Extend the migration expectations for the new head"
    assert [
        (r.revision, r.down_revision or "base") for r in reversed(list(scripts.walk_revisions()))
    ] == PAIRS
    cli(migration_database, "upgrade", "head")
    assert_revision(migration_database, "0029")
    head = snapshot(migration_database)
    cli(migration_database, "downgrade", "0001")
    assert_revision(migration_database, "0001")
    cli(migration_database, "upgrade", "head")
    assert snapshot(migration_database) == head
    cli(migration_database, "check")


def test_guard_refuses_downgrade_to_base_and_unauthorized_cli_writes(migration_database):
    engine = migration_database
    cli(engine, "upgrade", "0002")
    before = snapshot(engine)
    with pytest.raises(GuardRefused) as caught:
        integration_db.plan_token(engine.url.database, operation="downgrade", target="base")
    assert caught.value.code == "NXG-L01"
    for args in (["downgrade", "base"], ["upgrade", "head"], ["stamp", "head"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env={**os.environ, "NEXTUP_DB_NAME": engine.url.database},
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode != 0 and "NXG-A01" in result.stdout + result.stderr
    assert snapshot(engine) == before


BLOCKERS = [
    ("0004", "jobs_greenhouse", "Cannot downgrade while Greenhouse records exist"),
    ("0004", "jobs_sample_greenhouse", "Cannot downgrade while Greenhouse records exist"),
    ("0004", "fetch_greenhouse", "Cannot downgrade while Greenhouse records exist"),
    ("0004", "fetch_sample_greenhouse", "Cannot downgrade while Greenhouse records exist"),
    ("0006", "saved_search", "Saved searches exist"),
    ("0007", "enabled_alerts", "Alert data exists"),
    ("0007", "inbox", "Alert data exists"),
    ("0008", "diagnostic_recovery", "Recovery history exists"),
    ("0008", "fetch_recovery", "Recovery history exists"),
    ("0008", "failed_diagnostic", "Failed diagnostic history exists"),
    ("0028", "job_rating", "Cannot downgrade while job ratings exist"),
]


def add_blocker(engine, kind):
    if kind.startswith("jobs_"):
        execute(engine, "UPDATE jobs SET source=:source", source=kind.removeprefix("jobs_"))
    elif kind.startswith("fetch_") and kind != "fetch_recovery":
        execute(engine, "UPDATE job_fetches SET source=:source", source=kind.removeprefix("fetch_"))
    elif kind == "enabled_alerts":
        execute(engine, "UPDATE saved_searches SET alerts_enabled=true")
    elif kind == "inbox":
        execute(
            engine,
            "INSERT INTO job_alerts (id,search_id,job_key,search_name,job,read_at) "
            "VALUES (:id,:search_id,'synthetic-key','Synthetic search',"
            '\'{"title":"Synthetic role"}\',now())',
            id=uuid4(),
            search_id=SEARCH_ID,
        )
    elif kind in ("diagnostic_recovery", "fetch_recovery"):
        table = "diagnostic_runs" if kind == "diagnostic_recovery" else "job_fetches"
        execute(
            engine,
            f"UPDATE {table} SET recovery_deadline=now(),"
            "delivery_attempts=2,last_dispatched_at=now()",
        )
    elif kind == "job_rating":
        execute(
            engine,
            "INSERT INTO job_ratings (id,job_key,source,external_id,title,company,rating)"
            " VALUES (:id,'synthetic-identity','adzuna','migration-example','Synthetic QA',"
            "'Example Company',1)",
            id=uuid4(),
        )
    elif kind == "failed_diagnostic":
        execute(
            engine, "UPDATE diagnostic_runs SET status='failed',error_message='Synthetic failure'"
        )
    else:
        assert kind == "saved_search"  # seed_legacy already supplied the blocking row


@pytest.mark.parametrize("revision,blocker,message", BLOCKERS)
def test_guarded_downgrade_preserves_schema_rows_and_version(
    migration_database, revision, blocker, message
):
    engine = migration_database
    cli(engine, "upgrade", revision)
    seed_legacy(engine, revision)
    add_blocker(engine, blocker)
    before = snapshot(engine)
    cli(engine, "downgrade", f"{int(revision) - 1:04d}", expected_error=message)
    assert snapshot(engine) == before


def test_later_guard_rolls_back_earlier_downgrades_in_same_cli_transaction(migration_database):
    engine = migration_database
    cli(engine, "upgrade", "head")
    seed_legacy(engine, "0008")
    before = snapshot(engine)
    # 0008 and 0007 perform DDL before 0006 refuses to drop the saved search.
    cli(engine, "downgrade", "0005", expected_error="Saved searches exist")
    assert snapshot(engine) == before
    cli(engine, "check")


def test_old_constraints_are_restored_and_new_constraints_return_after_reupgrade(
    migration_database,
):
    engine = migration_database
    cli(engine, "upgrade", "0007")
    seed_legacy(engine, "0007")
    for revision in ("0007", "0008", "0007", "0008"):
        with engine.connect() as connection:
            current = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if current != revision:
            cli(engine, "upgrade" if revision > current else "downgrade", revision)
        # Always roll back these probe writes so they cannot become rollback blockers.
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                statement = text("UPDATE diagnostic_runs SET status='failed'")
                if revision == "0007":
                    with pytest.raises(IntegrityError):
                        connection.execute(statement)
                else:
                    connection.execute(statement)
            finally:
                transaction.rollback()
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("UPDATE job_fetches SET status='queued'"))
                with pytest.raises(IntegrityError):
                    connection.execute(
                        text(
                            "INSERT INTO job_fetches (id,source,status,query) "
                            "VALUES (:id,'adzuna','running','{}')"
                        ),
                        {"id": uuid4()},
                    )
            finally:
                transaction.rollback()
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                if revision == "0008":
                    connection.execute(
                        text(
                            "UPDATE job_fetches SET status='publish_failed',recovery_deadline=now()"
                        )
                    )
                else:
                    connection.execute(text("UPDATE job_fetches SET status='publish_failed'"))
                statement = text(
                    "INSERT INTO job_fetches (id,source,status,query) "
                    "VALUES (:id,'adzuna','queued','{}')"
                )
                if revision == "0008":
                    with pytest.raises(IntegrityError):
                        connection.execute(statement, {"id": uuid4()})
                else:
                    connection.execute(statement, {"id": uuid4()})
            finally:
                transaction.rollback()
    cli(engine, "upgrade", "head")
    cli(engine, "check")


# 0001 -> base is not authorizable (see ROUND_TRIPS); the early destructive pairs are 0002 and 0003.
@pytest.mark.parametrize("revision,previous", PAIRS[1:3])
def test_early_destructive_downgrades_drop_only_their_tables(
    migration_database, revision, previous
):
    engine = migration_database
    cli(engine, "upgrade", revision)
    seed_legacy(engine, revision)
    before = snapshot(engine)
    removed = {name for name, (introduced, _) in TABLES.items() if introduced == int(revision)}
    assert all(before["rows"][table] for table in removed)
    cli(engine, "downgrade", previous)
    assert_revision(engine, previous)
    downgraded = snapshot(engine)
    for table, rows in downgraded["rows"].items():
        if table != "alembic_version":
            assert rows == before["rows"][table]
    cli(engine, "upgrade", revision)
    assert_revision(engine, revision)
    upgraded = snapshot(engine)
    assert all(upgraded["rows"][table] == [] for table in removed)
    for table, rows in before["rows"].items():
        if table not in removed and table != "alembic_version":
            assert upgraded["rows"][table] == rows


def test_score_cache_is_lost_but_source_and_profile_data_survive(migration_database):
    engine = migration_database
    cli(engine, "upgrade", "0005")
    seed_legacy(engine, "0005")
    execute(
        engine,
        "UPDATE jobs SET score=88,score_breakdown=CAST(:breakdown AS jsonb),"
        "score_signature='synthetic-signature'",
        breakdown='{"synthetic":88}',
    )
    before = snapshot(engine)
    cli(engine, "downgrade", "0004")
    assert_revision(engine, "0004")
    cli(engine, "upgrade", "0005")
    after = snapshot(engine)
    for row in before["rows"]["jobs"]:
        row.update(score=None, score_breakdown=None, score_signature=None)
    assert after == before


def test_cli_refuses_working_database_before_connection_or_subprocess(monkeypatch):
    connect = Mock(side_effect=AssertionError("Must not connect"))
    run = Mock(side_effect=AssertionError("Must not execute Alembic"))
    monkeypatch.setattr(subprocess, "run", run)
    engine = SimpleNamespace(
        url=make_url("postgresql+psycopg://example@postgres/otherapp"), connect=connect
    )
    with pytest.raises(RuntimeError, match="Refusing migration"):
        cli(engine, "downgrade", "base")
    connect.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("blocker", ["settings", "job", "fetch", "search", "board"])
def test_discovery_downgrade_refuses_new_data_without_changes(migration_database, blocker):
    engine = migration_database
    cli(engine, "upgrade", "head")
    seed_legacy(engine, "0009")
    if blocker == "settings":
        execute(engine, "INSERT INTO discovery_settings (id,boards) VALUES (1,'[]')")
        message = "Discovery configuration exists"
    elif blocker == "board":
        execute(engine, "UPDATE job_fetches SET board_key='synthetic-employer'")
        message = "Employer fetch history exists"
    else:
        table = {"job": "jobs", "fetch": "job_fetches", "search": "saved_searches"}[blocker]
        execute(engine, f"UPDATE {table} SET source='lever'")
        message = "Discovery source data exists"
    before = snapshot(engine)
    cli(engine, "downgrade", "0008", expected_error=message)
    assert snapshot(engine) == before


@pytest.mark.parametrize("blocker", ["settings", "search"])
def test_match_preferences_downgrade_preserves_protected_data(migration_database, blocker):
    engine = migration_database
    cli(engine, "upgrade", "0010")
    seed_legacy(engine, "0010")
    if blocker == "settings":
        execute(
            engine,
            "INSERT INTO discovery_settings (id,boards,match_preferences) "
            "VALUES (1,'[]',CAST(:rules AS jsonb))",
            rules='{"locations":["US"]}',
        )
        message = "Match preferences exist"
    else:
        execute(
            engine,
            "UPDATE saved_searches SET filters=CAST(:filters AS jsonb)",
            filters='{"discovery_only":true}',
        )
        message = "Discovery-filter searches exist"
    before = snapshot(engine)
    cli(engine, "downgrade", "0009", expected_error=message)
    assert snapshot(engine) == before


def test_default_preferences_upgrade_preserves_existing_discovery_schedule(migration_database):
    engine = migration_database
    cli(engine, "upgrade", "0009")
    execute(
        engine,
        "INSERT INTO discovery_settings (id,boards,enabled,next_run_at) "
        "VALUES (1,'[]',true,'2026-11-01T12:00:00Z')",
    )
    before = snapshot(engine)
    cli(engine, "upgrade", "0010")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT match_preferences FROM discovery_settings")) == {}
    cli(engine, "downgrade", "0009")
    assert snapshot(engine) == before


@pytest.mark.parametrize("kind", ["settings", "draft", "event"])
def test_career_downgrade_refuses_saved_work(migration_database, kind):
    engine = migration_database
    cli(engine, "upgrade", "head")
    if kind == "settings":
        execute(engine, "INSERT INTO career_settings (id,preferences) VALUES (1,'{}')")
    else:
        execute(
            engine,
            "INSERT INTO pursuits (id,job_key,job,created_by,application_draft) "
            "VALUES (:id,'synthetic','{}','manual','Keep my draft')",
            id=SEARCH_ID,
        )
        if kind == "event":
            execute(
                engine,
                "INSERT INTO pursuit_events (id,pursuit_id,message) "
                "VALUES (:id,:parent,'Synthetic activity')",
                id=uuid4(),
                parent=SEARCH_ID,
            )
    before = snapshot(engine)
    cli(engine, "downgrade", "0010", expected_error="Career workspace data exists")
    assert snapshot(engine) == before


def test_companies_backfill_collapses_spellings_links_rows_and_is_repeatable(migration_database):
    engine = migration_database
    cli(engine, "upgrade", "0026")
    seed_company_sources(engine)
    cli(engine, "upgrade", "0027")
    with engine.connect() as connection:
        companies = {
            row.name_normalized: row
            for row in connection.execute(
                text("SELECT id, name, name_normalized, aliases, status, created_at FROM companies")
            )
        }
        assert set(companies) == {"acme robotics", "globex", "initech"}, "blank and placeholder"
        acme = companies["acme robotics"]
        # Three spellings collapse; the pursuit spelling wins the tie and the rest are aliases.
        assert acme.name == "Acme Robotics, Inc." and acme.status == "applied"
        assert acme.aliases == ["Acme Robotics"]
        assert companies["globex"].name == "The Globex Corporation"
        assert companies["globex"].status == "tracking" and companies["globex"].aliases == []
        initech = companies["initech"]
        assert initech.name == "Initech" and initech.aliases == ["Initech LLC"]
        assert initech.status == "contact_only"
        assert str(initech.created_at.date()) == "2026-09-02", "first seen, not migration time"
        linked = dict(
            connection.execute(
                text(
                    "SELECT job->>'company', company_id FROM pursuits"
                    " UNION ALL SELECT coalesce(company, '<none>'), company_id FROM contacts"
                )
            ).all()
        )
        assert linked["ACME Robotics"] == linked["Acme Robotics, Inc."] == acme.id
        assert linked["Acme Robotics"] == acme.id and linked["Initech LLC"] == initech.id
        assert linked["  "] is None and linked["Company not provided"] is None
        assert linked["<none>"] is None
        before = snapshot(engine)

    # Running the backfill again changes nothing.
    module = ScriptDirectory.from_config(Config("alembic.ini")).get_revision("0027").module
    with engine.begin() as connection:
        for statement in (module.BACKFILL, module.LINK, module.STATUS):
            connection.execute(text(statement))
    assert snapshot(engine) == before
    cli(engine, "downgrade", "0026")
    cli(engine, "upgrade", "0027")
    assert snapshot(engine) == before, "ids and timestamps are deterministic"


def test_normalize_function_matches_the_python_mirror(migration_database):
    from app.companies import normalize_company_name

    cli(migration_database, "upgrade", "0027")
    samples = [
        "The Harlow Northwind Corporation",
        "Harlow Northwind Corp.",
        "R.J. Marlowe Finch & Co.",
        "Q&R Inc",
        "O'Fallowmere Media, LLC",
        "Alder  &  Birch Global Ltd",
        "Smith-Jones Holdings Co., Ltd.",
        "the",
        "The Co",
        "Inc",
        "Tradeco Wholesale",
        "Bélanor S.A.",
        "KVL Partners",
        "foo_bar plc",
        "  spaced   out  ",
        "",
    ]
    with migration_database.connect() as connection:
        for sample in samples:
            database = connection.scalar(
                text("SELECT nextup_normalize_company(:value)"), {"value": sample}
            )
            assert database == normalize_company_name(sample), sample
