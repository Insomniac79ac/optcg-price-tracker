#!/usr/bin/env bash
# Phase 8 completion audit - the standard checks (secrets, test suites,
# admin endpoints, web route smoke). The analytics digest and portfolio-risk
# features this audit originally covered were removed in Collector v1 S1
# (2026-10-13), so their checks were removed too.
# Fails fast: stops at the first failing step, same convention as
# scripts/phase7_audit.sh (which this is meant to run alongside/after).
#
# Meant to be run against a live local/dev stack (`make dev-up`).
#
# Usage: scripts/phase8_audit.sh
#
# Env vars:
#   SKIP_TESTS       default false - set true to skip the
#                    `docker compose exec api pytest` / `docker compose run
#                    --rm worker pytest` steps.
#   ADMIN_TOKEN      default local-dev-admin-token (matches docker-compose.yml's
#                    dev default), sent as X-Admin-Token on the admin curl
#                    checks below.
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
ADMIN_TOKEN="${ADMIN_TOKEN:-local-dev-admin-token}"
BASE_API_URL="${BASE_API_URL:-http://127.0.0.1:8000}"
WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:3000}"
export ADMIN_TOKEN BASE_API_URL WEB_BASE_URL

fail() {
  echo "FAIL: $1" >&2
  echo "Phase 8 audit FAILED." >&2
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
ADMIN_GET_CHECKS=(
  "/admin/cache/status"
  "/admin/system-check"
)
for path in "${ADMIN_GET_CHECKS[@]}"; do
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

echo "Phase 8 audit passed"
