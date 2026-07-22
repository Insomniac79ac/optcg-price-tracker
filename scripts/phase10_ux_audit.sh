#!/usr/bin/env bash
# Phase 10 UX audit - verifies the mobile/tablet responsiveness/UX polish
# pass and the later styling-consistency pass (every apps/web/src/app route
# migrated to the TCG Vault design system - see
# docs/frontend_styling_audit.md) didn't break anything that already worked:
# same standard checks as scripts/phase8_audit.sh/phase9_audit.sh, HTTP 200
# checks across every route/endpoint this phase touched, and a handful of
# static source greps for the styling-pass anti-patterns (bare "Market"
# labels, literal undefined/null/NaN rendered as text, bright gradients,
# admin token persisted somewhere it shouldn't be). Fails fast: stops at the
# first failing step.
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
# Every apps/web/src/app/**/page.tsx route (see docs/frontend_styling_audit.md
# for the full inventory this was cross-checked against) except /cards/[id]
# (dynamic - needs a real card id, exercised separately/manually) and /
# (a redirect, not an HTTP-200 page).
WEB_ROUTES=(
  /dashboard
  /search
  /collection
  /collection/vault
  /wishlist
  /grading
  /activity
  /analytics/digest
  /analytics/collection
  /analytics/wishlist
  /analytics/buy-decisions
  /analytics/sell-decisions
  /analytics/grading
  /analytics/portfolio-risk
  /market/movers
  /market/report
  /market/opportunities
  /market/signals
  /market/signal-events
  /admin/catalog-ops
  /admin/import-validation
  /admin/card-duplicates
  /admin/source-mapping-quality
  /admin/catalog-coverage
  /admin/price-source-health
  /admin/system-check
  /admin/cards
  /admin/card-audit
  /admin/snkrdunk-candidates
  /admin/actions
  /admin/refresh-runs
  /admin/market-workflow-runs
  /admin/backup
  /admin/performance
  /admin/logs
  /admin/release-status
  /admin/alerts
  /admin/job-locks
  /admin/file-jobs
  /admin/data-retention
  /admin/cache
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

echo "== 5. Static styling/safety checks (grep, no live stack needed) =="
# Cheap source greps for the styling-consistency-pass anti-patterns called
# out in docs/interface_design_system.md ("Do-not list", "Price/source
# display audit rules", "Admin safety UI rules"). Deliberately narrow
# patterns so this doesn't flag legitimate code comments/docs - see notes
# per check.
WEB_SRC="apps/web/src"

# Literal "undefined"/"null"/"NaN" rendered as JSX text is almost always a
# missing-fallback bug (should be MissingValue/"not available"/"—" instead).
# Matches a JSX text node exactly, e.g. `>undefined<` from `{value}`
# rendering an actual undefined - not TS type unions (`: T | null`) or JS
# comparisons (`=== null`), which never look like this.
if grep -rnE '>(undefined|null|NaN)<' "$WEB_SRC" --include="*.tsx" | grep -v '\.test\.tsx'; then
  fail "found literal undefined/null/NaN rendered as JSX text above - use MissingValue/formatNullable/\"not available\" instead"
else
  echo "PASS: no literal undefined/null/NaN rendered as JSX text"
fi

# A bare "Market" price-basis label (no source/mode qualifier) is exactly
# the ambiguity PriceBasisLabel exists to prevent. SidebarNav's top-level
# "Market" nav section label is a legitimate exception (it's a nav category,
# not a price basis), not a price display.
if grep -rn '>Market<' "$WEB_SRC" --include="*.tsx" | grep -v 'SidebarNav.tsx'; then
  fail "found a standalone \"Market\" label above - price basis labels must name the source/mode (see PriceBasisLabel)"
else
  echo "PASS: no standalone \"Market\" price-basis labels"
fi

# Bright gradients are on the design system's do-not list (vault aesthetic,
# not a SaaS landing page).
if grep -rn 'bg-gradient-to' "$WEB_SRC" --include="*.tsx"; then
  fail "found bg-gradient-* usage above - not part of the TCG Vault design system (see docs/interface_design_system.md Do-not list)"
else
  echo "PASS: no bright gradient classes"
fi

# Admin token persistence: the admin token must only ever be read/written
# via getAdminToken/setAdminToken/clearAdminToken in lib/api.ts. Any other
# file touching localStorage with an admin/token-ish key, or building a
# saved-view/recent-workflow payload that includes a token field, would leak
# it into persisted state the token should never reach.
if grep -rniE "localStorage\.(get|set|remove)Item\(['\"].*(admin|token)" "$WEB_SRC" --include="*.ts" --include="*.tsx" | grep -v 'lib/api.ts' | grep -v '\.test\.'; then
  fail "found localStorage admin/token access above outside lib/api.ts - the admin token must only be persisted via getAdminToken/setAdminToken/clearAdminToken"
else
  echo "PASS: admin token localStorage access confined to lib/api.ts"
fi
if grep -rniE "(payload_json|currentFilters|filters)[^;]*:\s*\{[^}]*\btoken\b" "$WEB_SRC" --include="*.tsx" --include="*.ts" | grep -v '\.test\.'; then
  fail "found a token field inside a saved-view/recent-workflow payload above - the admin token must never be saved into saved views or recent workflows"
else
  echo "PASS: no admin token found in saved-view/recent-workflow payloads"
fi
echo

echo "== 6. Frontend viewport/overflow smoke tests =="
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
