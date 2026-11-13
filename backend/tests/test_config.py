"""Configuration contract. Pure: explicit environ dicts, no services."""

import importlib.util
import logging
import os
import tempfile
import unittest
import unittest.mock
import uuid

from app import config
from app.config import LEGACY_VARIABLES, ConfigError, Settings, load_settings

PASSWORD = "dev_password_for_unit_tests_only_0123"
SENTINEL = "SENTINEL_value_never_printed_123456789"
HAVE_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


def env(name="dev", role="runtime", **overrides):
    prefix = {"dev": "nextup_dev", "staging": "nextup_stg", "ci": "nextup_ci", "test": "nextup_ci"}[
        name
    ]
    values = {
        "NEXTUP_ENV": name,
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": prefix,
        "NEXTUP_DB_USER": f"{prefix}_{'app' if role == 'runtime' else 'owner'}",
        "NEXTUP_DB_PASSWORD": PASSWORD,
    }
    if role == "migrator":
        values.update(NEXTUP_DB_ROLE="migrator", NEXTUP_MIGRATION_KEY="k" * 40)
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


class Refusals(unittest.TestCase):
    def refused(self, code, environ):
        with self.assertRaises(ConfigError) as caught:
            load_settings(environ)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        for secret in (PASSWORD, SENTINEL, "k" * 40):
            self.assertNotIn(secret, str(caught.exception) + repr(caught.exception))
        return caught.exception


