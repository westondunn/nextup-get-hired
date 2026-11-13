"""Rehearse PostgreSQL recovery only inside a validated synthetic CI stack.

Catalog access uses the CI bootstrap admin over the postgres container's local
socket (no password is passed anywhere). The restored copy must reproduce every table,
including the guard's marker and ledger, and the guard must REFUSE to serve it: a
restored database is a different identity.
"""

import hashlib
import json
import re
from uuid import uuid4

from verify_failures import wait_for

# Every application table; the restore must reproduce all of them, rows and schema.
ADMIN = "nextup_ci_admin"
SOURCE = "nextup_ci"
TABLES = (
    "alembic_version",
    "nextup_environment",
    "nextup_migration_authorizations",
    "profiles",
    "diagnostic_runs",
    "jobs",
    "job_fetches",
    "saved_searches",
    "job_alerts",
    "discovery_settings",
    "career_settings",
    "pursuits",
    "pursuit_events",
    "campaigns",
    "campaign_tasks",
    "evidence",
    "resume_versions",
    "content_items",
    "contacts",
    "communications",
    "follow_up_rules",
    "correspondence_sync_settings",
    "companies",
    "job_ratings",
    "email_classifications",
)
# Tables the rehearsal writes to itself; these must carry rows to count as exercised.
EXERCISED = TABLES[:13]


def normalize_schema(definition):
    # pg_restore reparses varchar-array -> text-array casts into equivalent
    # per-element casts. Normalize only this exact form; retain literals, order,
    # predicates, uniqueness, column references, and all other SQL unchanged.
    literal = r"'(?:[^']|'')*'::character varying"
    element = rf"\({literal}\)::text"
    pattern = rf"ARRAY\[({element}(?:, {element})*)\]"

    def array_cast(match):
        values = re.sub(rf"\(({literal})\)::text", r"\1", match.group(1))
        return f"(ARRAY[{values}])::text[]"

    return re.sub(pattern, array_cast, definition)


def sql(stack, database, statement):
    return stack.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "--set=ON_ERROR_STOP=1",
        "-U",
        ADMIN,
        "-d",
        database,
        "-At",
        "-c",
        statement,
    )


