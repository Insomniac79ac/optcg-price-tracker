#!/usr/bin/env bash
# Postgres backup for the production stack (docker-compose.prod.yml by
# default) - runs pg_dump inside the postgres container via `docker compose
# exec` (no pg_dump/psql install needed on the host) and gzips the plain-SQL
# output straight onto the host filesystem.
#
# Usage: bash scripts/db_backup.sh   (also wired up as `make prod-db-backup`)
#
# Env vars (all optional - defaults match docker-compose.prod.yml /
# .env.production):
#   COMPOSE_FILE      default docker-compose.prod.yml
#   ENV_FILE          default .env.production - Compose only auto-loads a
#                     file literally named `.env`, so this is passed via
#                     --env-file explicitly whenever it exists (same as
#                     Makefile's PROD_COMPOSE - see docs/deployment.md).
#   POSTGRES_SERVICE  default postgres
#   POSTGRES_DB       default opcg
#   POSTGRES_USER     default opcg_prod - must match the deployment's actual
#                     POSTGRES_USER (see .env.production), not a real default.
#   BACKUP_DIR        default data/backups/db
#
# See "Database backup and restore drill" in docs/operations.md.

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-opcg}"
POSTGRES_USER="${POSTGRES_USER:-opcg_prod}"
BACKUP_DIR="${BACKUP_DIR:-data/backups/db}"

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE+=(--env-file "$ENV_FILE")
fi

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
out_file="$BACKUP_DIR/opcg_db_backup_${timestamp}.sql.gz"
tmp_file="${out_file}.partial"

# Write to a .partial file and only rename it into place on success - a
# shell redirect creates its target file before the command behind it ever
# runs, so a failed pg_dump would otherwise still leave a garbage/empty
# .sql.gz behind under the real name.
cleanup() { rm -f "$tmp_file"; }
trap cleanup EXIT

echo "Backing up '$POSTGRES_DB' from service '$POSTGRES_SERVICE' ($COMPOSE_FILE)..."

# --clean --if-exists emits DROP ... IF EXISTS before each CREATE, so the
# dump can be re-applied into a database that already has the schema
# without erroring on every "already exists" - see db_restore.sh and
# "Restore Postgres" in docs/operations.md, which relies on the same
# --clean --if-exists behavior (there via pg_restore, here via plain SQL).
#
# pipefail (set above) makes this fail if pg_dump itself fails, even though
# its exit code would otherwise be swallowed by the pipe into gzip.
"${COMPOSE[@]}" exec -T "$POSTGRES_SERVICE" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists | gzip > "$tmp_file"

mv "$tmp_file" "$out_file"
echo "Backup written to $out_file"
