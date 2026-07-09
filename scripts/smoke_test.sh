#!/usr/bin/env bash
# Smoke test for a running OPTCG price tracker stack (local dev or a real
# deployment) - checks API health, market data, admin auth, and the web app.
# Prints PASS/FAIL for each check and exits non-zero if any check failed.
#
# Usage: scripts/smoke_test.sh   (also wired up as `make smoke-test`)
#
# Env vars:
#   API_URL      default http://localhost:8000
#   WEB_URL      default http://localhost:3000
#   ADMIN_TOKEN  required - must match the target's configured ADMIN_TOKEN
#
# See docs/operations.md for local and post-deployment usage.

set -uo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

CURL_OPTS=(-sS --connect-timeout 5 --max-time 15)

FAILURES=0
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }

# Sets HTTP_STATUS and writes the response body to $BODY_FILE.
http_get() {
  local url="$1"
  shift
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" "$url" "$@" 2>/dev/null) \
    || HTTP_STATUS="000"
}

# json_field <field_name> - reads $BODY_FILE, prints the field's value
# ("true"/"false" for booleans, "" if missing/unparseable).
json_field() {
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    value = data.get(sys.argv[2])
    if isinstance(value, bool):
        print('true' if value else 'false')
    elif value is None:
        print('')
    else:
        print(value)
except Exception:
    print('')
" "$BODY_FILE" "$1"
}

is_json_array() {
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    sys.exit(0 if isinstance(data, list) else 1)
except Exception:
    sys.exit(1)
" "$BODY_FILE"
}

echo "== OPTCG smoke test =="
echo "API_URL=$API_URL"
echo "WEB_URL=$WEB_URL"
echo

echo "-- 1. API health --"
http_get "$API_URL/health"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "GET /health returned HTTP $HTTP_STATUS (expected 200)"
else
  status_field="$(json_field status)"
  db_connected="$(json_field database_connected)"

  if [[ "$status_field" == "ok" ]]; then
    pass "GET /health status=ok"
  else
    fail "GET /health status='$status_field' (expected 'ok')"
  fi

  if [[ "$db_connected" == "true" ]]; then
    pass "GET /health database_connected=true"
  else
    fail "GET /health database_connected='$db_connected' (expected true)"
  fi
fi
echo

echo "-- 2. Market movers --"
http_get "$API_URL/market/movers"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "GET /market/movers returned HTTP $HTTP_STATUS (expected 200)"
elif is_json_array; then
  pass "GET /market/movers returned a valid JSON array"
else
  fail "GET /market/movers did not return a valid JSON array"
fi
echo

echo "-- 3. Admin auth --"
http_get "$API_URL/admin/refresh-runs"
if [[ "$HTTP_STATUS" == "401" ]]; then
  pass "GET /admin/refresh-runs without a token returned 401"
else
  fail "GET /admin/refresh-runs without a token returned HTTP $HTTP_STATUS (expected 401)"
fi

if [[ -z "$ADMIN_TOKEN" ]]; then
  fail "ADMIN_TOKEN is not set - cannot verify authenticated admin access"
else
  http_get "$API_URL/admin/refresh-runs" -H "X-Admin-Token: $ADMIN_TOKEN"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET /admin/refresh-runs with X-Admin-Token returned 200"
  else
    fail "GET /admin/refresh-runs with X-Admin-Token returned HTTP $HTTP_STATUS (expected 200)"
  fi
fi
echo

echo "-- 4. Web app --"
http_get "$WEB_URL/dashboard" -L
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET $WEB_URL/dashboard returned 200"
else
  fail "GET $WEB_URL/dashboard returned HTTP $HTTP_STATUS (expected 200)"
fi
echo

echo "== Summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "All checks passed."
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