def snapshot(stack, database):
    tables = sql(stack, database, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
    assert set(tables.splitlines()) == set(TABLES), "Unexpected public table set"
    result = {}
    for table in TABLES:
        # Names come only from the fixed application table list above.
        data = sql(
            stack, database, f'SELECT to_jsonb(t) FROM "{table}" t ORDER BY to_jsonb(t)::text'
        )
        count = int(sql(stack, database, f'SELECT count(*) FROM "{table}"'))
        assert count > 0 or table not in EXERCISED, f"Recovery fixture did not exercise {table}"
        result[table] = {"rows": count, "sha256": hashlib.sha256(data.encode()).hexdigest()}
    for name, query in {
        "columns": "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema='public' "
        "ORDER BY table_name, ordinal_position",
        "constraints": "SELECT conrelid::regclass, conname, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE connamespace='public'::regnamespace "
        "ORDER BY conrelid::regclass::text, conname",
        "indexes": "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname='public' ORDER BY tablename, indexname",
    }.items():
        definition = normalize_schema(sql(stack, database, query))
        result[name] = hashlib.sha256(definition.encode()).hexdigest()
    return result


def verify_recovery(stack):
    # Recheck all isolation guards before any writes or service stops.
    from verify_ci import validate_ci

    assert re.fullmatch(r"nextup-ci-[0-9a-f]{12}", stack.project), "CI project required"
    config = json.loads(
        stack.compose("--profile", "test", "--profile", "migrate", "config", "--format", "json")
    )
    assert config["name"] == stack.project
    validate_ci(
        config,
        getattr(stack, "secrets_dir", None),
        getattr(stack, "e2e_dir", None),
        getattr(stack, "expected_user", None),
    )
    fixture = json.loads(
        (stack.artifacts.parents[2] / "backend/tests/fixtures/profile.synthetic.json").read_text()
    )
    assert stack.request("/api/profile") == (200, fixture), "Synthetic profile required"

    code, search = stack.request(
        "/api/saved-searches",
        "POST",
        {
            "name": f"Recovery rehearsal {uuid4().hex[:12]}",
            "source": "adzuna",
            "filters": {"q": "Head QA"},
        },
    )
    assert code == 201
    path = f"/api/saved-searches/{search['id']}/alerts"
    assert stack.request(path, "PUT", {"enabled": True, "min_score": 0})[0] == 200
    assert stack.request(f"{path}/check", "POST")[0] == 202

    def delivered():
        status, inbox = stack.request("/api/alerts?limit=50")
        return status == 200 and any(row["search_id"] == search["id"] for row in inbox["items"])

    wait_for(delivered, "synthetic recovery alert")
    alerts = stack.request("/api/alerts?limit=50")[1]["items"]
    alert = next(row for row in alerts if row["search_id"] == search["id"])
    assert stack.request(f"/api/alerts/{alert['id']}/read", "PUT")[1]["read_at"] is not None
    print("PASS: synthetic profile, listings, saved search, and read inbox entry prepared")

    # Include actual pipeline data and its activity event in the restore rehearsal.
    assert stack.request("/api/career/preferences", "PUT", {"automatic": False})[0] == 200
    listing = stack.request("/api/jobs?source=adzuna")[1]["items"][0]
    status, pursuit = stack.request(
        "/api/career/pursuits",
        "POST",
        {"source": listing["source"], "external_id": listing["external_id"]},
    )
    assert status == 200 and pursuit["created"]
    assert stack.request("/api/career")[1]["total"] >= 1

    # This is the last CI exercise. Stop writers for exact before/after comparison;
    # the runner's finally block removes the entire synthetic project afterwards.
    stack.compose("stop", "scheduler", "frontend", "api", "worker")
    original = snapshot(stack, SOURCE)
    archive = "/tmp/nextup-recovery.dump"
    stack.check(
        "database-dump",
        "exec",
        "-T",
        "--interactive=false",
        "postgres",
        "pg_dump",
        "-U",
        ADMIN,
        "-d",
        SOURCE,
        "--format=custom",
        "--file",
        archive,
    )
    target = "nextup_restore_" + uuid4().hex[:12]
    # createdb refuses an existing name. No --clean, --create, DROP, or source overwrite.
    stack.compose("exec", "-T", "postgres", "createdb", "-U", ADMIN, "--template=template0", target)
    stack.check(
        "database-restore",
        "exec",
        "-T",
        "--interactive=false",
        "postgres",
        "pg_restore",
        "--verbose",
        "-U",
        ADMIN,
        "-d",
        target,
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        archive,
    )
    restored = snapshot(stack, target)
    differences = [name for name in original if restored[name] != original[name]]
    report = {
        "source": SOURCE,
        "restored_database": target,
        "matched": not differences,
        "differences": differences,
        "original": original,
        "snapshot": restored,
    }
    (stack.artifacts / "recovery.json").write_text(json.dumps(report, indent=2) + "\n")
    assert not differences, f"Restored rows or schema differ: {', '.join(differences)}"
    assert snapshot(stack, SOURCE) == original, "Source database changed during restore"
    # The restored copy is a different database identity: the runtime guard must refuse to
    # serve it (no adoption path exists). Runtime role only, read-only check, no secrets.
    probe = stack.compose_result(
        "run",
        "--rm",
        "--no-deps",
        "-e",
        f"NEXTUP_DB_NAME={target}",
        "--entrypoint",
        "python",
        "api",
        "-m",
        "app.guard",
        "check",
    )
    output = probe.stdout + probe.stderr
    assert probe.returncode in (3, 4), "Guard did not refuse the restored copy"
    assert "nextup-guard: " in output and "PROCEED" not in output
    print("PASS: guard refuses to serve the restored copy (identity mismatch)")
    print(
        f"PASS: PostgreSQL archive restored into a new database; all {len(TABLES)} tables"
        " and schema match"
    )
    print("PASS: source unchanged; archive and restored database stay in disposable CI container")
