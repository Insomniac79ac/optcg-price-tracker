#!/usr/bin/env bash
# Phase 10 UX audit - verifies the mobile/tablet responsiveness and UX
# polish pass (responsive shell, responsive table system, filter/saved-view
# bar collapse, card vault/detail responsiveness, modal responsiveness,
# empty/loading/error consistency, price/source display, admin safety UI)
# didn't break anything that already worked: same standard checks as
# scripts/phase8_audit.sh/phase9_audit.sh, plus HTTP 200 checks across every
# route/endpoint this phase touched. Fails fast: stops at the first failing
# step.
#
# This is a UX/frontend polish pass, not a new feature - it never adds user
# accounts/login, never adds scraping logic (SNKRDUNK or otherwise), and
# never touches backend pricing/valuation formulas. Nothing here exercises
# any of that.
#
# Meant to be run against a live local/dev stack (`make dev-up`).
#
# Usage: scripts/phase10_ux_audit.sh
#
# Env vars:
#   SKIP_TESTS       default false - set true to skip the
#                    `docker compose exec api pytest` / `docker compose run
#                    --rm worker pytest` steps.
#   ADMIN_TOKEN      default local-dev-admin-token (matches docker-compose.yml's
#                    dev default), sent as X-Admin-Token on the admin curl
#                    checks below.
#   BASE_API_URL     default http://127.0.0.1:8000
#   BASE_WEB_URL     default http://127.0.0.1:3000

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

SKIP_TESTS="${SKIP_TESTS:-false}"
ADMIN_TOKEN="${ADMIN_TOKEN:-local-dev-admin-token}"
BASE_API_URL="${BASE_API_URL:-http://127.0.0.1:8000}"
BASE_WEB_URL="${BASE_WEB_URL:-http://127.0.0.1:3000}"

CURL_OPTS=(-sS --connect-timeout 5 --max-time 20)
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

fail() {
  echo "FAIL: $1" >&2
  echo "Phase 10 UX audit FAILED." >&2
  exit 1
}

http_get() {
  # $1 = url, optional $2 = "admin" to send the admin token header
  local url="$1" auth="${2:-}"
  if [[ "$auth" == "admin" ]]; then
    HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
      -H "X-Admin-Token: $ADMIN_TOKEN" "$url" 2>/dev/null) || HTTP_STATUS="000"
  else
    HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" "$url" 2>/dev/null) || HTTP_STATUS="000"
  fi
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

echo "== 3. Web route checks (BASE_WEB_URL=$BASE_WEB_URL) =="
WEB_ROUTES=(
  /dashboard
  /collection
  /collection/vault
  /wishlist
  /grading
  /analytics/digest
  /analytics/collection
  /analytics/wishlist
  /analytics/buy-decisions
  /analytics/sell-decisions
  /analytics/grading
  /analytics/portfolio-risk
  /admin/catalog-ops
  /admin/import-validation
  /admin/card-duplicates
  /admin/source-mapping-quality
  /admin/catalog-coverage
  /admin/price-source-health
  /admin/system-check
)
for route in "${WEB_ROUTES[@]}"; do
  http_status=$(curl -sS -L -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    "$BASE_WEB_URL$route" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    echo "PASS: GET $route returned 200"
  else
    fail "GET $route returned HTTP $http_status (expected 200)"
  fi
done
echo

echo "== 4. API endpoint checks (BASE_API_URL=$BASE_API_URL) =="
PUBLIC_GET_CHECKS=(
  "/health"
  "/saved-views?limit=5"
  "/analytics/digest"
  "/analytics/buy-decisions?limit=5"
  "/analytics/sell-decisions?limit=5"
)
for path in "${PUBLIC_GET_CHECKS[@]}"; do
  http_get "$BASE_API_URL$path"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "PASS: GET $path returned 200"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200)"
  fi
done

ADMIN_GET_CHECKS=(
  "/admin/catalog-coverage"
  "/admin/price-source-health"
  "/admin/source-mappings/quality?limit=5"
)
for path in "${ADMIN_GET_CHECKS[@]}"; do
  http_get "$BASE_API_URL$path" admin
  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "PASS: GET $path (admin) returned 200"
  else
    fail "GET $path (admin) returned HTTP $HTTP_STATUS (expected 200)"
  fi
done
echo

echo "== 5. Frontend viewport/overflow smoke tests =="
if [[ -f "apps/web/playwright.config.ts" || -f "apps/web/playwright.config.js" ]]; then
  (cd apps/web && npx playwright test ux-viewport-smoke) \
    || fail "apps/web viewport smoke tests"
else
  echo "skipped - no Playwright (or equivalent) frontend test setup exists in apps/web,"
  echo "and this audit intentionally does not add a heavy new test framework just for"
  echo "this check (see docs/manual_qa_checklist.md for the manual 360/768/1440px pass)."
fi
echo

echo "Phase 10 UX audit passed"
