"""Deterministic, non-sensitive errors for configuration and database-identity checks.

Every error carries a stable code and a fixed description. Messages never contain
values: no URLs, hosts, user names, passwords, file contents or exception text from
drivers. Callers raise these ``from None`` so no chained cause is printed either.
"""

EXIT_PROCEED = 0
EXIT_REFUSE = 3
EXIT_CONFIG = 4
EXIT_UNREACHABLE = 5

# code -> (exit code, fixed description)
CODES: dict[str, tuple[int, str]] = {
    # configuration
    "NXG-C01": (EXIT_CONFIG, "NEXTUP_ENV is missing or not one of dev, staging, ci, test"),
    "NXG-C02": (EXIT_CONFIG, "NEXTUP_ENV=personal is reserved until adoption is approved"),
    "NXG-C03": (EXIT_CONFIG, "legacy configuration variables are present"),
    "NXG-C04": (EXIT_CONFIG, "a setting is supplied by more than one source"),
    "NXG-C05": (EXIT_UNREACHABLE, "database unreachable"),
    "NXG-C06": (EXIT_UNREACHABLE, "database authentication failed"),
    "NXG-C07": (EXIT_CONFIG, "database host or port is not the stack's own service"),
    "NXG-C08": (EXIT_CONFIG, "an integration is enabled without its required settings"),
    "NXG-C09": (EXIT_CONFIG, "integrations and their credentials are not allowed in staging"),
    "NXG-C10": (EXIT_CONFIG, "runtime processes must not receive migration credentials"),
    "NXG-C11": (EXIT_CONFIG, "no database identity is configured"),
    "NXG-C12": (EXIT_CONFIG, "database name or user does not match the environment"),
    "NXG-C13": (EXIT_CONFIG, "a required setting is missing"),
    "NXG-C14": (EXIT_CONFIG, "a setting has an invalid value"),
    "NXG-C15": (EXIT_CONFIG, "inline secrets are not allowed in this environment"),
    "NXG-C16": (EXIT_CONFIG, "unknown NEXTUP_ configuration variables are present"),
    "NXG-C17": (EXIT_CONFIG, "fixture data mode excludes live fetching and provider credentials"),
    "NXG-C18": (
        EXIT_CONFIG,
        "PostgreSQL client variables (PG*) are not allowed: "
        "connection settings are fixed by the application",
    ),
    # secret files
    "NXG-S01": (EXIT_CONFIG, "secret file is missing or is not a regular file"),
    "NXG-S02": (
        EXIT_CONFIG,
        "secret file path is a symlink, has symlinked components, "
        "or is outside the secret directories",
    ),
    "NXG-S03": (EXIT_CONFIG, "secret file permissions are too broad"),
    "NXG-S04": (EXIT_CONFIG, "secret file content is empty, too large, or malformed"),
    "NXG-S05": (EXIT_CONFIG, "secret file is not readable"),
    "NXG-S06": (EXIT_CONFIG, "database password does not meet the strength rules"),
    "NXG-S07": (EXIT_CONFIG, "secret file has an unexpected owner"),
    # identity
    "NXG-I01": (EXIT_REFUSE, "environment identity is missing or invalid"),
    "NXG-I02": (EXIT_REFUSE, "connected database is not the configured database"),
    "NXG-I03": (EXIT_REFUSE, "connected cluster is not the expected cluster"),
    "NXG-I04": (EXIT_REFUSE, "connected role is not the role this process requires"),
    "NXG-I05": (EXIT_REFUSE, "connected role has privileges it must not have"),
    "NXG-I06": (EXIT_REFUSE, "PostgreSQL server version is unsupported"),
    "NXG-I07": (EXIT_REFUSE, "cluster system identifier is unavailable"),
    "NXG-I08": (EXIT_REFUSE, "required extension pg_trgm is missing"),
    "NXG-I09": (EXIT_REFUSE, "database identity facts could not be read with this role"),
    "NXG-I10": (EXIT_REFUSE, "database provisioning is incomplete or unrecognized"),
    # marker
    "NXG-M01": (EXIT_REFUSE, "database is populated but has no environment marker"),
    "NXG-M02": (EXIT_REFUSE, "marker environment does not match NEXTUP_ENV"),
    "NXG-M03": (EXIT_REFUSE, "marker database or cluster does not match the connection"),
    "NXG-M04": (EXIT_REFUSE, "marker instance identity does not match"),
    "NXG-M05": (EXIT_REFUSE, "database is not initialized"),
    # lineage
    "NXG-L01": (EXIT_REFUSE, "database revision is not part of the known lineage"),
    "NXG-L02": (EXIT_REFUSE, "database has more than one revision row"),
    "NXG-L03": (EXIT_REFUSE, "database revision does not match the code head"),
    "NXG-L04": (EXIT_REFUSE, "migration files do not match the pinned lineage"),
    "NXG-L05": (EXIT_REFUSE, "marker or revision table state is inconsistent"),
    # roles and grants
    "NXG-R01": (
        EXIT_REFUSE,
        "an external-classifier role exists while that integration is disabled",
    ),
    "NXG-R02": (EXIT_REFUSE, "unexpected roles hold privileges on application tables"),
    # authorization
    "NXG-A01": (EXIT_REFUSE, "schema-changing operation requires a migration authorization"),
    "NXG-A02": (EXIT_REFUSE, "authorization does not match the current database state or request"),
    "NXG-A03": (EXIT_REFUSE, "authorization has already been used"),
    "NXG-A04": (EXIT_REFUSE, "authorization has expired or is not yet valid"),
    "NXG-A05": (EXIT_REFUSE, "authorization is malformed or its signature is invalid"),
    "NXG-A06": (EXIT_REFUSE, "operation is not allowed in this environment"),
    # NXG-A07 is retired (the CI-only test authorization was removed); never reuse it.
    "NXG-A08": (EXIT_REFUSE, "offline migration SQL requires NEXTUP_ALEMBIC_OFFLINE_REVIEW=1"),
    "NXG-A09": (EXIT_REFUSE, "migration failed; the whole transaction was rolled back"),
    "NXG-A10": (
        EXIT_REFUSE,
        "authorization tokens are accepted on standard input only, never as arguments",
    ),
    "NXG-A11": (EXIT_REFUSE, "migration was not confirmed; nothing was applied"),
    # entry points
    "NXG-X01": (EXIT_REFUSE, "command is not an allowed service command"),
}


