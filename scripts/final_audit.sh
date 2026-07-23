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
#                 scripts/web_route_smoke.sh. `BASE_WEB_URL` (the name every
#                 other audit script in this repo reads) is also accepted as
#                 an alias, so setting one consistently across a whole audit
#                 run works regardless of which script you're calling -
#                 WEB_BASE_URL wins if both happen to be set.
#   RUN_PHASE7_AUDIT  default false - set RUN_PHASE7_AUDIT=true to also run
#                 scripts/phase7_audit.sh (Phase 7 performance/scale audit -
#                 see docs/performance_testing.md). Off by default so this
#                 script stays fast; RUN_LOAD_TESTS is forwarded to it
#                 unchanged (also default false there), so even with
#                 RUN_PHASE7_AUDIT=true the load tests themselves stay opt-in.
#   RUN_PHASE9_AUDIT  default false - set RUN_PHASE9_AUDIT=true to also run
#                 scripts/phase9_audit.sh (Phase 9 catalog-operations audit -
#                 see 'Catalog operations workflow' in docs/operations.md).
#                 Off by default, same reasoning as RUN_PHASE7_AUDIT above;
#                 ADMIN_TOKEN/BASE_API_URL are forwarded to it unchanged.
#   RUN_RELEASE_CANDIDATE_AUDIT  default false - set true to also run
#                 scripts/release_candidate_audit.sh (Phase 11 release-
#                 candidate audit - see docs/release_candidate_report.md).
#                 Off by default, same reasoning as RUN_PHASE7_AUDIT/
#                 RUN_PHASE9_AUDIT above - this script itself already runs
#                 as part of scripts/release_candidate_audit.sh's own phase-
#                 audit step, so running it from here too would normally be
#                 redundant; ADMIN_TOKEN/BASE_API_URL/WEB_BASE_URL are
#                 forwarded to it unchanged (as BASE_API_URL/BASE_WEB_URL).

set -euo pipefail

# Resolve the repo root from this script's own location rather than
# `git rev-parse --show-toplevel` (which depends on the caller's current
# working directory and fails outright if invoked from outside the repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$repo_root"

SKIP_TESTS="${SKIP_TESTS:-false}"
ALLOW_DIRTY="${ALLOW_DIRTY:-false}"
SKIP_WEB_SMOKE="${SKIP_WEB_SMOKE:-false}"
WEB_BASE_URL="${WEB_BASE_URL:-${BASE_WEB_URL:-http://127.0.0.1:3000}}"
RUN_PHASE7_AUDIT="${RUN_PHASE7_AUDIT:-false}"
RUN_PHASE9_AUDIT="${RUN_PHASE9_AUDIT:-false}"
RUN_RELEASE_CANDIDATE_AUDIT="${RUN_RELEASE_CANDIDATE_AUDIT:-false}"
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
  scripts/phase7_audit.sh
  scripts/load_test_api.sh
  scripts/load_test_web.sh
  docs/performance_testing.md
  scripts/phase9_audit.sh
  scripts/phase10_ux_audit.sh
  scripts/release_candidate_audit.sh
  docs/release_candidate_report.md
  docs/release_blockers.md
)
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    echo "PASS: $f exists"
  else
    fail "$f is missing"
  fi
done
echo

echo "== 8. Phase 7 audit (RUN_PHASE7_AUDIT=$RUN_PHASE7_AUDIT) =="
if [[ "$RUN_PHASE7_AUDIT" == "true" ]]; then
  SKIP_TESTS="$SKIP_TESTS" WEB_BASE_URL="$WEB_BASE_URL" bash scripts/phase7_audit.sh \
    || fail "scripts/phase7_audit.sh"
else
  echo "skipped (RUN_PHASE7_AUDIT=true to enable)"
fi
echo

echo "== 9. scripts/phase9_audit.sh is executable =="
if [[ -x scripts/phase9_audit.sh ]]; then
  echo "PASS: scripts/phase9_audit.sh is executable"
else
  fail "scripts/phase9_audit.sh is not executable (chmod +x scripts/phase9_audit.sh)"
fi
echo

echo "== 10. Phase 9 audit (RUN_PHASE9_AUDIT=$RUN_PHASE9_AUDIT) =="
if [[ "$RUN_PHASE9_AUDIT" == "true" ]]; then
  SKIP_TESTS="$SKIP_TESTS" WEB_BASE_URL="$WEB_BASE_URL" bash scripts/phase9_audit.sh \
    || fail "scripts/phase9_audit.sh"
else
  echo "skipped (RUN_PHASE9_AUDIT=true to enable)"
fi
echo

echo "== 11. scripts/release_candidate_audit.sh is executable =="
if [[ -x scripts/release_candidate_audit.sh ]]; then
  echo "PASS: scripts/release_candidate_audit.sh is executable"
else
  fail "scripts/release_candidate_audit.sh is not executable (chmod +x scripts/release_candidate_audit.sh)"
fi
echo

echo "== 12. Release candidate audit (RUN_RELEASE_CANDIDATE_AUDIT=$RUN_RELEASE_CANDIDATE_AUDIT) =="
if [[ "$RUN_RELEASE_CANDIDATE_AUDIT" == "true" ]]; then
  SKIP_TESTS="$SKIP_TESTS" RUN_PHASE_AUDITS=false BASE_WEB_URL="$WEB_BASE_URL" \
    bash scripts/release_candidate_audit.sh \
    || fail "scripts/release_candidate_audit.sh"
else
  echo "skipped (RUN_RELEASE_CANDIDATE_AUDIT=true to enable)"
fi
echo

echo "Final production readiness audit passed"