class Identity(Refusals):
    def test_valid_runtime_and_migrator_identities(self):
        settings = load_settings(env())
        self.assertEqual(settings.identity.environment, "dev")
        self.assertEqual(settings.identity.expected_user, "nextup_dev_app")
        self.assertEqual(settings.identity.expected_cluster, "nextup-oss-dev")
        self.assertIsNone(settings.identity.migration_key)
        migrator = load_settings(env(role="migrator"))
        self.assertEqual(migrator.identity.expected_user, "nextup_dev_owner")
        self.assertIsNotNone(migrator.identity.migration_key)

    def test_environment_identity_is_required(self):
        self.refused("NXG-C01", env(NEXTUP_ENV=None))
        self.refused("NXG-C01", env(NEXTUP_ENV="production"))
        self.refused("NXG-C01", env(NEXTUP_ENV="DEV"))
        self.refused("NXG-C02", env(NEXTUP_ENV="personal"))

    def test_no_default_database(self):
        settings = Settings()
        with self.assertRaises(ConfigError) as caught:
            _ = settings.database_url
        self.assertEqual(caught.exception.code, "NXG-C11")
        for key in ("NEXTUP_DB_HOST", "NEXTUP_DB_NAME", "NEXTUP_DB_USER"):
            with self.subTest(key=key):
                self.refused("NXG-C13", env(**{key: None}))
        self.refused("NXG-C13", env(NEXTUP_DB_PASSWORD=None))

    def test_database_must_be_the_stacks_own(self):
        for host in ("db.example", "127.0.0.1", "host.docker.internal", "postgres.local"):
            with self.subTest(host=host):
                self.refused("NXG-C07", env(NEXTUP_DB_HOST=host))
        self.refused("NXG-C07", env(NEXTUP_DB_PORT="5433"))
        self.refused("NXG-C14", env(NEXTUP_DB_PORT="x"))
        for name in ("nextup_stg", "nextup", "postgres", "nextup_dev_copy"):
            with self.subTest(name=name):
                self.refused("NXG-C12", env(NEXTUP_DB_NAME=name))
        self.refused("NXG-C12", env(NEXTUP_DB_USER="nextup_dev_owner"))  # runtime with owner
        self.refused("NXG-C12", env(role="migrator", NEXTUP_DB_USER="nextup_dev_app"))
        self.refused("NXG-C12", env(NEXTUP_DB_USER="postgres"))

    def test_test_environment_database_names(self):
        load_settings(env("test"))
        load_settings(env("test", NEXTUP_DB_NAME="nextup_migration_test_" + "a" * 32))
        self.refused("NXG-C12", env("test", NEXTUP_DB_NAME="nextup_migration_test_x"))
        self.refused("NXG-C12", env("test", NEXTUP_DB_NAME="nextup_dev"))

    def test_password_strength(self):
        for value in ("short", "local-development", "a b c d e f g h i j k l m n", "ä" * 30):
            with self.subTest(value=len(value)):
                self.refused("NXG-S06", env(NEXTUP_DB_PASSWORD=value))

    def test_url_form(self):
        url = f"postgresql+psycopg://nextup_dev_app:{PASSWORD}@postgres:5432/nextup_dev"
        base = env(
            NEXTUP_DB_HOST=None, NEXTUP_DB_NAME=None, NEXTUP_DB_USER=None, NEXTUP_DB_PASSWORD=None
        )
        self.assertEqual(
            load_settings({**base, "NEXTUP_DATABASE_URL": url}).identity.database.name, "nextup_dev"
        )
        self.refused("NXG-C04", {**env(), "NEXTUP_DATABASE_URL": url})
        self.refused("NXG-C14", {**base, "NEXTUP_DATABASE_URL": url + "?host=elsewhere"})
        self.refused(
            "NXG-C14", {**base, "NEXTUP_DATABASE_URL": url.replace("postgresql+psycopg", "mysql")}
        )
        self.refused(
            "NXG-C07", {**base, "NEXTUP_DATABASE_URL": url.replace("@postgres:", "@db.example:")}
        )

    def test_instance_identity(self):
        load_settings(env(NEXTUP_INSTANCE_ID=str(uuid.uuid4())))
        self.refused("NXG-C14", env(NEXTUP_INSTANCE_ID="not-a-uuid"))
        self.refused("NXG-C14", env(NEXTUP_INSTANCE_ID=str(uuid.uuid1())))

    def test_runtime_never_receives_migration_credentials(self):
        self.refused("NXG-C10", env(NEXTUP_MIGRATION_KEY="k" * 40))
        self.refused("NXG-C10", env(NEXTUP_MIGRATION_KEY_FILE="/run/secrets/migration_key"))
        self.refused("NXG-C13", env(role="migrator", NEXTUP_MIGRATION_KEY=None))
        self.refused("NXG-S06", env(role="migrator", NEXTUP_MIGRATION_KEY="short"))
        self.refused("NXG-C14", env(NEXTUP_DB_ROLE="admin"))


class Legacy(Refusals):
    def test_each_legacy_variable_is_refused_by_name(self):
        for name in sorted(LEGACY_VARIABLES) + ["N8N_DB_PASSWORD", "MY_N8N_URL", "N8N"]:
            with self.subTest(name=name):
                error = self.refused("NXG-C03", {**env(), name: SENTINEL})
                self.assertIn(name, str(error))

    def test_pgoptions_is_refused_by_name_only(self):
        """libpq would apply PGOPTIONS to guard connections. Refused for every
        environment and role, with a fixed message that never contains the value."""
        value = f"-c nextup.provisioning=complete-v1 -c x.y={SENTINEL}"
        for name, role in (
            ("dev", "runtime"),
            ("dev", "migrator"),
            ("staging", "runtime"),
            ("ci", "migrator"),
            ("test", "migrator"),
        ):
            with self.subTest(env=name, role=role):
                error = self.refused("NXG-C18", {**env(name, role), "PGOPTIONS": value})
                self.assertIn("PGOPTIONS", str(error))
                self.assertNotIn("provisioning", str(error) + repr(error))
        self.refused("NXG-C18", {**env(), "PGOPTIONS": ""})  # presence is enough
        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("probe").debug("start")
            with self.assertRaises(ConfigError):
                load_settings({**env(), "PGOPTIONS": value})
        self.assertNotIn(SENTINEL, "\n".join(logs.output))

    def test_pgoptions_in_the_real_process_environment_is_refused(self):
        # libpq reads os.environ, whatever mapping the loader was handed.
        with unittest.mock.patch.dict(os.environ, {"PGOPTIONS": f"-c x.y={SENTINEL}"}):
            self.refused("NXG-C18", env())
            self.refused("NXG-C18", env(role="migrator"))
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("PGOPTIONS", None)
            load_settings(env())


