#!/usr/bin/env bash
# Final production readiness audit - the last gate before treating this app
# as production-ready. Unlike scripts/release_check.sh and
# scripts/prod_verify.sh (which run every check and print a summary at the
# end), this script fails fast: it stops at the first failing step, since a
# broken step here means the audit did not pass and there's no value in
# grinding through the rest.
#
# Meant to be run on the actual deploy host (or a CI job) once
# .env.production and the dev stack (for the pytest steps) already exist -
# see docs/deployment.md and docs/release_checklist.md for how this fits
# into the release process.
#
# Usage: scripts/final_audit.sh   (also wired up as `make final-audit`)
#
# Env vars:
#   SKIP_TESTS    default false - set SKIP_TESTS=true to skip the
#                 `docker compose exec api pytest` / `docker compose run
#                 --rm worker pytest` steps (e.g. when the dev stack isn't
#                 up, or in a context where running the full suite is too
#                 slow).
#   ALLOW_DIRTY   default false - forwarded to scripts/release_check.sh,
#                 which reads it directly; set ALLOW_DIRTY=true to allow an
#                 unclean git working tree through that check.
#   SKIP_WEB_SMOKE  default false - set SKIP_WEB_SMOKE=true to skip
#                 scripts/web_route_smoke.sh entirely. Even when not set,
#                 the web route smoke step only runs if WEB_BASE_URL (default
#                 http://127.0.0.1:3000) actually answers - it's skipped
#                 (not failed) rather than requiring every environment this
#                 script runs in to also have the web container up.
#   WEB_BASE_URL  default http://127.0.0.1:3000 - forwarded to
#                 scripts/web_route_smoke.sh.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

SKIP_TESTS="${SKIP_TESTS:-false}"
ALLOW_DIRTY="${ALLOW_DIRTY:-false}"
SKIP_WEB_SMOKE="${SKIP_WEB_SMOKE:-false}"
WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:3000}"
export ALLOW_DIRTY

fail() {
  echo "FAIL: $1"
  echo "Final production readiness audit FAILED."
  exit 1
}

echo "== 1. Secret check =="
bash scripts/check_secrets.sh || fail "scripts/check_secrets.sh"
echo

echo "== 2. Release check (ALLOW_DIRTY=$ALLOW_DIRTY) =="
bash scripts/release_check.sh || fail "scripts/release_check.sh"
echo

# --env-file is required for docker compose to resolve ${VAR} substitutions
# in docker-compose.prod.yml itself (the per-service `env_file:` directive is
# a separate mechanism, resolved at container-start time) - see the
# PROD_COMPOSE comment in the Makefile.
echo "== 3. docker compose config (docker-compose.prod.yml) =="
docker compose -f docker-compose.prod.yml --env-file .env.production config >/dev/null \
  || fail "docker compose -f docker-compose.prod.yml config"
echo

echo "== 4. docker compose config (docker-compose.prod.yml + docker-compose.prod.private.yml) =="
docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml \
  --env-file .env.production config >/dev/null \
  || fail "docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml config"
echo

echo "== 5. Test suites (SKIP_TESTS=$SKIP_TESTS) =="
if [[ "$SKIP_TESTS" == "true" ]]; then
  echo "skipped (SKIP_TESTS=true)"
else
  docker compose exec api pytest \
    || fail "docker compose exec api pytest - is the dev stack up (make dev-up)?"
  docker compose run --rm worker pytest \
    || fail "docker compose run --rm worker pytest"
fi
echo

echo "== 6. Web route smoke (SKIP_WEB_SMOKE=$SKIP_WEB_SMOKE) =="
if [[ "$SKIP_WEB_SMOKE" == "true" ]]; then
  echo "skipped (SKIP_WEB_SMOKE=true)"
elif ! curl -sS --connect-timeout 3 --max-time 5 -o /dev/null "$WEB_BASE_URL" 2>/dev/null; then
  echo "skipped (WEB_BASE_URL=$WEB_BASE_URL is not reachable - is the web container up?)"
else
  WEB_BASE_URL="$WEB_BASE_URL" bash scripts/web_route_smoke.sh \
    || fail "scripts/web_route_smoke.sh"
fi
echo

echo "== 7. Required files present =="
REQUIRED_FILES=(
  VERSION
  CHANGELOG.md
  docs/release_checklist.md
  docs/route_inventory.md
  scripts/prod_smoke_test.sh
  scripts/prod_verify.sh
  scripts/db_backup.sh
  scripts/db_restore.sh
  scripts/db_backup_prune.sh
  scripts/web_route_smoke.sh
)
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    echo "PASS: $f exists"
  else
    fail "$f is missing"
  fi
done
echo

echo "Final production readiness audit passed"
