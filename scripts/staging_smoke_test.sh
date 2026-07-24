#!/usr/bin/env bash
# Post-deploy smoke test for a staging deployment (Vercel web + Railway api).
# Checks a handful of API endpoints and web pages, prints PASS/FAIL per
# check, and exits non-zero if anything failed. Does not run any destructive
# action (no writes, no admin mutations) and does not require Docker Compose
# - this is meant to run from your own machine or CI against the deployed
# staging URLs, same shape as scripts/prod_smoke_test.sh but pointed at the
# Vercel/Railway staging deployment instead of a local docker-compose.prod.yml
# stack.
#
# Usage:
#   STAGING_API_URL=https://<railway-api-url> \
#   STAGING_WEB_URL=https://<vercel-staging-url> \
#   ADMIN_TOKEN=<staging-admin-token> \
#   bash scripts/staging_smoke_test.sh
#
# STAGING_WEB_URL and ADMIN_TOKEN may be left unset to skip their checks
# (e.g. before Vercel is deployed).
#
# Env vars:
#   STAGING_API_URL   required. The Railway api service's public HTTPS URL.
#                     Fails fast with a clear message if unset.
#   STAGING_WEB_URL   optional. The Vercel staging deployment's URL. Only
#                     gates the web page checks (step 6) - leave unset/empty
#                     to skip those when the Vercel deployment isn't up yet;
#                     every API check still runs.
#   ADMIN_TOKEN       optional. Must match the staging deployment's
#                     configured ADMIN_TOKEN. Only gates the two admin
#                     checks below (system-check, catalog-coverage) - every
#                     other check runs regardless.
#
# See docs/staging_deployment.md section 8 and docs/staging_checklist.md.

set -uo pipefail

STAGING_API_URL="${STAGING_API_URL:-}"
STAGING_WEB_URL="${STAGING_WEB_URL:-}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

if [[ -z "$STAGING_API_URL" ]]; then
  echo "FAIL: STAGING_API_URL is not set." >&2
  echo "Usage: STAGING_API_URL=https://<railway-api-url> [STAGING_WEB_URL=https://<vercel-staging-url>] [ADMIN_TOKEN=<token>] bash scripts/staging_smoke_test.sh" >&2
  exit 1
fi

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

# A 200 or 401 are both healthy outcomes for session-gated routes without a
# real signed-in browser session in hand (see /analytics/digest,
# /saved-views - same convention as scripts/release_candidate_audit.sh's
# public_or_session_get). Anything else means the route is broken.
api_get_public_or_session() {
  local path="$1"
  http_get "$STAGING_API_URL$path"
  if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "401" ]]; then
    pass "GET $path returned $HTTP_STATUS"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200 or 401)"
  fi
}

web_get() {
  local path="$1"
  http_get "$STAGING_WEB_URL$path" -L
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET $path returned 200"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200)"
  fi
}

echo "== OPTCG staging smoke test =="
echo "STAGING_API_URL=$STAGING_API_URL"
echo "STAGING_WEB_URL=$STAGING_WEB_URL"
if [[ -n "$ADMIN_TOKEN" ]]; then
  echo "ADMIN_TOKEN=<set>"
else
  echo "ADMIN_TOKEN=<unset - skipping admin checks>"
fi
echo

echo "-- 1. API health (GET \$STAGING_API_URL/health) --"
http_get "$STAGING_API_URL/health"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "GET $STAGING_API_URL/health returned HTTP $HTTP_STATUS (expected 200)"
else
  status_field="$(json_field status)"
  if [[ "$status_field" == "ok" ]]; then
    pass "GET /health status=ok"
  else
    fail "GET /health status='$status_field' (expected 'ok')"
  fi
fi
echo

echo "-- 2. API version (GET \$STAGING_API_URL/version) --"
http_get "$STAGING_API_URL/version"
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /version returned 200 (version=$(json_field version), git_commit=$(json_field git_commit))"
elif [[ "$HTTP_STATUS" == "404" ]]; then
  echo "SKIP: GET /version returned 404 - route does not exist, skipping"
else
  fail "GET /version returned HTTP $HTTP_STATUS (route exists but is broken)"
fi
echo

echo "-- 3. API analytics digest / saved views (session-gated, 200 or 401 both healthy) --"
api_get_public_or_session "/analytics/digest"
api_get_public_or_session "/saved-views?limit=5"
echo

if [[ -z "$ADMIN_TOKEN" ]]; then
  echo "-- 4. Admin checks (system-check, catalog-coverage) --"
  echo "Skipping (ADMIN_TOKEN not set)."
  echo
else
  echo "-- 4. Admin system check (GET \$STAGING_API_URL/admin/system-check) --"
  http_get "$STAGING_API_URL/admin/system-check" -H "X-Admin-Token: $ADMIN_TOKEN"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "GET /admin/system-check returned HTTP $HTTP_STATUS (expected 200)"
  else
    status_field="$(json_field status)"
    if [[ "$status_field" == "critical" ]]; then
      fail "GET /admin/system-check status=critical - see /admin/system-check in the web UI for details"
    else
      pass "GET /admin/system-check status=$status_field"
    fi
  fi
  echo

  echo "-- 5. Admin catalog coverage (GET \$STAGING_API_URL/admin/catalog-coverage) --"
  http_get "$STAGING_API_URL/admin/catalog-coverage" -H "X-Admin-Token: $ADMIN_TOKEN"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET /admin/catalog-coverage returned 200"
  else
    fail "GET /admin/catalog-coverage returned HTTP $HTTP_STATUS (expected 200)"
  fi
  echo
fi

if [[ -z "$STAGING_WEB_URL" ]]; then
  echo "-- 6. Web pages --"
  echo "Skipping (STAGING_WEB_URL not set)."
  echo
else
  echo "-- 6. Web pages --"
  web_get "/"
  web_get "/dashboard"
  web_get "/collection"
  web_get "/collection/vault"
  web_get "/analytics/digest"
  web_get "/admin/catalog-ops"
  echo
fi

echo "== Summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Staging smoke test passed"
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