# Environment variables documented for libpq in PostgreSQL 17 (33.15), plus two older names.
LIBPQ_DOCUMENTED = (
    "PGHOST PGSSLNEGOTIATION PGHOSTADDR PGPORT PGDATABASE PGUSER PGPASSWORD PGPASSFILE "
    "PGREQUIREAUTH PGCHANNELBINDING PGSERVICE PGSERVICEFILE PGOPTIONS PGAPPNAME PGSSLMODE "
    "PGREQUIRESSL PGSSLCOMPRESSION PGSSLCERT PGSSLKEY PGSSLCERTMODE PGSSLROOTCERT PGSSLCRL "
    "PGSSLCRLDIR PGSSLSNI PGREQUIREPEER PGSSLMINPROTOCOLVERSION PGSSLMAXPROTOCOLVERSION "
    "PGGSSENCMODE PGKRBSRVNAME PGGSSLIB PGGSSDELEGATION PGCONNECT_TIMEOUT PGCLIENTENCODING "
    "PGTARGETSESSIONATTRS PGLOADBALANCEHOSTS PGDATESTYLE PGTZ PGGEQO PGSYSCONFDIR PGLOCALEDIR "
    "PGREALM PGTTY"
).split()
PROCESSES = (
    ("dev", "runtime"),  # api, worker and scheduler share this identity
    ("dev", "migrator"),
    ("staging", "runtime"),
    ("staging", "migrator"),
    ("ci", "runtime"),
    ("ci", "migrator"),
    ("test", "migrator"),
)


