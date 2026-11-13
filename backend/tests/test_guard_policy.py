"""Database guard policy: pure decisions, facts parsing, lineage and
authorization. No database: facts are constructed or come from a fake query function."""

import dataclasses
import inspect
import itertools
import re
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from pydantic import SecretStr

from app.config import load_settings
from app.guard import facts as facts_module
from app.guard import lineage as lineage_module
from app.guard import plan as plan_module
from app.guard.errors import GuardRefused
from app.guard.facts import Facts, Marker, gather
from app.guard.plan import InMemoryLedger, plan, revalidate_and_consume, verify
from app.guard.policy import decide_migration, decide_runtime

LINEAGE = lineage_module.load()
SYSID = "7311234567890123456"
INSTANCE = str(uuid.uuid4())
# The stored, database-wide sentinel entry of a completely provisioned database.
PERSISTED = (("database", "nextup.provisioning=complete-v1"),)
PASSWORD = "dev_password_for_unit_tests_only_0123"


def identity(env="dev", role="runtime", instance=INSTANCE):
    # Staging forbids inline secrets, so it is built from a dev identity and then switched.
    prefix = {"dev": "nextup_dev", "staging": "nextup_dev", "ci": "nextup_ci", "test": "nextup_ci"}[
        env
    ]
    environ = {
        "NEXTUP_ENV": env,
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": prefix,
        "NEXTUP_DB_USER": f"{prefix}_{'app' if role == 'runtime' else 'owner'}",
        "NEXTUP_DB_PASSWORD": PASSWORD,
    }
    if instance:
        environ["NEXTUP_INSTANCE_ID"] = instance
    if role == "migrator":
        environ.update(NEXTUP_DB_ROLE="migrator", NEXTUP_MIGRATION_KEY="m" * 48)
    if env == "staging":
        environ["NEXTUP_ENV"] = "dev"
        built = load_settings(environ).identity
        return dataclasses.replace(
            built,
            environment="staging",
            expected_cluster="nextup-oss-stg",
            database=dataclasses.replace(
                built.database,
                name="nextup_stg",
                user=f"nextup_stg_{'app' if role == 'runtime' else 'owner'}",
            ),
        )
    return load_settings(environ).identity


def marker(ident, **changes):
    values = dict(
        environment=ident.environment,
        lineage="nextup",
        database_name=ident.database.name,
        cluster_name=ident.expected_cluster,
        system_identifier=SYSID,
        instance_id=None if ident.instance_id is None else str(ident.instance_id),
        guard_version="2a.1",
    )
    values.update(changes)
    return Marker(**values)


def initialized(ident, revision="0029", **changes):
    values = dict(
        database=ident.database.name,
        cluster_name=ident.expected_cluster,
        current_user=ident.expected_user,
        session_user=ident.expected_user,
        server_version_num=170004,
        schema="public",
        superuser=False,
        createrole=False,
        createdb=False,
        bypassrls=False,
        replication=False,
        can_create_in_database=False,
        can_create_in_schema=ident.role == "migrator",
        member_of_owner=False,
        application_tables=24,
        alembic_present=True,
        alembic_versions=(revision,),
        marker_present=True,
        markers=(marker(ident),),
        pg_trgm=True,
        classifier_role_exists=False,
        foreign_grantees=(),
        system_identifier=SYSID,
        guard_tables_writable=ident.role == "migrator",
        provisioning=facts_module.PROVISIONED,
        provisioning_persisted=PERSISTED,
    )
    values.update(changes)
    return Facts(**values)


def empty(ident, **changes):
    return initialized(
        ident,
        **{
            "application_tables": 0,
            "alembic_present": False,
            "alembic_versions": (),
            "marker_present": False,
            "markers": (),
            **changes,
        },
    )


