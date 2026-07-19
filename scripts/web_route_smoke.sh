#!/usr/bin/env bash
# Route-level smoke test for the web app - checks that every important page
# actually returns HTTP 200 (not just that the process is up). Fails fast:
# stops at the first failing route rather than checking the rest, since a
# broken route here means the build/deploy is already bad.
#
# Unlike scripts/prod_smoke_test.sh (which also checks the API directly and
# only runs a handful of pages), this is web-only and covers every route
# listed in "Route smoke checks" - see docs/route_inventory.md for what each
# one is. Meant to run against either a local `npm run dev`/`next start` or
# a deployed web container.
#
# Usage: scripts/web_route_smoke.sh   (also wired into scripts/final_audit.sh)
#
# Env vars:
#   WEB_BASE_URL   default http://127.0.0.1:3000. In docker-compose.prod.yml,
#                  `web` is published on ${WEB_PORT:-3000}, so this matches
#                  an unmodified deploy on the same host.

set -uo pipefail

WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:3000}"

CURL_OPTS=(-sS -L --connect-timeout 5 --max-time 15)

# /dashboard, /collection, /wishlist, and /grading redirect an anonymous
# visitor to /market/movers (see apps/web/middleware.ts) - -L above follows
# that, so this only verifies "the app is up and routing works", not that
# the page itself rendered its signed-in content. Same tradeoff
# scripts/prod_smoke_test.sh already makes for the same pages.
ROUTES=(
  /dashboard
  /search
  /collection
  /analytics/collection
  /wishlist
  /grading
  /activity
  /market/report
  /market/opportunities
  /market/signals
  /market/signal-events
  /admin/actions
  /admin/backup
  /admin/logs
  /admin/performance
  /admin/data-retention
)

echo "== Web route smoke test =="
echo "WEB_BASE_URL=$WEB_BASE_URL"
echo

for route in "${ROUTES[@]}"; do
  http_status=$(curl "${CURL_OPTS[@]}" -o /dev/null -w "%{http_code}" "$WEB_BASE_URL$route" 2>/dev/null) \
    || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    echo "PASS: GET $route returned 200"
  else
    echo "FAIL: GET $route returned HTTP $http_status (expected 200)" >&2
    echo "Web route smoke test FAILED." >&2
    exit 1
  fi
done

echo
echo "Web route smoke test passed"