class LibpqEnvironment(Refusals):
    """No PostgreSQL client variable reaches a connection."""

    def test_the_allowlist_is_explicit_and_empty(self):
        self.assertEqual(config.LIBPQ_ALLOWED_VARIABLES, frozenset())
        self.assertEqual(config.SERVER_ONLY_VARIABLES, frozenset({"PGDATA"}))
        self.assertEqual(len(set(LIBPQ_DOCUMENTED)), 42)
        self.assertEqual(config.libpq_variables(LIBPQ_DOCUMENTED), sorted(LIBPQ_DOCUMENTED))

    def test_every_documented_variable_is_refused_by_name_only(self):
        for name in LIBPQ_DOCUMENTED:
            with self.subTest(name=name):
                with self.assertRaises(ConfigError) as caught:
                    load_settings({**env(), name: SENTINEL})
                error = caught.exception
                # the six names of the older layout keep their earlier code
                self.assertEqual(error.code, "NXG-C03" if name in LEGACY_VARIABLES else "NXG-C18")
                self.assertIn(name, str(error))
                self.assertNotIn(SENTINEL, str(error) + repr(error))
                load_error = self.refused(error.code, {**env(), name: ""})  # presence is enough
                self.assertIn(name, str(load_error))

    def test_every_process_identity_shares_the_policy(self):
        for name, role in PROCESSES:
            for variable in ("PGHOSTADDR", "PGSERVICE", "PGSYSCONFDIR", "PGPORT", "PGSSLMODE"):
                with self.subTest(env=name, role=role, variable=variable):
                    error = self.refused("NXG-C18", {**env(name, role), variable: SENTINEL})
                    self.assertEqual(error.keys, (variable,))

    def test_variables_inherited_from_the_shell_are_refused(self):
        # libpq reads the real process environment, whatever mapping the loader was handed.
        for name in LIBPQ_DOCUMENTED:
            with self.subTest(name=name), unittest.mock.patch.dict(os.environ, {name: SENTINEL}):
                error = self.refused("NXG-C18", env())
                self.assertEqual(error.keys, (name,))
                self.refused("NXG-C18", env(role="migrator"))
                with self.assertRaises(ConfigError) as caught:
                    config.refuse_client_environment()
                self.assertEqual(caught.exception.keys, (name,))
        # the loader's default mapping is the process environment itself
        with unittest.mock.patch.dict(os.environ, {**env(), "PGHOSTADDR": SENTINEL}, clear=True):
            with self.assertRaises(ConfigError) as caught:
                load_settings()
            self.assertEqual(caught.exception.code, "NXG-C18")
            self.assertEqual(caught.exception.keys, ("PGHOSTADDR",))

    def test_all_offending_names_are_reported_together_without_values(self):
        with unittest.mock.patch.dict(os.environ, {"PGSERVICE": SENTINEL}):
            with self.assertLogs(level="DEBUG") as logs:
                logging.getLogger("probe").debug("start")
                error = self.refused("NXG-C18", {**env(), "PGHOSTADDR": SENTINEL, "PGTZ": "x"})
        self.assertEqual(error.keys, ("PGHOSTADDR", "PGSERVICE", "PGTZ"))
        self.assertNotIn(SENTINEL, "\n".join(logs.output))

    def test_unknown_and_future_client_names_fail_closed(self):
        for name in ("PGMAXPROTOCOLVERSION", "PGNEWTHING", "PGX", "PGHOST_2", "PGSSLKEYLOGFILE"):
            with self.subTest(name=name):
                self.refused("NXG-C18", {**env(), name: "x"})

    def test_names_libpq_does_not_read_are_not_flagged(self):
        harmless = {"PGDATA": "/x", "PG_MAJOR": "17", "PG_VERSION": "17.1", "pghost": "x"}
        harmless.update(PG="x", XPGHOST="x", MYPGHOSTADDR="x")
        load_settings({**env(), **harmless})
        with unittest.mock.patch.dict(os.environ, harmless):
            load_settings(env())
            config.refuse_client_environment()

    @unittest.skipUnless(HAVE_SQLALCHEMY, "SQLAlchemy is not installed")
    def test_no_engine_is_created_once_a_client_variable_appears(self):
        """PGHOSTADDR and the service variables cannot redirect a connection: even when one
        appears after the settings were loaded, both engine factories refuse before SQLAlchemy
        (and so libpq) is given anything."""
        from app import db, guard  # noqa: PLC0415

        runtime, migrator = load_settings(env()), load_settings(env(role="migrator"))
        for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR", "PGOPTIONS"):
            with self.subTest(name=name), unittest.mock.patch.dict(os.environ, {name: SENTINEL}):
                with unittest.mock.patch("sqlalchemy.create_engine") as created:
                    for schema in (None, "s_" + "0" * 32):
                        with self.assertRaises(ConfigError) as caught:
                            guard.migration_engine(migrator, schema=schema)
                        self.assertEqual(caught.exception.code, "NXG-C18")
                    created.assert_not_called()
                db.get_engine.cache_clear()
                self.addCleanup(db.get_engine.cache_clear)
                with (
                    unittest.mock.patch.object(db, "get_settings", return_value=runtime),
                    unittest.mock.patch.object(db, "create_engine") as created,
                    unittest.mock.patch.object(db.guard, "install_runtime_guard") as installed,
                ):
                    with self.assertRaises(ConfigError) as caught:
                        db.get_engine()
                    self.assertEqual(caught.exception.code, "NXG-C18")
                    self.assertNotIn(SENTINEL, str(caught.exception))
                    created.assert_not_called()
                    installed.assert_not_called()

    def test_every_connection_is_built_by_the_two_checked_factories(self):
        """api, worker and scheduler use app.db.get_engine; the migrator uses
        guard.migration_engine. Nothing else in the application creates an engine."""
        import pathlib  # noqa: PLC0415

        app_dir = pathlib.Path(config.__file__).parent
        creators = sorted(
            str(path.relative_to(app_dir))
            for path in app_dir.rglob("*.py")
            if "create_engine(" in path.read_text()
        )
        self.assertEqual(creators, ["db.py", "guard/__init__.py"])
        for relative in creators:
            source = (app_dir / relative).read_text()
            self.assertEqual(source.count("create_engine("), 1, relative)
            check, create = "refuse_client_environment()", "create_engine("
            self.assertLess(source.index(check), source.index(create), relative)
        for relative in creators:
            source = (app_dir / relative).read_text()
            for parameter in ("hostaddr", "service=", "sslmode", "passfile"):
                self.assertNotIn(parameter, source, relative)

    def test_the_connection_url_carries_no_override_parameters(self):
        base = f"postgresql+psycopg://nextup_ci_app:{PASSWORD}@postgres:5432/nextup_ci"
        for extra in (
            "?hostaddr=10.0.0.9",
            "?service=other",
            "?options=-c%20x.y%3D1",
            "?sslmode=x",
        ):
            with self.subTest(extra=extra):
                url = base + extra
                self.refused(
                    "NXG-C14",
                    env(
                        "ci",
                        NEXTUP_DATABASE_URL=url,
                        NEXTUP_DB_HOST=None,
                        NEXTUP_DB_NAME=None,
                        NEXTUP_DB_USER=None,
                        NEXTUP_DB_PASSWORD=None,
                    ),
                )

    def test_namespaced_names_with_n8n_inside_words_are_not_flagged(self):
        # Not a legacy name. It is still refused, as an unknown key.
        with self.assertRaises(ConfigError) as caught:
            load_settings({**env(), "NEXTUP_CHAN8NEL_HINT": "x"})
        self.assertEqual(caught.exception.code, "NXG-C16")


