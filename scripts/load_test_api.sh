#!/usr/bin/env bash
# Lightweight API load test - fires a small burst of concurrent requests at
# the important read endpoints and reports success/failure counts plus a
# rough average duration per endpoint. This is NOT a real load testing tool
# (no ramping, no percentiles, no connection reuse tuning) - it exists to
# catch "this endpoint falls over or times out under a handful of
# concurrent requests" before Phase 7 is considered done. See
# docs/performance_testing.md.
#
# Uses only curl + bash - no k6/hey/ab/wrk dependency.
#
# Usage: scripts/load_test_api.sh
#
# Env vars:
#   BASE_API_URL   default http://127.0.0.1:8000
#   ADMIN_TOKEN    optional - if set, also load-tests the /admin/* endpoints
#                  below, sent as the X-Admin-Token header.
#   REQUESTS       total requests per endpoint, default 20
#   CONCURRENCY    requests in flight at once per endpoint, default 5
#
# A request "succeeds" if the server returned any response other than a
# connection failure or a 5xx - this is a load/stability check, not an auth
# check, so an expected 401/404 on a login-gated endpoint (e.g.
# /collection/valuation with no bearer token) still counts as a success.
# Exits non-zero if any endpoint had a connection failure or a 5xx.

set -uo pipefail

BASE_API_URL="${BASE_API_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
REQUESTS="${REQUESTS:-20}"
CONCURRENCY="${CONCURRENCY:-5}"

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

ENDPOINTS=(
  "/health"
  "/dashboard/overview"
  "/collection/valuation"
  "/market/opportunities?limit=20"
  "/market/signals?limit=20"
  "/wishlist/summary"
  "/grading/summary"
  "/search/suggestions?q=OP"
)

if [[ -n "$ADMIN_TOKEN" ]]; then
  ENDPOINTS+=(
    "/admin/performance/summary"
    "/admin/cache/status"
    "/admin/job-locks"
    "/admin/data-retention/policy"
  )
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "== API load test =="
echo "BASE_API_URL=$BASE_API_URL REQUESTS=$REQUESTS CONCURRENCY=$CONCURRENCY ADMIN_TOKEN=$([[ -n "$ADMIN_TOKEN" ]] && echo set || echo unset)"
echo

OVERALL_FAILURES=0

for endpoint in "${ENDPOINTS[@]}"; do
  results_file="$WORKDIR/$(echo "$endpoint" | tr -c 'a-zA-Z0-9' '_').txt"
  : > "$results_file"

  curl_headers=(-H "Accept: application/json")
  if [[ -n "$ADMIN_TOKEN" && "$endpoint" == /admin/* ]]; then
    curl_headers+=(-H "X-Admin-Token: $ADMIN_TOKEN")
  fi

  in_flight=0
  for ((i = 0; i < REQUESTS; i++)); do
    (
      out=$(curl -sS -o /dev/null --connect-timeout 5 --max-time 15 \
        -w "%{http_code} %{time_total}\n" "${curl_headers[@]}" \
        "$BASE_API_URL$endpoint" 2>/dev/null) || out="000 0"
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
  failures=$(awk '{code=$1; if (code == "000" || code >= 500) c++} END{print c+0}' "$results_file")
  success=$((total - failures))
  avg_duration=$(awk '{sum+=$2; n++} END{if (n>0) printf "%.3f", sum/n; else print "n/a"}' "$results_file")

  printf 'endpoint=%s total=%s success=%s failures=%s avg_duration_s=%s\n' \
    "$endpoint" "$total" "$success" "$failures" "$avg_duration"

  if [[ "$failures" -gt 0 ]]; then
    OVERALL_FAILURES=$((OVERALL_FAILURES + 1))
  fi
done

echo
if [[ "$OVERALL_FAILURES" -gt 0 ]]; then
  echo "FAIL: $OVERALL_FAILURES endpoint(s) had connection failures or 5xx responses." >&2
  exit 1
fi

echo "API load test passed"
