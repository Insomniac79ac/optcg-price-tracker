#!/usr/bin/env bash
# Postgres restore for the production stack (docker-compose.prod.yml by
# default) - the inverse of scripts/db_backup.sh. Overwrites the target
# database, so it refuses to run without an explicit CONFIRM_RESTORE=RESTORE
# and a backup file that actually exists.
#
# Usage:
#   CONFIRM_RESTORE=RESTORE bash scripts/db_restore.sh data/backups/db/opcg_db_backup_<ts>.sql.gz
#   (also wired up as `make prod-db-restore BACKUP=<path>`)
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
#   CONFIRM_RESTORE   required - must be exactly RESTORE.
#
# See "Database backup and restore drill" in docs/operations.md.

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-opcg}"
POSTGRES_USER="${POSTGRES_USER:-opcg_prod}"

if [[ $# -lt 1 ]]; then
  echo "Usage: CONFIRM_RESTORE=RESTORE bash scripts/db_restore.sh <backup-file>.sql.gz" >&2
  exit 1
fi

BACKUP_FILE="$1"

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "FAIL: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-}" != "RESTORE" ]]; then
  echo "Refusing to restore without confirmation." >&2
  echo "Set CONFIRM_RESTORE=RESTORE to proceed:" >&2
  echo "  CONFIRM_RESTORE=RESTORE bash scripts/db_restore.sh $BACKUP_FILE" >&2
  exit 1
fi

echo "=============================================================="
echo "WARNING: this will overwrite the '$POSTGRES_DB' database on"
echo "service '$POSTGRES_SERVICE' ($COMPOSE_FILE) with:"
echo "  $BACKUP_FILE"
echo "This cannot be undone. Existing data in that database will be lost."
echo "=============================================================="

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE+=(--env-file "$ENV_FILE")
fi

# Only api/worker/beat/web write to or depend on the database - postgres and
# redis themselves are left running throughout. Only stop/restart services
# that were actually running (and only for the prod compose file - the dev
# stack's restore flow doesn't need this ceremony).
#
# restart_services is idempotent and registered as an EXIT trap, not just
# called inline after a successful restore: `set -e` means a failed restore
# or migration step below jumps straight past any inline restart call,
# which would otherwise leave the stack stopped after a failed attempt. The
# trap fires either way, so services never end up down for longer than the
# restore itself takes.
RESTART_SERVICES=()
services_stopped=false

restart_services() {
  if [[ "$services_stopped" == true ]]; then
    echo "Restarting services: ${RESTART_SERVICES[*]}"
    "${COMPOSE[@]}" start "${RESTART_SERVICES[@]}"
    services_stopped=false
  fi
}
trap restart_services EXIT

if [[ "$COMPOSE_FILE" == *prod* ]]; then
  running="$("${COMPOSE[@]}" ps --status running --services 2>/dev/null || true)"
  for svc in api worker beat web; do
    if grep -qx "$svc" <<<"$running"; then
      RESTART_SERVICES+=("$svc")
    fi
  done
  if [[ ${#RESTART_SERVICES[@]} -gt 0 ]]; then
    echo "Stopping services before restore: ${RESTART_SERVICES[*]}"
    "${COMPOSE[@]}" stop "${RESTART_SERVICES[@]}"
    services_stopped=true
  fi
fi

echo "Restoring $BACKUP_FILE into '$POSTGRES_DB'..."
# ON_ERROR_STOP=1 - psql otherwise logs an error per failing statement and
# keeps going, which for a restore could silently apply the dump partially
# instead of failing loudly.
gunzip -c "$BACKUP_FILE" | "${COMPOSE[@]}" exec -T "$POSTGRES_SERVICE" \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

restart_services

echo "Running migrations..."
"${COMPOSE[@]}" exec api alembic upgrade head

echo
echo "Restore complete. Next, run the smoke test:"
echo "  ADMIN_TOKEN=<token> make prod-smoke"
