#!/usr/bin/env bash
# Post-deploy smoke test for a running production stack
# (docker-compose.prod.yml) - checks the web app, its health endpoint, a
# handful of pages, and (optionally) the API directly. Prints PASS/FAIL per
# check; the final line on success is exactly "Production smoke test
# passed", so it's grep-able from CI/deploy tooling.
#
# Usage: scripts/prod_smoke_test.sh   (also wired up as `make prod-smoke`)
#
# Env vars:
#   ADMIN_TOKEN  required - fails fast (before running any checks) if unset.
#                Must match the target deployment's configured ADMIN_TOKEN.
#   BASE_URL     default http://127.0.0.1:3000 - the web app. In
#                docker-compose.prod.yml, `web` is published on
#                ${WEB_PORT:-3000}, so this matches an unmodified deploy on
#                the same host.
#   API_URL      optional, unset by default. docker-compose.prod.yml does
#                NOT publish the api service to the host by default (see
#                "expose api only if needed" in docker-compose.prod.yml) -
#                api/admin checks below are skipped unless you explicitly
#                set this (e.g. API_URL=http://127.0.0.1:8000 if you've
#                added a `ports:` mapping for api, or API_URL=http://api:8000
#                if you're running this script from another container on
#                the same compose network).
#
# See docs/operations.md for post-deployment usage.

set -uo pipefail

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "FAIL: ADMIN_TOKEN is required (fail-fast: refusing to run any checks without it)." >&2
  exit 1
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:3000}"
API_URL="${API_URL:-}"

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

echo "== OPTCG production smoke test =="
echo "BASE_URL=$BASE_URL"
echo "API_URL=${API_URL:-<unset - skipping direct API checks>}"
echo

echo "-- 1. Web health (GET \$BASE_URL/api/health) --"
http_get "$BASE_URL/api/health"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "GET $BASE_URL/api/health returned HTTP $HTTP_STATUS (expected 200)"
else
  status_field="$(json_field status)"
  if [[ "$status_field" == "ok" ]]; then
    pass "GET $BASE_URL/api/health status=ok"
  else
    fail "GET $BASE_URL/api/health status='$status_field' (expected 'ok')"
  fi
fi
echo

# /dashboard and /collection require a signed-in user (see
# apps/web/middleware.ts) - an anonymous request redirects to
# /market/movers rather than rendering. -L follows that redirect, so these
# checks verify "the app is up and routing works", not "the page itself
# rendered" - the same tradeoff scripts/smoke_test.sh already makes for
# /dashboard in the dev stack.
echo "-- 2. Frontend pages --"
for page in /dashboard /market/report /collection /search; do
  http_get "$BASE_URL$page" -L
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET $BASE_URL$page returned 200"
  else
    fail "GET $BASE_URL$page returned HTTP $HTTP_STATUS (expected 200)"
  fi
done
echo

if [[ -z "$API_URL" ]]; then
  echo "-- 3. API checks skipped (API_URL not set) --"
  echo
else
  echo "-- 3. API health (GET \$API_URL/health) --"
  http_get "$API_URL/health"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "GET $API_URL/health returned HTTP $HTTP_STATUS (expected 200)"
  else
    status_field="$(json_field status)"
    if [[ "$status_field" == "ok" ]]; then
      pass "GET $API_URL/health status=ok"
    else
      fail "GET $API_URL/health status='$status_field' (expected 'ok')"
    fi
  fi
  echo

  echo "-- 4. Admin env check (GET \$API_URL/admin/env-check) --"
  http_get "$API_URL/admin/env-check" -H "X-Admin-Token: $ADMIN_TOKEN"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "GET $API_URL/admin/env-check returned HTTP $HTTP_STATUS (expected 200)"
  else
    status_field="$(json_field status)"
    if [[ "$status_field" == "critical" ]]; then
      fail "GET $API_URL/admin/env-check status=critical - production environment is misconfigured"
    else
      pass "GET $API_URL/admin/env-check status=$status_field"
    fi
  fi
  echo

  echo "-- 5. Admin system check (GET \$API_URL/admin/system-check) --"
  http_get "$API_URL/admin/system-check" -H "X-Admin-Token: $ADMIN_TOKEN"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "GET $API_URL/admin/system-check returned HTTP $HTTP_STATUS (expected 200)"
  else
    status_field="$(json_field status)"
    if [[ "$status_field" == "critical" ]]; then
      fail "GET $API_URL/admin/system-check status=critical - see /admin/system-check in the web UI for details"
    else
      pass "GET $API_URL/admin/system-check status=$status_field"
    fi
  fi
  echo
fi

echo "== Summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Production smoke test passed"
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
