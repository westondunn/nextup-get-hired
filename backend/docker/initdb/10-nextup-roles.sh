#!/usr/bin/env bash
# Nextup OSS first-boot role provisioning.
#
# Mounted read-only at /docker-entrypoint-initdb.d. The official postgres image runs it
# ONLY when the data directory is empty, as the bootstrap superuser (POSTGRES_USER,
# nextup_E_admin), against the temporary init server.
#
# It creates (or, when re-run by an operator, re-applies):
#   nextup_E_owner  schema owner and migrator; no superuser/createrole/replication/bypassrls;
#                   CREATEDB only in CI (nextup_ci) for the disposable migration suites;
#                   also in CI only, SET on the parameter nextup.provisioning
#   nextup_E_app    runtime DML only; NOINHERIT; no CREATE on the database or schema
#   database nextup_E owned by nextup_E_owner, pg_trgm, schema and default privileges
#   nextup.provisioning = 'complete-v1' on nextup_E: reset first, set last, so the guard
#   can tell a completed provisioning from an interrupted one (NXG-I10)
#
# Re-running is non-destructive and is the recovery path for an interrupted first boot
# (a deliberate operator step): roles
# and the database are created only if missing, attributes, passwords and grants are
# re-applied, nothing is dropped, and an application database owned by anyone else is
# refused.
#
# Passwords are read from files copied by the Compose root-phase step into the
# postgres-owned tmpfs /run/nextup-initdb (mode 0700, files 0400). They are read with
# psql backticks, so they never appear on a command line, in `ps`, or in the environment,
# and statement logging is disabled for this session so a failed statement cannot log them.
# No marker and no tables are created: the first `guard apply` (INIT) does that.
set -Eeuo pipefail
set +x

refuse() { echo "nextup-initdb: refusing: $1" >&2; exit 1; }

# psql is a libpq client: PGHOST, PGHOSTADDR, PGPORT, PGSERVICE or PGDATABASE would point this
# script at another server, PGUSER at another role, PGOPTIONS would plant session settings.
# Provisioning runs against the local init server over the default socket with nothing
# client-supplied. Allowed: PGDATA (the server's data directory,
# not a client variable) and PGPASSWORD, which the image's entrypoint itself exports for the
# init phase. Names only are printed, never values.
for name in $(compgen -e); do
  case "$name" in
    PGDATA | PGPASSWORD) ;;
    PG[A-Z]*) refuse "$name is not allowed" ;;
  esac
done

admin="${POSTGRES_USER:-}"
prefix="${admin%_admin}"
case "$prefix" in
  nextup_dev | nextup_stg | nextup_ci) ;;
  *) refuse "bootstrap user is not nextup_<dev|stg|ci>_admin" ;;
esac
[ "$admin" = "${prefix}_admin" ] || refuse "bootstrap user is not ${prefix}_admin"
[ "${POSTGRES_DB:-}" = "postgres" ] || refuse "POSTGRES_DB must be postgres (the application database is created here)"

dir=/run/nextup-initdb
for name in db_owner_password db_app_password; do
  file="$dir/$name"
  [ -f "$file" ] && [ ! -L "$file" ] && [ -r "$file" ] || refuse "password file $name is missing or unreadable"
  # 24-256 URL-safe characters, one line (the same rule the application enforces).
  grep -Eq '^[A-Za-z0-9_-]{24,256}$' "$file" || refuse "password file $name does not meet the strength rules"
  [ "$(wc -l < "$file")" -le 1 ] || refuse "password file $name has more than one line"
done
cmp -s "$dir/db_owner_password" "$dir/db_app_password" && refuse "owner and app passwords must differ"

createdb=NOCREATEDB
ci=0
if [ "$prefix" = nextup_ci ]; then
  createdb=CREATEDB
  ci=1
fi

psql --no-psqlrc -v ON_ERROR_STOP=1 -q --username "$admin" --dbname postgres \
  -v owner="${prefix}_owner" -v app="${prefix}_app" -v db="$prefix" -v createdb="$createdb" \
  -v ci="$ci" <<'SQL'
\set ECHO none
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;

-- Refuse to touch an application database that someone else owns (repair safety).
SELECT 'DO $refuse$ BEGIN RAISE EXCEPTION ''application database exists with a foreign owner''; END $refuse$'
  FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba
 WHERE d.datname = :'db' AND r.rolname <> :'owner' \gexec

-- An interrupted earlier run must not keep claiming completion.
SELECT format('ALTER DATABASE %I RESET nextup.provisioning', :'db')
 WHERE EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec

SELECT format('CREATE ROLE %I', :'owner') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner') \gexec
SELECT format('CREATE ROLE %I', :'app') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
\set owner_pw `cat /run/nextup-initdb/db_owner_password`
\set app_pw `cat /run/nextup-initdb/db_app_password`
ALTER ROLE :"owner" LOGIN PASSWORD :'owner_pw'
  NOSUPERUSER NOCREATEROLE :createdb NOBYPASSRLS NOREPLICATION INHERIT;
ALTER ROLE :"app" LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS NOREPLICATION NOINHERIT;
\unset owner_pw
\unset app_pw
-- Neither role may act as the other (warnings only when no membership exists).
REVOKE :"owner" FROM :"app";
REVOKE :"app" FROM :"owner";

SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING %L', :'db', :'owner', 'UTF8')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"owner";
GRANT CONNECT ON DATABASE :"db" TO :"app";
REVOKE TEMPORARY ON DATABASE :"db" FROM :"app";
REVOKE CONNECT, TEMPORARY ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE template1 FROM PUBLIC;

\if :ci
-- CI only: the migration suites create disposable databases as the CI owner,
-- which must then record provisioning for each one (ALTER DATABASE ... SET). PostgreSQL lets
-- a non-superuser store a custom parameter only with this privilege. It covers this one
-- parameter and this one role. A parameter privilege is cluster-wide, so it is acceptable
-- only here: a disposable CI instance whose databases are all synthetic. No other
-- environment, the runtime role and PUBLIC never receive it.
GRANT SET ON PARAMETER nextup.provisioning TO "nextup_ci_owner";
-- CI only: disposable nextup_migration_test_<hex> databases are cloned from template1 and
-- need the same extension and system-identifier grant as the application database.
\connect template1
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"owner", :"app";
\endif

\connect :"db"
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
-- PostgreSQL 15+: schema public is owned by pg_database_owner (= the owner role here).
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";
-- Identity factor for the guard; function privileges are per database.
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"owner", :"app";
-- Runtime DML on objects the owner creates later. The guard revokes app writes on
-- alembic_version, the marker and the ledger after every authorized migration.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Must stay the final statement: everything above succeeded.
ALTER DATABASE :"db" SET nextup.provisioning = 'complete-v1';
SQL

echo "nextup-initdb: provisioning of ${prefix} complete (roles ${prefix}_owner, ${prefix}_app; database ${prefix})"
