#!/usr/bin/env bash
# Phase 7 completion audit - verifies that performance, pruning, caching,
# pagination, job locks, and background file jobs all work together. Fails
# fast: stops at the first failing step, same convention as
# scripts/final_audit.sh (which this is meant to run alongside/after - see
# RUN_PHASE7_AUDIT there). See docs/performance_testing.md.
#
# Meant to be run against a live local/dev stack (`make dev-up`).
#
# Usage: scripts/phase7_audit.sh
#
# Env vars:
#   SKIP_TESTS       default false - set true to skip the
#                    `docker compose exec api pytest` / `docker compose run
#                    --rm worker pytest` steps.
#   RUN_LOAD_TESTS   default false - set true to also run
#                    scripts/load_test_api.sh and scripts/load_test_web.sh.
#                    Off by default so this script stays fast enough to run
#                    routinely; the load tests take noticeably longer.
#   ADMIN_TOKEN      default local-dev-admin-token (matches docker-compose.yml's
#                    dev default), sent as X-Admin-Token on the admin curl
#                    checks below and forwarded to the load tests.
#   BASE_API_URL     default http://127.0.0.1:8000
#   WEB_BASE_URL     default http://127.0.0.1:3000

set -euo pipefail

# Resolve the repo root from this script's own location rather than
# `git rev-parse --show-toplevel` (which depends on the caller's current
# working directory and fails outright if invoked from outside the repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$repo_root"

SKIP_TESTS="${SKIP_TESTS:-false}"
RUN_LOAD_TESTS="${RUN_LOAD_TESTS:-false}"
ADMIN_TOKEN="${ADMIN_TOKEN:-local-dev-admin-token}"
BASE_API_URL="${BASE_API_URL:-http://127.0.0.1:8000}"
WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:3000}"
export ADMIN_TOKEN BASE_API_URL WEB_BASE_URL

fail() {
  echo "FAIL: $1" >&2
  echo "Phase 7 audit FAILED." >&2
  exit 1
}

echo "== 1. Secret check =="
bash scripts/check_secrets.sh || fail "scripts/check_secrets.sh"
echo

echo "== 2. Test suites (SKIP_TESTS=$SKIP_TESTS) =="
if [[ "$SKIP_TESTS" == "true" ]]; then
  echo "skipped (SKIP_TESTS=true)"
else
  docker compose exec api pytest \
    || fail "docker compose exec api pytest - is the dev stack up (make dev-up)?"
  docker compose run --rm worker pytest \
    || fail "docker compose run --rm worker pytest"
fi
echo

echo "== 3. Admin endpoint checks (BASE_API_URL=$BASE_API_URL) =="
ADMIN_CHECKS=(
  "/admin/db-index-audit"
  "/admin/performance/summary"
  "/admin/data-retention/policy"
  "/admin/cache/status"
  "/admin/job-locks"
  "/file-jobs"
)
for path in "${ADMIN_CHECKS[@]}"; do
  http_status=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    -H "X-Admin-Token: $ADMIN_TOKEN" "$BASE_API_URL$path" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    echo "PASS: GET $path returned 200"
  else
    fail "GET $path returned HTTP $http_status (expected 200)"
  fi
done
echo

echo "== 4. Web route smoke (WEB_BASE_URL=$WEB_BASE_URL) =="
WEB_BASE_URL="$WEB_BASE_URL" bash scripts/web_route_smoke.sh || fail "scripts/web_route_smoke.sh"
echo

echo "== 5. Load tests (RUN_LOAD_TESTS=$RUN_LOAD_TESTS) =="
if [[ "$RUN_LOAD_TESTS" == "true" ]]; then
  BASE_API_URL="$BASE_API_URL" ADMIN_TOKEN="$ADMIN_TOKEN" bash scripts/load_test_api.sh \
    || fail "scripts/load_test_api.sh"
  WEB_BASE_URL="$WEB_BASE_URL" bash scripts/load_test_web.sh \
    || fail "scripts/load_test_web.sh"
else
  echo "skipped (RUN_LOAD_TESTS=true to enable)"
fi
echo

echo "Phase 7 audit passed"
