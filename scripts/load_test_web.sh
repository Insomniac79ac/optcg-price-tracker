#!/usr/bin/env bash
# Lightweight web load test - fires a small burst of concurrent requests at
# the important pages and prints PASS/FAIL per route. Like
# scripts/load_test_api.sh, this is a stability check (does the route hold
# up under a handful of concurrent requests), not a real load testing tool.
# Uses only curl + bash - no k6/hey/ab/wrk dependency. See
# docs/performance_testing.md.
#
# Unlike scripts/web_route_smoke.sh (one request per route, stops at the
# first failure), this sends REQUESTS requests per route (CONCURRENCY at a
# time) and keeps going through every route, so a single flaky route
# doesn't hide results for the rest.
#
# Usage: scripts/load_test_web.sh
#
# Env vars:
#   WEB_BASE_URL   default http://127.0.0.1:3000
#   REQUESTS       total requests per route, default 10
#   CONCURRENCY    requests in flight at once per route, default 3

set -uo pipefail

WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:3000}"
REQUESTS="${REQUESTS:-10}"
CONCURRENCY="${CONCURRENCY:-3}"

if ! command -v curl >/dev/null 2>&1; then
  echo "FAIL: curl is required but not found on PATH." >&2
  exit 1
fi

if ! [[ "$REQUESTS" =~ ^[0-9]+$ ]] || [[ "$REQUESTS" -lt 1 ]]; then
  echo "FAIL: REQUESTS must be a positive integer (got '$REQUESTS')." >&2
  exit 1
fi
if ! [[ "$CONCURRENCY" =~ ^[0-9]+$ ]] || [[ "$CONCURRENCY" -lt 1 ]]; then
  echo "FAIL: CONCURRENCY must be a positive integer (got '$CONCURRENCY')." >&2
  exit 1
fi

# /dashboard, /collection, /wishlist, and /grading redirect an anonymous
# visitor to /market/movers (see apps/web/middleware.ts) - -L below follows
# that, matching scripts/web_route_smoke.sh's tradeoff of only verifying
# "the app is up and routing works" for those routes, not signed-in content.
ROUTES=(
  /dashboard
  /search
  /collection
  /wishlist
  /grading
  /activity
  /market/report
  /market/opportunities
  /admin/performance
  /admin/cache
  /admin/file-jobs
)

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "== Web load test =="
echo "WEB_BASE_URL=$WEB_BASE_URL REQUESTS=$REQUESTS CONCURRENCY=$CONCURRENCY"
echo

CURL_OPTS=(-sS -L --connect-timeout 5 --max-time 15)
FAILED_ROUTES=0

for route in "${ROUTES[@]}"; do
  results_file="$WORKDIR/$(echo "$route" | tr -c 'a-zA-Z0-9' '_').txt"
  : > "$results_file"

  in_flight=0
  for ((i = 0; i < REQUESTS; i++)); do
    (
      out=$(curl "${CURL_OPTS[@]}" -o /dev/null -w "%{http_code} %{time_total}\n" \
        "$WEB_BASE_URL$route" 2>/dev/null) || out="000 0"
      echo "$out" >> "$results_file"
    ) &
    in_flight=$((in_flight + 1))
    if [[ "$in_flight" -ge "$CONCURRENCY" ]]; then
      wait
      in_flight=0
    fi
  done
  wait

  total=$(wc -l < "$results_file" | tr -d ' ')
  failures=$(awk '{if ($1 != "200") c++} END{print c+0}' "$results_file")
  success=$((total - failures))
  avg_duration=$(awk '{sum+=$2; n++} END{if (n>0) printf "%.3f", sum/n; else print "n/a"}' "$results_file")

  if [[ "$failures" -eq 0 ]]; then
    echo "PASS: $route (total=$total success=$success avg_duration_s=$avg_duration)"
  else
    echo "FAIL: $route (total=$total success=$success failures=$failures avg_duration_s=$avg_duration)" >&2
    FAILED_ROUTES=$((FAILED_ROUTES + 1))
  fi
done

echo
if [[ "$FAILED_ROUTES" -gt 0 ]]; then
  echo "FAIL: $FAILED_ROUTES route(s) had non-200 responses under load." >&2
  exit 1
fi

echo "Web load test passed"