class GuardError(Exception):
    """Base class: ``str()`` is always the fixed line for the code."""

    def __init__(self, code: str, *, env: str | None = None, keys: tuple[str, ...] = ()):
        if code not in CODES:
            code = "NXG-C14"
        self.code = code
        self.exit_code, self.description = CODES[code]
        # Only configuration-key names and the env name are ever echoed.
        self.keys = tuple(sorted({k for k in keys if _is_key_name(k)}))
        self.env = env if env in {"dev", "staging", "ci", "test", "personal"} else None
        super().__init__(self.line())

    def line(self) -> str:
        detail = self.description
        if self.keys:
            detail += " (" + ", ".join(self.keys) + ")"
        if self.env:
            detail += f" (env={self.env})"
        return f"nextup-guard: {self.verdict} {self.code} {detail}"

    verdict = "REFUSE"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r})"


class ConfigError(GuardError, ValueError):
    verdict = "CONFIG"


class SecretFileError(ConfigError):
    pass


class GuardRefused(GuardError):
    verdict = "REFUSE"


def _is_key_name(value: str) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value.replace("_", "").isalnum()
        and value.upper() == value
    )


def classify_connection_error(exc: BaseException) -> GuardError:
    """Map a driver/SQLAlchemy connection failure to a code without reading its text."""
    for candidate in (exc, getattr(exc, "orig", None), getattr(exc, "__cause__", None)):
        state = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if isinstance(state, str) and state.startswith("28"):
            return GuardRefused("NXG-C06")
        if state == "3D000":  # invalid_catalog_name
            return GuardRefused("NXG-I02")
    return GuardRefused("NXG-C05")
