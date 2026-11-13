"""No secret or connection detail escapes through errors, tracebacks, reprs or logs."""

import logging
import os
import tempfile
import traceback
import unittest
import uuid

from app.config import Settings, load_settings
from app.guard.errors import CODES, ConfigError, GuardError, GuardRefused, classify_connection_error
from app.secrets_files import read_secret_file

SECRET = "zZSENTINELzz_super_secret_value_0123456789"
HOST = "sentinel-host.internal.example"


def base(**overrides):
    values = {
        "NEXTUP_ENV": "dev",
        "NEXTUP_DB_HOST": "postgres",
        "NEXTUP_DB_NAME": "nextup_dev",
        "NEXTUP_DB_USER": "nextup_dev_app",
        "NEXTUP_DB_PASSWORD": SECRET,
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


def rendered(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(exc))
    return "\n".join([text, str(exc), repr(exc), repr(exc.args)])


class Redaction(unittest.TestCase):
    def assertClean(self, text):
        for needle in (SECRET, HOST, "SENTINEL"):
            self.assertNotIn(needle, text)

    def capture(self, environ):
        with self.assertRaises(GuardError) as caught:
            load_settings(environ)
        return caught.exception

    def test_configuration_errors_never_echo_values(self):
        cases = [
            base(NEXTUP_DB_HOST=HOST),
            base(NEXTUP_DB_NAME=SECRET),
            base(NEXTUP_DB_USER=SECRET),
            base(NEXTUP_DB_PASSWORD="short" + "SENTINEL"),
            base(NEXTUP_DB_PORT=SECRET),
            base(NEXTUP_ENV=SECRET),
            base(NEXTUP_INSTANCE_ID=SECRET),
            base(NEXTUP_DB_ROLE=SECRET),
            base(NEXTUP_DIAGNOSTIC_INTERVAL_SECONDS=SECRET),
            base(NEXTUP_GREENHOUSE_BOARD_TOKEN=SECRET + "/x"),
            base(NEXTUP_GMAIL_SYNC_ENABLED=SECRET),
            base(NEXTUP_REDIS_URL=f"redis://{HOST}:6379/0"),
            base(NEXTUP_MIGRATION_KEY=SECRET),
            {**base(), "DATABASE_URL": f"postgresql://u:{SECRET}@{HOST}/db"},
            {**base(), "N8N_PASSWORD": SECRET},
            {
                **base(
                    NEXTUP_DB_HOST=None,
                    NEXTUP_DB_NAME=None,
                    NEXTUP_DB_USER=None,
                    NEXTUP_DB_PASSWORD=None,
                ),
                "NEXTUP_DATABASE_URL": f"postgresql://nextup_dev_app:{SECRET}@{HOST}:5432/nextup_dev?sslmode=disable",
            },
            {
                **base(
                    NEXTUP_DB_HOST=None,
                    NEXTUP_DB_NAME=None,
                    NEXTUP_DB_USER=None,
                    NEXTUP_DB_PASSWORD=None,
                ),
                "NEXTUP_DATABASE_URL": f"postgresql://nextup_dev_app:{SECRET}@{HOST}:99999/nextup_dev",
            },
            {**base(), "NEXTUP_DB_PASSWORD_FILE": f"/run/secrets/{SECRET}"},
        ]
        for environ in cases:
            with self.subTest(keys=sorted(environ)):
                error = self.capture(environ)
                self.assertIn(error.code, CODES)
                self.assertClean(rendered(error))
                self.assertIsNone(error.__cause__)

    def test_secret_file_errors_never_echo_path_or_content(self):
        root = os.path.realpath(tempfile.mkdtemp())
        path = os.path.join(root, SECRET)
        try:
            with open(path, "w") as handle:
                handle.write(SECRET + "\n" + SECRET)
            os.chmod(path, 0o644)
            for mode in (0o644, 0o600):
                os.chmod(path, mode)
                with self.subTest(mode=oct(mode)), self.assertRaises(GuardError) as caught:
                    read_secret_file(path, variable="NEXTUP_DB_PASSWORD_FILE", roots=(root,))
                self.assertClean(rendered(caught.exception))
        finally:
            os.unlink(path)
            os.rmdir(root)

    def test_reprs_mask_secrets(self):
        settings = load_settings(
            base(NEXTUP_ADZUNA_APP_KEY=SECRET, NEXTUP_INSTANCE_ID=str(uuid.uuid4()))
        )
        for text in (
            repr(settings),
            str(settings),
            repr(settings.identity),
            repr(settings.identity.database),
            repr(Settings(gmail_refresh_token=SECRET)),
            str(settings.model_dump()),
        ):
            self.assertClean(text)

    def test_logs_carry_key_names_only(self):
        records = []

        class Collect(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        handler = Collect()
        root = logging.getLogger()
        root.addHandler(handler)
        previous = root.level
        root.setLevel(logging.DEBUG)
        try:
            load_settings(
                base(NEXTUP_ADZUNA_APP_KEY=SECRET, NEXTUP_GOOGLE_OAUTH_CLIENT_SECRET=SECRET)
            )
            try:
                load_settings(base(NEXTUP_DB_HOST=HOST))
            except GuardError:
                pass
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        self.assertTrue(records)
        self.assertClean("\n".join(records))

    def test_driver_errors_are_classified_without_their_text(self):
        class DriverError(Exception):
            def __init__(self, sqlstate):
                super().__init__(
                    f'connection to server at "{HOST}" failed: password {SECRET} for user x'
                )
                self.sqlstate = sqlstate

        class Wrapped(Exception):
            def __init__(self, orig):
                super().__init__(str(orig))
                self.orig = orig

        for exc, expected in (
            (DriverError("28P01"), "NXG-C06"),
            (DriverError("28000"), "NXG-C06"),
            (DriverError("3D000"), "NXG-I02"),
            (DriverError(None), "NXG-C05"),
            (Wrapped(DriverError("28P01")), "NXG-C06"),
            (OSError(SECRET), "NXG-C05"),
        ):
            with self.subTest(expected=expected):
                classified = classify_connection_error(exc)
                self.assertEqual(classified.code, expected)
                self.assertClean(rendered(classified))

    def test_error_objects_accept_only_key_names(self):
        error = GuardRefused(
            "NXG-I02",
            keys=("NEXTUP_DB_NAME", SECRET, f"/run/secrets/{SECRET}", "lower_case"),
            env=SECRET,
        )
        self.assertClean(rendered(error))
        self.assertIn("NEXTUP_DB_NAME", str(error))
        self.assertEqual(ConfigError("unknown-code").code, "NXG-C14")
        self.assertTrue(all(line.startswith("NXG-") for line in CODES))


if __name__ == "__main__":
    unittest.main()