class Sources(Refusals):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        for name in os.listdir(self.root):
            os.unlink(os.path.join(self.root, name))
        os.rmdir(self.root)

    def secret(self, name, value):
        path = os.path.join(self.root, name)
        with open(path, "w") as handle:
            handle.write(value + "\n")
        os.chmod(path, 0o600)
        return path

    def test_file_secrets_and_conflicts(self):
        path = self.secret("db", PASSWORD)
        environ = env(
            NEXTUP_DB_PASSWORD=None, NEXTUP_DB_PASSWORD_FILE=path, NEXTUP_SECRETS_DIR=self.root
        )
        self.assertEqual(
            load_settings(environ).identity.database.password.get_secret_value(), PASSWORD
        )
        self.refused("NXG-C04", {**environ, "NEXTUP_DB_PASSWORD": PASSWORD})
        key = self.secret("adzuna", SENTINEL)
        self.refused(
            "NXG-C04",
            {
                **env(),
                "NEXTUP_ADZUNA_APP_KEY": "x",
                "NEXTUP_ADZUNA_APP_KEY_FILE": key,
                "NEXTUP_SECRETS_DIR": self.root,
            },
        )

    def test_staging_requires_files_and_instance(self):
        path = self.secret("db", PASSWORD)
        files = {
            "NEXTUP_DB_PASSWORD": None,
            "NEXTUP_DB_PASSWORD_FILE": path,
            "NEXTUP_SECRETS_DIR": self.root,
        }
        good = env("staging", NEXTUP_INSTANCE_ID=str(uuid.uuid4()), **files)
        self.assertEqual(load_settings(good).identity.environment, "staging")
        self.refused("NXG-C13", env("staging", **files))
        self.refused("NXG-C15", env("staging", NEXTUP_INSTANCE_ID=str(uuid.uuid4())))


