#!/usr/bin/env bash
# Phase 8 completion audit - verifies that the analytics digest feature
# (backend service/endpoints/CLI/admin action, and the portfolio-risk work
# it builds on) actually works end to end on top of the standard checks.
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

repo_root="$(git rev-parse --show-toplevel)"
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

# Real POST - generates (and persists) one analytics_digest_reports row, the
# same side effect running the CLI or clicking the admin UI button would
# have. Feeds section 4's no-auth GET checks below, which need at least one
# stored report to return 200 instead of 404.
digest_post_status=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 30 \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"valuation_mode": "raw_market"}' \
  "$BASE_API_URL/admin/actions/generate-analytics-digest" 2>/dev/null) || digest_post_status="000"
if [[ "$digest_post_status" == "200" ]]; then
  echo "PASS: POST /admin/actions/generate-analytics-digest returned 200"
else
  fail "POST /admin/actions/generate-analytics-digest returned HTTP $digest_post_status (expected 200)"
fi
echo

echo "== 4. New analytics endpoint checks (BASE_API_URL=$BASE_API_URL) =="
# /analytics/digest and /analytics/portfolio-risk require a signed-in user
# session (there is no admin-token path for them, by design - see 'Analytics
# digest' in docs/operations.md), so this script can't fetch their 200
# response without a real OAuth session. It instead confirms both routes
# exist and correctly reject an unauthenticated request (401), which is
# still a real, meaningful check - a 404/500/000 here means the route is
# missing or broken, not just "needs a session".
SESSION_ONLY_CHECKS=(
  "/analytics/digest"
  "/analytics/portfolio-risk"
)
for path in "${SESSION_ONLY_CHECKS[@]}"; do
  http_status=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    "$BASE_API_URL$path" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "401" ]]; then
    echo "PASS: GET $path returned 401 (session required, as expected)"
  else
    fail "GET $path returned HTTP $http_status (expected 401 without a session)"
  fi
done

# The persisted-report endpoints are not session-gated (same convention as
# GET /market/report/latest) - after section 3's POST above, these must
# return real data.
NO_AUTH_CHECKS=(
  "/analytics/digest/latest"
  "/analytics/digest/reports"
)
for path in "${NO_AUTH_CHECKS[@]}"; do
  http_status=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    "$BASE_API_URL$path" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    echo "PASS: GET $path returned 200"
  else
    fail "GET $path returned HTTP $http_status (expected 200)"
  fi
done
echo

echo "== 5. Web route smoke (WEB_BASE_URL=$WEB_BASE_URL) =="
WEB_BASE_URL="$WEB_BASE_URL" bash scripts/web_route_smoke.sh || fail "scripts/web_route_smoke.sh"
echo

echo "Phase 8 audit passed"