def code(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except GuardRefused as exc:
        return exc.code
    return "PROCEED"


class Lineage(unittest.TestCase):
    def test_pinned_lineage(self):
        self.assertEqual(LINEAGE.order, tuple(f"{n:04d}" for n in range(1, 30)))
        self.assertEqual(LINEAGE.head, "0029")
        self.assertTrue(LINEAGE.crosses(None, "0029", "0029"))
        self.assertTrue(LINEAGE.crosses("0028", "0029", "0029"))
        self.assertFalse(LINEAGE.crosses("0029", "0029", "0029"))

    def copy(self):
        root = Path(tempfile.mkdtemp())
        shutil.copytree(lineage_module.MIGRATIONS / "versions", root / "versions")
        shutil.copy(lineage_module.MIGRATIONS / "LINEAGE.sha256", root / "LINEAGE.sha256")
        self.addCleanup(shutil.rmtree, root)
        return root

    def test_tampering_and_foreign_revisions_are_refused(self):
        root = self.copy()
        target = next((root / "versions").glob("0029_*.py"))
        target.write_text(target.read_text() + "\n# edited\n")
        with self.assertRaises(GuardRefused) as caught:
            lineage_module.load(root)
        self.assertEqual(caught.exception.code, "NXG-L04")

        for name, revision, down in (
            ("prv_0030_x.py", "prv_0030", "0029"),
            ("0030_x.py", "0030", "0029"),
            ("oss_0030_branch.py", "oss_0030", "0028"),
        ):
            with self.subTest(revision=revision):
                root = self.copy()
                (root / "versions" / name).write_text(
                    f'revision = "{revision}"\ndown_revision = "{down}"\n'
                )
                with self.assertRaises(GuardRefused) as caught:
                    lineage_module.load(root)
                self.assertEqual(caught.exception.code, "NXG-L04")

        root = self.copy()
        pins = (root / "LINEAGE.sha256").read_text().splitlines()
        (root / "LINEAGE.sha256").write_text("\n".join(pins[:-1]) + "\n")
        with self.assertRaises(GuardRefused):
            lineage_module.load(root)

    def test_oss_descendant_extends_the_lineage(self):
        root = self.copy()
        (root / "versions" / "oss_0030_example.py").write_text(
            'revision = "oss_0030"\ndown_revision = "0029"\n'
        )
        extended = lineage_module.load(root)
        self.assertEqual(extended.head, "oss_0030")
        self.assertNotEqual(extended.digest, LINEAGE.digest)


class Runtime(unittest.TestCase):
    def setUp(self):
        self.ident = identity()

    def test_proceeds_only_on_the_exact_identity(self):
        self.assertEqual(
            decide_runtime(initialized(self.ident), self.ident, LINEAGE).mode, "PROCEED-RUNTIME"
        )

    def test_each_mismatch_refuses_with_its_code(self):
        i = self.ident
        cases = {
            "NXG-I02": dict(database="some_other_database"),
            "NXG-I03": dict(cluster_name=""),
            "NXG-I04": dict(current_user="nextup_dev_owner", session_user="nextup_dev_owner"),
            "NXG-I05": dict(superuser=True),
            "NXG-I06": dict(server_version_num=160004),
            "NXG-I07": dict(system_identifier=None),
            "NXG-M05": dict(
                application_tables=0,
                alembic_present=False,
                alembic_versions=(),
                marker_present=False,
                markers=(),
            ),
            "NXG-M01": dict(marker_present=False, markers=()),
            "NXG-M02": dict(markers=(marker(i, environment="staging"),)),
            "NXG-M03": dict(markers=(marker(i, system_identifier="999"),)),
            "NXG-M04": dict(markers=(marker(i, instance_id=str(uuid.uuid4())),)),
            "NXG-L05": dict(markers=(marker(i), marker(i))),
            "NXG-L02": dict(alembic_versions=("0028", "0029")),
            "NXG-L01": dict(alembic_versions=("prv_0030",)),
            "NXG-L03": dict(alembic_versions=("0028",)),
            "NXG-R01": dict(classifier_role_exists=True),
            "NXG-R02": dict(foreign_grantees=("PUBLIC",)),
        }
        for expected, changes in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(
                    code(decide_runtime, initialized(i, **changes), i, LINEAGE), expected
                )

    def test_over_privileged_runtime_roles(self):
        for changes in (
            dict(createrole=True),
            dict(createdb=True),
            dict(bypassrls=True),
            dict(replication=True),
            dict(can_create_in_database=True),
            dict(can_create_in_schema=True),
            dict(member_of_owner=True),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    code(decide_runtime, initialized(self.ident, **changes), self.ident, LINEAGE),
                    "NXG-I05",
                )

    def test_set_role_does_not_count_and_migrator_cannot_serve(self):
        facts = initialized(self.ident, session_user="nextup_dev_owner")
        self.assertEqual(code(decide_runtime, facts, self.ident, LINEAGE), "NXG-I04")
        migrator = identity(role="migrator")
        self.assertEqual(code(decide_runtime, initialized(migrator), migrator, LINEAGE), "NXG-I04")

    def test_restored_dump_and_cross_environment_copies(self):
        i = self.ident
        # Same marker, different cluster (restore of a dump into another PostgreSQL instance).
        self.assertEqual(
            code(decide_runtime, initialized(i, system_identifier="111"), i, LINEAGE), "NXG-M03"
        )
        # A staging database (marker, names) reached with dev configuration.
        staging = identity("staging")
        self.assertEqual(code(decide_runtime, initialized(staging), i, LINEAGE), "NXG-I02")
        # Marker without instance while configuration pins one, and vice versa.
        self.assertEqual(
            code(
                decide_runtime, initialized(i, markers=(marker(i, instance_id=None),)), i, LINEAGE
            ),
            "NXG-M04",
        )
        unpinned = identity(instance=None)
        self.assertEqual(
            code(decide_runtime, initialized(unpinned, markers=(marker(i),)), unpinned, LINEAGE),
            "NXG-M04",
        )

    def test_generated_perturbations_never_proceed(self):
        i = self.ident
        perturbations = [
            dict(database="other"),
            dict(cluster_name="nextup-oss-stg"),
            dict(current_user="x"),
            dict(session_user="x"),
            dict(superuser=True),
            dict(createrole=True),
            dict(createdb=True),
            dict(bypassrls=True),
            dict(replication=True),
            dict(can_create_in_database=True),
            dict(can_create_in_schema=True),
            dict(member_of_owner=True),
            dict(server_version_num=150000),
            dict(system_identifier=None),
            dict(marker_present=False, markers=()),
            dict(markers=(marker(i, environment="ci"),)),
            dict(markers=(marker(i, lineage="other"),)),
            dict(markers=(marker(i, database_name="x"),)),
            dict(markers=(marker(i, cluster_name="x"),)),
            dict(markers=(marker(i, system_identifier="x"),)),
            dict(markers=(marker(i, instance_id=None),)),
            dict(alembic_present=False, alembic_versions=()),
            dict(alembic_versions=()),
            dict(alembic_versions=("0001",)),
            dict(alembic_versions=("zz",)),
            dict(classifier_role_exists=True),
            dict(foreign_grantees=("intruder",)),
        ]
        combos = 0
        for size in (1, 2):
            for chosen in itertools.combinations(perturbations, size):
                changes = {}
                for item in chosen:
                    changes.update(item)
                combos += 1
                with self.subTest(changes=sorted(changes)):
                    self.assertNotEqual(
                        code(decide_runtime, initialized(i, **changes), i, LINEAGE), "PROCEED"
                    )
        self.assertGreater(combos, 350)


class Migration(unittest.TestCase):
    def setUp(self):
        self.ident = identity(role="migrator")

    def test_empty_database_bootstraps(self):
        decision = decide_migration(empty(self.ident), self.ident, LINEAGE)
        self.assertEqual(
            (decision.mode, decision.from_revision, decision.target), ("INIT", None, "0029")
        )
        self.assertEqual(len(decision.steps), 29)
        self.assertEqual(decision.data_changing_steps, ("0004", "0019", "0025", "0027", "0029"))

    def test_bootstrap_preconditions(self):
        i = self.ident
        self.assertEqual(code(decide_migration, empty(i, pg_trgm=False), i, LINEAGE), "NXG-I08")
        self.assertEqual(
            code(decide_migration, empty(i, classifier_role_exists=True), i, LINEAGE), "NXG-R01"
        )
        self.assertEqual(
            code(decide_migration, empty(i, system_identifier=None), i, LINEAGE), "NXG-I07"
        )
        self.assertEqual(
            code(decide_migration, empty(i, foreign_grantees=("n8n",)), i, LINEAGE), "NXG-R02"
        )
        # INIT up to 0028 does not cross the granting revision.
        self.assertEqual(
            decide_migration(empty(i, classifier_role_exists=True), i, LINEAGE, target="0028").mode,
            "INIT",
        )

    def test_unknown_populated_database_is_refused(self):
        i = self.ident
        for changes in (
            dict(application_tables=3),
            dict(alembic_present=True, alembic_versions=("0029",)),
            dict(application_tables=0, alembic_present=True, alembic_versions=()),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(code(decide_migration, empty(i, **changes), i, LINEAGE), "NXG-M01")
        self.assertEqual(
            code(
                decide_migration,
                initialized(i, alembic_present=False, alembic_versions=()),
                i,
                LINEAGE,
            ),
            "NXG-L05",
        )

    def test_upgrade_noop_and_grant_crossing(self):
        i = self.ident
        decision = decide_migration(initialized(i, "0027"), i, LINEAGE)
        self.assertEqual((decision.mode, decision.steps), ("UPGRADE", ("0028", "0029")))
        self.assertEqual(decide_migration(initialized(i), i, LINEAGE).mode, "NOOP")
        self.assertEqual(
            code(decide_migration, initialized(i, "0028", classifier_role_exists=True), i, LINEAGE),
            "NXG-R01",
        )
        # "upgrade" to an older revision is a downgrade in disguise.
        self.assertEqual(
            code(decide_migration, initialized(i), i, LINEAGE, target="0027"), "NXG-A06"
        )
        self.assertEqual(
            code(decide_migration, initialized(i), i, LINEAGE, target="0031"), "NXG-L01"
        )

    def test_operations_limited_by_environment(self):
        i = self.ident
        self.assertEqual(
            code(decide_migration, initialized(i), i, LINEAGE, operation="stamp"), "NXG-A06"
        )
        self.assertEqual(
            code(
                decide_migration, initialized(i), i, LINEAGE, operation="downgrade", target="0028"
            ),
            "NXG-A06",
        )
        ci = identity("ci", role="migrator")
        down = decide_migration(initialized(ci), ci, LINEAGE, operation="downgrade", target="0027")
        self.assertEqual((down.mode, down.steps), ("DOWNGRADE", ("0029", "0028")))
        runtime = identity()
        self.assertEqual(code(decide_migration, empty(runtime), runtime, LINEAGE), "NXG-I04")

    def test_ci_owner_may_create_databases_but_dev_owner_may_not(self):
        ci = identity("ci", role="migrator")
        self.assertEqual(decide_migration(empty(ci, createdb=True), ci, LINEAGE).mode, "INIT")
        self.assertEqual(
            code(decide_migration, empty(self.ident, createdb=True), self.ident, LINEAGE), "NXG-I05"
        )


class FactsGathering(unittest.TestCase):
    def fake(self, rows, fail_sysid=False):
        calls = []

        def query(sql, params):
            calls.append(sql)
            if sql == facts_module.SYSTEM_IDENTIFIER and fail_sysid:
                raise PermissionError("permission denied for function pg_control_system")
            if sql == facts_module.TABLE_PRESENT:
                return [(rows["present"].get(params["table"], False),)]
            return rows.get(sql, [])

        return query, calls

    def test_gather_parses_rows_and_tolerates_missing_sysid(self):
        rows = {
            facts_module.IDENTITY: [
                (
                    "nextup_dev",
                    "nextup-oss-dev",
                    "nextup_dev_app",
                    "nextup_dev_app",
                    170004,
                    "public",
                )
            ],
            facts_module.ROLE_ATTRIBUTES: [(False, False, False, False, False)],
            facts_module.CREATE_RIGHTS: [(False, False, False)],
            facts_module.APPLICATION_TABLES: [(24,)],
            facts_module.ALEMBIC_ROWS: [("0029",)],
            facts_module.MARKER_ROWS: [
                ("dev", "nextup", "nextup_dev", "nextup-oss-dev", SYSID, INSTANCE, "2a.1")
            ],
            facts_module.EXTENSION: [(True,)],
            facts_module.CLASSIFIER: [(False,)],
            facts_module.FOREIGN_GRANTEES: [],
            facts_module.GUARD_TABLE_WRITES: [(False,)],
            facts_module.PROVISIONING: [("complete-v1",)],
            facts_module.PROVISIONING_PERSISTED: [("database", "nextup.provisioning=complete-v1")],
            facts_module.SYSTEM_IDENTIFIER: [(SYSID,)],
            "present": {"alembic_version": True, "nextup_environment": True},
        }
        query, calls = self.fake(rows)
        facts = gather(query, owner_role="nextup_dev_owner", app_role="nextup_dev_app")
        self.assertEqual(decide_runtime(facts, identity(), LINEAGE).mode, "PROCEED-RUNTIME")
        self.assertEqual(calls[-1], facts_module.SYSTEM_IDENTIFIER)
        query, _ = self.fake(rows, fail_sysid=True)
        self.assertIsNone(gather(query, owner_role="o", app_role="a").system_identifier)
        rows[facts_module.ROLE_ATTRIBUTES] = []  # role row missing: assume the worst
        query, _ = self.fake(rows)
        self.assertTrue(gather(query, owner_role="o", app_role="a").superuser)

    def test_provisioning_setting_is_read_and_missing_means_none(self):
        rows = {
            facts_module.IDENTITY: [("d", "c", "u", "u", 170004, "public")],
            facts_module.CREATE_RIGHTS: [(False, False, False)],
            facts_module.APPLICATION_TABLES: [(0,)],
            facts_module.EXTENSION: [(True,)],
            facts_module.CLASSIFIER: [(False,)],
            facts_module.PROVISIONING: [("complete-v1",)],
            "present": {},
        }
        query, calls = self.fake(rows)
        self.assertEqual(gather(query, owner_role="o", app_role="a").provisioning, "complete-v1")
        pair = (facts_module.PROVISIONING, facts_module.SYSTEM_IDENTIFIER)
        order = [calls.index(sql) for sql in pair]
        self.assertEqual(order, sorted(order))
        rows[facts_module.PROVISIONING] = [(None,)]
        self.assertIsNone(gather(self.fake(rows)[0], owner_role="o", app_role="a").provisioning)
        rows.pop(facts_module.PROVISIONING)
        self.assertIsNone(gather(self.fake(rows)[0], owner_role="o", app_role="a").provisioning)

    def test_persistent_provisioning_entries_are_read_from_the_catalog(self):
        rows = {
            facts_module.IDENTITY: [("d", "c", "u", "u", 170004, "public")],
            facts_module.CREATE_RIGHTS: [(False, False, False)],
            facts_module.APPLICATION_TABLES: [(0,)],
            facts_module.EXTENSION: [(True,)],
            facts_module.CLASSIFIER: [(False,)],
            facts_module.PROVISIONING: [("complete-v1",)],
            facts_module.PROVISIONING_PERSISTED: [
                ("database", "nextup.provisioning=complete-v1"),
                ("role", "nextup.provisioning=complete-v1"),
            ],
            "present": {},
        }
        query, calls = self.fake(rows)
        facts = gather(query, owner_role="o", app_role="a")
        self.assertEqual(
            facts.provisioning_persisted,
            (
                ("database", "nextup.provisioning=complete-v1"),
                ("role", "nextup.provisioning=complete-v1"),
            ),
        )
        # after the effective value, before the system identifier (which must stay last)
        order = [
            calls.index(sql)
            for sql in (
                facts_module.PROVISIONING,
                facts_module.PROVISIONING_PERSISTED,
                facts_module.SYSTEM_IDENTIFIER,
            )
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(calls[-1], facts_module.SYSTEM_IDENTIFIER)
        rows.pop(facts_module.PROVISIONING_PERSISTED)  # no stored setting at all
        self.assertEqual(
            gather(self.fake(rows)[0], owner_role="o", app_role="a").provisioning_persisted, ()
        )

    def test_unreadable_catalog_means_provisioning_is_not_established(self):
        rows = {
            facts_module.IDENTITY: [("d", "c", "u", "u", 170004, "public")],
            facts_module.CREATE_RIGHTS: [(False, False, False)],
            facts_module.APPLICATION_TABLES: [(0,)],
            facts_module.EXTENSION: [(True,)],
            facts_module.CLASSIFIER: [(False,)],
            facts_module.PROVISIONING: [("complete-v1",)],
            "present": {},
        }
        calls = []

        def query(sql, params):
            calls.append(sql)
            if sql == facts_module.PROVISIONING_PERSISTED:
                raise PermissionError("permission denied for table pg_db_role_setting")
            if sql == facts_module.TABLE_PRESENT:
                return [(False,)]
            return rows.get(sql, [])

        facts = gather(query, owner_role="o", app_role="a")
        self.assertIsNone(facts.provisioning_persisted)
        self.assertEqual(facts.provisioning, "complete-v1")  # the session value is not enough
        self.assertFalse(facts_module.provisioning_verified(facts))

    def test_persistent_statement_is_bound_to_the_connected_database(self):
        sql = facts_module.PROVISIONING_PERSISTED
        self.assertIn("pg_catalog.pg_db_role_setting", sql)
        # this database's OID, looked up from the connected database, never a name or parameter
        self.assertIn(
            "s.setdatabase = (SELECT d.oid FROM pg_catalog.pg_database d "
            "WHERE d.datname = current_database())",
            sql,
        )
        self.assertIn("s.setdatabase <> 0 AND s.setrole = 0 THEN 'database'", sql)
        self.assertIn("lower(split_part(cfg, '=', 1)) = 'nextup.provisioning'", sql)
        for forbidden in ("current_setting", "set_config", ":", "%("):
            self.assertNotIn(forbidden, sql)  # no session value and no bind parameter
        self.assertNotIn("pg_db_role_setting", facts_module.PROVISIONING)

    def test_statements_are_read_only(self):
        forbidden = re.compile(
            r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|GRANT|REVOKE|TRUNCATE|COPY|CALL|DO|SET|LOCK|VACUUM|COMMENT|SECURITY|nextval|setval|pg_advisory)\b",
            re.I,
        )
        for sql in facts_module.STATEMENTS:
            # Privilege names such as 'CREATE' are string arguments, not statements.
            code_only = re.sub(r"'[^']*'", "''", sql)
            with self.subTest(sql=sql[:40]):
                self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
                self.assertIsNone(forbidden.search(code_only))
                self.assertNotIn(";", sql)
        for sql in facts_module.READ_ONLY_PREAMBLE:
            self.assertTrue(
                sql.startswith(
                    (
                        "SET TRANSACTION READ ONLY",
                        "SET LOCAL statement_timeout",
                        "SET LOCAL lock_timeout",
                    )
                )
            )


class Provisioning(unittest.TestCase):
    """An initialized data directory whose first-boot provisioning did not complete."""

    def test_incomplete_provisioning_is_refused_everywhere(self):
        for value in (None, "", "complete-v0", "complete-v1 ", "partial"):
            run, mig = identity(), identity(role="migrator")
            cases = (
                (decide_runtime, initialized(run, provisioning=value), run),
                (decide_migration, empty(mig, provisioning=value), mig),
                (decide_migration, initialized(mig, "0028", provisioning=value), mig),
            )
            for decide, facts, ident in cases:
                with self.subTest(value=value, decide=decide.__name__):
                    self.assertEqual(code(decide, facts, ident, LINEAGE), "NXG-I10")

    def refused_everywhere(self, label, **changes):
        run, mig = identity(), identity(role="migrator")
        cases = (
            (decide_runtime, initialized(run, **changes), run),
            (decide_migration, empty(mig, **changes), mig),
            (decide_migration, initialized(mig, "0028", **changes), mig),
        )
        for decide, facts, ident in cases:
            with self.subTest(label, decide=decide.__name__):
                self.assertFalse(facts_module.provisioning_verified(facts))
                self.assertEqual(code(decide, facts, ident, LINEAGE), "NXG-I10")

    def test_only_the_stored_database_wide_setting_establishes_provisioning(self):
        """In every case the effective (session) value says complete-v1."""
        good = ("database", "nextup.provisioning=complete-v1")
        self.assertTrue(facts_module.provisioning_verified(initialized(identity())))
        cases = {
            "catalog could not be read": None,
            "session SET, set_config() or PGOPTIONS only: nothing stored": (),
            "wrong stored value": (("database", "nextup.provisioning=complete-v0"),),
            "stored value with trailing space": (("database", "nextup.provisioning=complete-v1 "),),
            "stored empty value": (("database", "nextup.provisioning="),),
            "differently spelled name": (("database", "NextUp.Provisioning=complete-v1"),),
            "role-in-database setting only": (("role-in-database", good[1]),),
            "role setting only": (("role", good[1]),),
            "cluster-wide default only": (("cluster", good[1]),),
            "duplicate database entries": (good, good),
            "conflicting database entries": (good, ("database", "nextup.provisioning=partial")),
            "database entry plus a role override": (good, ("role-in-database", good[1])),
            "database entry plus a cluster default": (("cluster", good[1]), good),
            "unknown scope": (("other-database", good[1]),),
        }
        for label, persisted in cases.items():
            self.refused_everywhere(label, provisioning_persisted=persisted)

    def test_effective_value_must_agree_with_the_stored_setting(self):
        for value in (None, "", "complete-v0", "partial"):
            self.refused_everywhere(f"effective={value!r}", provisioning=value)

    def test_facts_without_catalog_evidence_fail_closed_by_default(self):
        ident = identity()
        values = {k: getattr(initialized(ident), k) for k in Facts.__dataclass_fields__}
        values.pop("provisioning_persisted")
        self.assertEqual(code(decide_runtime, Facts(**values), ident, LINEAGE), "NXG-I10")

    def test_verified_sentinel_never_replaces_identity_marker_or_grant_checks(self):
        run, mig = identity(), identity(role="migrator")
        cases = {
            "other database": (run, dict(database="otherapp"), "NXG-I02"),
            "other cluster": (run, dict(cluster_name="main"), "NXG-I03"),
            "owner credential at runtime": (run, dict(current_user="nextup_dev_owner"), "NXG-I04"),
            "SET ROLE": (run, dict(session_user="nextup_dev_admin"), "NXG-I04"),
            "superuser": (run, dict(superuser=True), "NXG-I05"),
            "app may write guard tables": (run, dict(guard_tables_writable=True), "NXG-I05"),
            "member of owner": (run, dict(member_of_owner=True), "NXG-I05"),
            "no system identifier": (run, dict(system_identifier=None), "NXG-I07"),
            "marker from another cluster": (run, dict(system_identifier="111"), "NXG-M03"),
            "no marker row": (run, dict(markers=()), "NXG-L05"),
            "unknown revision": (run, dict(alembic_versions=("prv_0030",)), "NXG-L01"),
            "foreign grantee": (run, dict(foreign_grantees=("PUBLIC",)), "NXG-R02"),
            "classifier role": (run, dict(classifier_role_exists=True), "NXG-R01"),
        }
        for label, (ident, changes, expected) in cases.items():
            with self.subTest(label):
                facts = initialized(ident, **changes)
                self.assertTrue(facts_module.provisioning_verified(facts))
                self.assertEqual(code(decide_runtime, facts, ident, LINEAGE), expected)
        populated = initialized(mig, marker_present=False, markers=())
        self.assertEqual(code(decide_migration, populated, mig, LINEAGE), "NXG-M01")
        createdb = empty(mig, createdb=True)
        self.assertEqual(code(decide_migration, createdb, mig, LINEAGE), "NXG-I05")

    def test_complete_provisioning_still_needs_every_other_check(self):
        ident = identity()
        self.assertEqual(decide_runtime(initialized(ident), ident, LINEAGE).mode, "PROCEED-RUNTIME")
        no_marker_row = initialized(ident, markers=())
        self.assertEqual(code(decide_runtime, no_marker_row, ident, LINEAGE), "NXG-L05")


class Authorization(unittest.TestCase):
    NOW = 1_800_000_000

    def setUp(self):
        self.ident = identity(role="migrator")
        self.facts = empty(self.ident)
        self.ledger = InMemoryLedger()

    def plan(self, **kwargs):
        decision, token = plan(self.facts, self.ident, LINEAGE, now=self.NOW, **kwargs)
        return decision, token

    def consume(self, token, facts=None, ident=None, now=None, **kwargs):
        return revalidate_and_consume(
            token,
            facts or self.facts,
            ident or self.ident,
            LINEAGE,
            now=self.NOW + 5 if now is None else now,
            ledger=self.ledger,
            **kwargs,
        )

    def refused(self, expected, *args, **kwargs):
        with self.assertRaises(GuardRefused) as caught:
            self.consume(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)

    def test_issue_revalidate_consume_once(self):
        decision, token = self.plan()
        self.assertEqual(decision.mode, "INIT")
        _, authorization = self.consume(token)
        self.assertEqual(authorization.operation, "INIT")
        self.refused("NXG-A03", token)  # second use

    def test_nonce_is_random_and_full_length(self):
        tokens = {self.plan()[1] for _ in range(20)}
        self.assertEqual(len(tokens), 20)
        payload = plan_module.json.loads(plan_module._unb64(next(iter(tokens)).split(".")[1]))
        self.assertEqual(len(plan_module._unb64(payload["nonce"])), 32)
        self.assertLessEqual(payload["exp"] - payload["iat"], plan_module.MAX_TTL_SECONDS)

    def test_expiry_and_clock_bounds(self):
        _, token = self.plan()
        self.refused("NXG-A04", token, now=self.NOW + plan_module.DEFAULT_TTL_SECONDS)
        self.refused("NXG-A04", token, now=self.NOW - plan_module.CLOCK_SKEW_SECONDS - 1)
        with self.assertRaises(GuardRefused) as caught:
            self.plan(ttl=plan_module.MAX_TTL_SECONDS + 1)
        self.assertEqual(caught.exception.code, "NXG-A05")

    def test_binding_to_identity_and_state(self):
        _, token = self.plan()
        i = self.ident
        changed = {
            "system identifier": empty(i, system_identifier="42"),
            "now populated": empty(i, application_tables=1),
        }
        for label, facts in changed.items():
            with self.subTest(label):
                with self.assertRaises(GuardRefused) as caught:
                    self.consume(token, facts=facts)
                self.assertIn(caught.exception.code, ("NXG-A02", "NXG-M01"))
        other_instance = dataclasses.replace(i, instance_id=uuid.uuid4())
        self.refused("NXG-A02", token, ident=other_instance)
        self.refused("NXG-A02", token, target="0028")

    def test_state_change_after_planning_an_upgrade(self):
        self.facts = initialized(self.ident, "0027")
        _, token = self.plan()
        self.refused(
            "NXG-A02", token, facts=initialized(self.ident, "0028")
        )  # someone else migrated
        self.refused("NXG-A02", token, facts=initialized(self.ident, "0026"))  # someone downgraded
        self.consume(token)  # unchanged state still works exactly once

    def test_tampering_and_foreign_keys(self):
        _, token = self.plan()
        prefix, body, mac = token.split(".")
        flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
        # The MAC's final base64 character is one of 16 canonical values, so a
        # fixed "A" equalled the real MAC in ~1/16 runs (flaky). Always pick a different one.
        last = "E" if mac[-1] == "A" else "A"
        for bad in (
            f"{prefix}.{flipped}.{mac}",
            f"{prefix}.{body}.{mac[:-1]}{last}",
            f"nxa2.{body}.{mac}",
            f"{prefix}.{body}",
            "x" * 2000,
            f"{prefix}.{body}.{mac}.extra",
            f"{prefix}.@@.{mac}",
        ):
            with self.subTest(bad=bad[:30]):
                self.refused("NXG-A05", bad)
        self.refused("NXG-A01", "")
        other_key = dataclasses.replace(self.ident, migration_key=SecretStr("z" * 48))
        self.refused("NXG-A05", token, ident=other_key)

    def test_noop_issues_nothing_and_runtime_cannot_authorize(self):
        self.facts = initialized(self.ident)
        decision, token = self.plan()
        self.assertEqual((decision.mode, token), ("NOOP", None))
        self.refused("NXG-A02", "nxa1.x.y")
        runtime = identity()
        with self.assertRaises(GuardRefused) as caught:
            verify(
                "nxa1.x.y",
                expected_digest="0" * 64,
                identity=runtime,
                now=self.NOW,
                ledger=self.ledger,
            )
        self.assertEqual(caught.exception.code, "NXG-A01")

    def test_constant_time_comparisons_and_concurrent_ledger(self):
        source = inspect.getsource(plan_module.verify)
        self.assertEqual(source.count("hmac.compare_digest"), 2)
        ledger, results = InMemoryLedger(), []
        threads = [
            threading.Thread(target=lambda: results.append(ledger.consume("n", 1)))
            for _ in range(16)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(True), 1)


if __name__ == "__main__":
    unittest.main()