class Integrations(Refusals):
    def test_everything_defaults_off(self):
        settings = load_settings(env())
        for flag in (
            "gmail_sync_enabled",
            "calendar_sync_enabled",
            "live_job_fetch_enabled",
            "fixture_data_mode",
            "external_classifier_enabled",
            "task_history_cleanup_enabled",
        ):
            self.assertFalse(getattr(settings, flag), flag)
        defaults = Settings()
        self.assertFalse(defaults.gmail_sync_enabled or defaults.live_job_fetch_enabled)

    def test_activation_requires_its_settings(self):
        self.refused("NXG-C08", env(NEXTUP_GMAIL_SYNC_ENABLED="true"))
        self.refused(
            "NXG-C08", env(NEXTUP_CALENDAR_SYNC_ENABLED="true", NEXTUP_GOOGLE_OAUTH_CLIENT_ID="id")
        )
        google = {
            "NEXTUP_GOOGLE_OAUTH_CLIENT_ID": "id",
            "NEXTUP_GOOGLE_OAUTH_CLIENT_SECRET": SENTINEL,
            "NEXTUP_GMAIL_REFRESH_TOKEN": SENTINEL,
        }
        self.assertTrue(
            load_settings(env(NEXTUP_GMAIL_SYNC_ENABLED="true", **google)).gmail_sync_enabled
        )
        self.refused("NXG-C08", env(NEXTUP_FIXTURE_DATA_MODE="true"))
        self.assertTrue(load_settings(env("ci", NEXTUP_FIXTURE_DATA_MODE="true")).fixture_data_mode)
        self.refused("NXG-C16", env("ci", NEXTUP_FIXTURE_FETCH_ENABLED="true"))  # retired name
        self.refused("NXG-C08", env(NEXTUP_EXTERNAL_CLASSIFIER_ENABLED="true"))
        self.refused("NXG-C14", env(NEXTUP_GMAIL_SYNC_ENABLED="yes"))

    def test_staging_refuses_integrations_and_their_credentials(self):
        base = {"NEXTUP_INSTANCE_ID": str(uuid.uuid4())}
        root = os.path.realpath(tempfile.mkdtemp())
        try:
            path = os.path.join(root, "db")
            with open(path, "w") as handle:
                handle.write(PASSWORD)
            os.chmod(path, 0o600)
            staging = env(
                "staging",
                NEXTUP_DB_PASSWORD=None,
                NEXTUP_DB_PASSWORD_FILE=path,
                NEXTUP_SECRETS_DIR=root,
                **base,
            )
            for key in (
                "NEXTUP_LIVE_JOB_FETCH_ENABLED",
                "NEXTUP_GMAIL_SYNC_ENABLED",
                "NEXTUP_FIXTURE_DATA_MODE",
                "NEXTUP_CALENDAR_SYNC_ENABLED",
                "NEXTUP_EXTERNAL_CLASSIFIER_ENABLED",
            ):
                with self.subTest(key=key):
                    self.refused("NXG-C09", {**staging, key: "true"})
            self.refused("NXG-C09", {**staging, "NEXTUP_GREENHOUSE_BOARD_TOKEN": "board"})
            secret = os.path.join(root, "adzuna")
            with open(secret, "w") as handle:
                handle.write(SENTINEL)
            os.chmod(secret, 0o600)
            self.refused("NXG-C09", {**staging, "NEXTUP_ADZUNA_APP_KEY_FILE": secret})
        finally:
            for name in os.listdir(root):
                os.unlink(os.path.join(root, name))
            os.rmdir(root)

    def test_unused_dev_credentials_are_logged_by_name_only(self):
        with self.assertLogs("app.config", level=logging.INFO) as logs:
            load_settings(env(NEXTUP_ADZUNA_APP_KEY=SENTINEL))
        joined = "\n".join(logs.output)
        self.assertIn("NEXTUP_ADZUNA_APP_KEY", joined)
        self.assertNotIn(SENTINEL, joined)

    def test_invalid_values_name_the_key_not_the_value(self):
        error = self.refused("NXG-C14", env(NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS="5"))
        self.assertIn("NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS", str(error))
        error = self.refused("NXG-C14", env(NEXTUP_GREENHOUSE_BOARD_TOKEN=SENTINEL + "/../x"))
        self.assertIn("NEXTUP_GREENHOUSE_BOARD_TOKEN", str(error))
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)
        self.refused("NXG-C07", env(NEXTUP_REDIS_URL="redis://elsewhere:6379/0"))


