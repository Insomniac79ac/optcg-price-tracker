#!/usr/bin/env bash
# Runs `alembic upgrade head` against a staging Postgres database. Intended
# to run either inside the Railway `api` service (`railway run --service api
# bash scripts/../staging_migrate.sh` isn't necessary - see docs/railway_staging.md
# for the plain `alembic upgrade head` one-liner Railway needs) or locally
# with services/api's Python dependencies installed and DATABASE_URL pointed
# at the staging Postgres instance (its private URL won't be reachable from
# outside Railway's network - use the public connection string for a local
# run, if the plugin exposes one, or run this from inside Railway instead).
#
# Fails fast: requires DATABASE_URL, refuses to run against
# APP_ENV=production unless ALLOW_PRODUCTION_MIGRATION=true, and does not
# touch Docker Compose at all (no `docker compose` calls here - this talks
# directly to whatever DATABASE_URL points at via alembic).
#
# Usage:
#   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db bash scripts/staging_migrate.sh
#
# Env vars:
#   DATABASE_URL   required. Full SQLAlchemy URL. Railway's Postgres plugin
#                  injects a bare postgresql:// URL - rewrite the scheme to
#                  postgresql+psycopg:// before passing it here (this app
#                  uses sync SQLAlchemy via psycopg, not an async driver).
#   APP_ENV        optional, default "staging". Refuses to run if this is
#                  "production" unless ALLOW_PRODUCTION_MIGRATION=true (use
#                  `make prod-migrate` for a real production deploy instead -
#                  this script is for staging).
#   ALLOW_PRODUCTION_MIGRATION   default false. Set true to explicitly
#                  override the APP_ENV=production refusal above.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"

APP_ENV="${APP_ENV:-staging}"
ALLOW_PRODUCTION_MIGRATION="${ALLOW_PRODUCTION_MIGRATION:-false}"

echo "== Staging migration (alembic upgrade head) =="
echo "APP_ENV=$APP_ENV"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "FAIL: DATABASE_URL is not set." >&2
  echo "Usage: DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db bash scripts/staging_migrate.sh" >&2
  exit 1
fi

if [[ "$APP_ENV" == "production" && "$ALLOW_PRODUCTION_MIGRATION" != "true" ]]; then
  echo "FAIL: APP_ENV=production - refusing to run scripts/staging_migrate.sh against production." >&2
  echo "Use 'make prod-migrate' for a real production deploy, or set" >&2
  echo "ALLOW_PRODUCTION_MIGRATION=true to explicitly override this refusal." >&2
  exit 1
fi

if [[ "$DATABASE_URL" != postgresql* ]]; then
  echo "FAIL: DATABASE_URL does not look like a postgresql(+psycopg):// URL." >&2
  exit 1
fi

if [[ "$DATABASE_URL" == postgresql://* ]]; then
  echo "NOTE: DATABASE_URL uses the bare 'postgresql://' scheme (e.g. straight from Railway's" >&2
  echo "Postgres plugin) - this app's SQLAlchemy setup expects 'postgresql+psycopg://'." >&2
  echo "Rewrite the scheme before running this script, or alembic/SQLAlchemy may fail to" >&2
  echo "select the psycopg driver correctly." >&2
fi

API_DIR="$repo_root/services/api"
if [[ ! -d "$API_DIR" ]]; then
  echo "FAIL: $API_DIR does not exist - is this the repo root ($repo_root)?" >&2
  exit 1
fi

if ! command -v alembic >/dev/null 2>&1; then
  echo "FAIL: 'alembic' is not on PATH." >&2
  echo "Install services/api's Python dependencies first:" >&2
  echo "  cd services/api && pip install -r requirements.txt" >&2
  echo "or run this migration inside the deployed Railway api service instead:" >&2
  echo "  railway run --service api alembic upgrade head" >&2
  echo "See docs/railway_staging.md section 3 for the Railway-side command." >&2
  exit 1
fi

cd "$API_DIR"
export DATABASE_URL
export APP_ENV

echo
echo "-- Current revision (before) --"
alembic current || true

echo
echo "-- Head revision(s) --"
alembic heads

echo
echo "-- Running: alembic upgrade head --"
alembic upgrade head

echo
echo "-- Current revision (after) --"
alembic current

echo
echo "Staging migration completed successfully."