class Allowlist(Refusals):
    """Every NEXTUP_* variable must be on the explicit allowlist."""

    def test_unknown_application_variables_are_refused_by_name(self):
        keys = (
            "NEXTUP_DB_SSLMODE",
            "NEXTUP_DATABASE_HOST",
            "NEXTUP_GOOGLE_REFRESH_TOKEN_FILE",
            "NEXTUP_GUARD_DISABLED",
            "NEXTUP_SKIP_GUARD",
            "NEXTUP_PLAN",
            "nextup_lower_ignored",
        )
        for key in keys:
            with self.subTest(key=key):
                if key.startswith("NEXTUP_"):
                    error = self.refused("NXG-C16", env(**{key: SENTINEL}))
                    self.assertIn(key, str(error))
                else:
                    load_settings(env(**{key: SENTINEL}))  # not in the NEXTUP_ namespace

    def test_harness_variables_only_in_ci_and_test(self):
        for name in ("dev", "staging"):
            with self.subTest(env=name):
                values = env(name, NEXTUP_TEST_SCHEMA="nextup_test_x")
                if name == "staging":
                    values.pop("NEXTUP_DB_PASSWORD")
                self.refused("NXG-C16", values)
        for name in ("ci", "test"):
            with self.subTest(env=name):
                load_settings(env(name, NEXTUP_TEST_SCHEMA="nextup_test_x", NEXTUP_TEST_QUEUE="q"))

    def test_every_settings_field_and_identity_key_is_accepted(self):
        load_settings(
            env(
                NEXTUP_INSTANCE_ID=str(uuid.uuid4()),
                NEXTUP_DB_PORT="5432",
                NEXTUP_REDIS_URL="redis://redis:6379/0",
                NEXTUP_ALEMBIC_OFFLINE_REVIEW="1",
                NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS="60",
                NEXTUP_GMAIL_SYNC_ENABLED="false",
                NEXTUP_EXTERNAL_CLASSIFIER_ENABLED="false",
                NEXTUP_JOB_RETENTION_DAYS="30",
            )
        )
        load_settings(env(role="migrator"))

    def test_test_plumbing_keys_and_no_test_credential_key(self):
        # The CI test runner is an ordinary migrator identity; no harness credential.
        for name in ("ci", "test", "dev"):
            with self.subTest(env=name):
                self.refused("NXG-C16", env(name, NEXTUP_TEST_DB_PASSWORD_FILE="/run/secrets/x"))
        load_settings(env("test", NEXTUP_TEST_BLOCK="1", NEXTUP_TEST_SOCKET="7"))
        self.refused("NXG-C16", env("dev", NEXTUP_TEST_SOCKET="7"))

    def test_offline_review_flag_takes_only_one(self):
        self.refused("NXG-C14", env(NEXTUP_ALEMBIC_OFFLINE_REVIEW="yes"))


@unittest.skipUnless(HAVE_SQLALCHEMY, "SQLAlchemy not installed on this interpreter")
class Url(unittest.TestCase):
    def test_url_object_masks_password(self):
        url = load_settings(env()).database_url
        self.assertNotIn(PASSWORD, repr(url))
        self.assertNotIn(PASSWORD, str(url))
        self.assertEqual(
            (url.host, url.port, url.database, url.username),
            ("postgres", 5432, "nextup_dev", "nextup_dev_app"),
        )


if __name__ == "__main__":
    unittest.main()
