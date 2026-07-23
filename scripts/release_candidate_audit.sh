#!/usr/bin/env bash
# Release-candidate audit - the single gate for "is this app ready to tag
# v1.0.0". Phase 11: this only *audits* readiness - it adds no product
# features, changes no valuation formulas, and never touches scraping
# behavior (no SNKRDUNK live scraping, no bypassing Yuyu-Tei/SNKRDUNK site
# protections - every check here either reads existing data or exercises a
# dry-run/validate-only endpoint, same rule scripts/phase9_audit.sh follows).
#
# Unlike scripts/final_audit.sh (pure fail-fast: stops at the first failing
# step) this script distinguishes two kinds of problems:
#   - a hard FAIL stops the script immediately (same fail-fast convention as
#     every other audit script in this repo) - these are "not release
#     candidate material, full stop" problems (tests fail, migrations don't
#     apply, a route that must exist is broken).
#   - a WARN is collected and printed at the end, but does not stop the
#     audit - these are "worth a human look before tagging, but not
#     necessarily a blocker" observations (a route this script guessed at
#     doesn't exist, a static grep found something ambiguous, the git tree
#     is dirty). See docs/release_blockers.md for turning a warning into a
#     tracked release blocker if it turns out to matter.
#
# Meant to be run against a live local/dev stack (`make dev-up`).
#
# Usage: scripts/release_candidate_audit.sh
#
# Env vars:
#   BASE_API_URL       default http://127.0.0.1:8000
#   BASE_WEB_URL        default http://127.0.0.1:3000
#   ADMIN_TOKEN         default local-dev-admin-token (matches
#                       docker-compose.yml's dev default), sent as
#                       X-Admin-Token on the admin curl checks below.
#   SKIP_TESTS          default false - set true to skip the
#                       `docker compose exec api pytest` / `docker compose
#                       run --rm worker pytest` / `npm run build` steps.
#   RUN_PHASE_AUDITS    default true - set false to skip re-running
#                       scripts/final_audit.sh and the phase7-10 audits
#                       (they've usually already been run individually; this
#                       script re-running all of them is the expensive,
#                       thorough path, not the fast one).
#   RUN_PROD_SMOKE      default false - set true to also run
#                       scripts/prod_smoke_test.sh against BASE_WEB_URL.
#   RUN_LOAD_TESTS      default false - set true to also run
#                       scripts/load_test_api.sh / scripts/load_test_web.sh
#                       with a small fixed load (REQUESTS=20 CONCURRENCY=5).
#   STRICT_GIT          default false - set true to fail (rather than warn)
#                       when the git working tree is dirty.

set -uo pipefail

# Resolve the repo root from this script's own location rather than
# `git rev-parse --show-toplevel` (which depends on the caller's current
# working directory - if invoked from outside the repo entirely, that
# lookup fails, leaving repo_root empty; without `set -e` the script would
# then silently `cd ""` - a no-op - and every subsequent `docker compose`
# call would fail with "no configuration file provided: not found" instead
# of a clear error).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$repo_root"

# Next.js supports either a top-level `apps/web/app` directory or a
# `apps/web/src/app` directory (the `src/` layout) - this repo uses the
# `src/` layout, but detect it rather than hardcode it, so route-existence
# checks below don't silently go stale (and warn on every route as "missing")
# if the frontend's directory layout ever changes.
if [[ -d "apps/web/src/app" ]]; then
  WEB_APP_DIR="apps/web/src/app"
elif [[ -d "apps/web/app" ]]; then
  WEB_APP_DIR="apps/web/app"
else
  echo "FAIL: could not find a Next.js app directory at apps/web/src/app or apps/web/app" >&2
  exit 1
fi

BASE_API_URL="${BASE_API_URL:-http://127.0.0.1:8000}"
BASE_WEB_URL="${BASE_WEB_URL:-http://127.0.0.1:3000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-local-dev-admin-token}"
SKIP_TESTS="${SKIP_TESTS:-false}"
RUN_PHASE_AUDITS="${RUN_PHASE_AUDITS:-true}"
RUN_PROD_SMOKE="${RUN_PROD_SMOKE:-false}"
RUN_LOAD_TESTS="${RUN_LOAD_TESTS:-false}"
STRICT_GIT="${STRICT_GIT:-false}"
export BASE_API_URL BASE_WEB_URL ADMIN_TOKEN

CURL_OPTS=(-sS --connect-timeout 5 --max-time 20)
BODY_FILE="$(mktemp)"
TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -f "$BODY_FILE"
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

WARNINGS=()

section() {
  echo
  echo "== $1 =="
}

fail() {
  echo "FAIL: $1" >&2
  echo "Release candidate audit FAILED." >&2
  exit 1
}

warn() {
  echo "WARN: $1"
  WARNINGS+=("$1")
}

pass() {
  echo "PASS: $1"
}

skip() {
  echo "SKIP: $1"
}

# Sets HTTP_STATUS and writes the response body to $BODY_FILE.
http_get() {
  # $1 = url, $2 = "admin" to send X-Admin-Token, omitted/anything else = no auth header
  local url="$1" auth="${2:-}"
  if [[ "$auth" == "admin" ]]; then
    HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
      -H "X-Admin-Token: $ADMIN_TOKEN" "$url" 2>/dev/null) || HTTP_STATUS="000"
  else
    HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" "$url" 2>/dev/null) || HTTP_STATUS="000"
  fi
}

http_post_json() {
  local url="$1" body="$2"
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
    -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" -d "$body" \
    "$url" 2>/dev/null) || HTTP_STATUS="000"
}

http_post_file() {
  local url="$1" file="$2"
  shift 2
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
    -H "X-Admin-Token: $ADMIN_TOKEN" -F "file=@$file" "$@" "$url" 2>/dev/null) || HTTP_STATUS="000"
}

# json_field <field_name> - reads $BODY_FILE, prints the field's value
# ("true"/"false" for booleans, "" if missing/unparseable) - same helper as
# scripts/phase9_audit.sh / scripts/prod_smoke_test.sh.
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

# Required admin GET check - the route must exist and return 200.
admin_get_required() {
  local path="$1"
  http_get "$BASE_API_URL$path" admin
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET $path returned 200"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200)"
  fi
}

# Optional admin GET check - a 404 means the route isn't implemented in this
# codebase yet, which is a SKIP, not a FAIL (see task's "if exists" checks).
# Any other non-200 means the route exists but is broken, which does fail.
admin_get_optional() {
  local path="$1"
  http_get "$BASE_API_URL$path" admin
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET $path returned 200"
  elif [[ "$HTTP_STATUS" == "404" ]]; then
    skip "GET $path returned 404 - route does not exist, skipping"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (route exists but is broken)"
  fi
}

# Session-gated GET check (no admin-token path exists for these by design -
# see scripts/phase8_audit.sh) - a 200 or 401 are both healthy outcomes
# without a real browser session; anything else means the route is broken.
public_or_session_get() {
  local path="$1"
  http_get "$BASE_API_URL$path"
  if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "401" ]]; then
    pass "GET $path returned $HTTP_STATUS"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200 or 401)"
  fi
}

echo "======================================================"
echo " Release candidate audit - target: v1.0.0"
echo " BASE_API_URL=$BASE_API_URL  BASE_WEB_URL=$BASE_WEB_URL"
echo " SKIP_TESTS=$SKIP_TESTS  RUN_PHASE_AUDITS=$RUN_PHASE_AUDITS"
echo " RUN_PROD_SMOKE=$RUN_PROD_SMOKE  RUN_LOAD_TESTS=$RUN_LOAD_TESTS"
echo "======================================================"

# --- 1. Secrets and repo hygiene --------------------------------------------
section "1. Secrets and repo hygiene"
bash scripts/check_secrets.sh || fail "scripts/check_secrets.sh"

if [[ -z "$(git status --porcelain)" ]]; then
  pass "git working tree is clean"
elif [[ "$STRICT_GIT" == "true" ]]; then
  fail "git working tree has uncommitted changes (STRICT_GIT=true)"
else
  warn "git working tree has uncommitted changes (set STRICT_GIT=true to make this a hard failure)"
  git status --porcelain | sed 's/^/  /'
fi

# scripts/check_secrets.sh above already fails on tracked .env/.env.production
# files, tracked *.sql.gz / opcg_backup_*.json backup dumps, tracked
# data/file_jobs/{input,output}/ files, and literal ADMIN_TOKEN/secret values
# committed anywhere. This adds one more sweep this repo doesn't otherwise
# have: an obvious "generated export dump" filename tracked anywhere outside
# the known-safe seed/template CSVs under data/imports and data/watchlists.
offending_exports=$(git ls-files \
  | grep -E '(_synthetic|_generated|_mock_export|_dump)\.(csv|json)$' \
  | grep -v -E '^data/(imports|watchlists)/.*_template\.csv$' \
  || true)
if [[ -n "$offending_exports" ]]; then
  warn "file(s) that look like generated/synthetic data exports are tracked - review before tagging:"
  echo "$offending_exports" | sed 's/^/  - /'
else
  pass "no obviously generated/synthetic data export files tracked"
fi

# --- 2. Backend tests --------------------------------------------------------
section "2. Backend tests (SKIP_TESTS=$SKIP_TESTS)"
if [[ "$SKIP_TESTS" == "true" ]]; then
  skip "docker compose exec api pytest (SKIP_TESTS=true)"
else
  docker compose exec api pytest \
    || fail "docker compose exec api pytest - is the dev stack up (make dev-up)?"
  pass "docker compose exec api pytest"
fi

# --- 3. Worker tests ----------------------------------------------------------
section "3. Worker tests (SKIP_TESTS=$SKIP_TESTS)"
if [[ "$SKIP_TESTS" == "true" ]]; then
  skip "docker compose run --rm worker pytest (SKIP_TESTS=true)"
else
  docker compose run --rm worker pytest \
    || fail "docker compose run --rm worker pytest"
  pass "docker compose run --rm worker pytest"
fi

# --- 4. Frontend build --------------------------------------------------------
section "4. Frontend build (SKIP_TESTS=$SKIP_TESTS)"
if [[ "$SKIP_TESTS" == "true" ]]; then
  skip "web build (SKIP_TESTS=true)"
else
  # apps/web only has a package-lock.json (npm) - no pnpm-lock.yaml or
  # yarn.lock in this repo, so npm is the project's actual package manager,
  # not a guess. Prefer `exec` against an already-running web container,
  # fall back to a throwaway `run --rm` if it isn't up.
  if docker compose exec web true >/dev/null 2>&1; then
    docker compose exec web npm run build || fail "docker compose exec web npm run build"
  else
    docker compose run --rm web npm run build || fail "docker compose run --rm web npm run build"
  fi
  pass "web build"
fi

# --- 5. Alembic migrations ----------------------------------------------------
section "5. Alembic migrations"
docker compose exec api alembic current || fail "docker compose exec api alembic current"
docker compose exec api alembic heads || fail "docker compose exec api alembic heads"
docker compose exec api alembic upgrade head || fail "docker compose exec api alembic upgrade head - migrations did not apply cleanly"
pass "alembic current / heads / upgrade head"

# --- 6. API health -------------------------------------------------------------
section "6. API health (public/session-gated)"
http_get "$BASE_API_URL/health"
if [[ "$HTTP_STATUS" == "200" ]]; then
  status_field="$(json_field status)"
  if [[ "$status_field" == "ok" || -z "$status_field" ]]; then
    pass "GET /health returned 200"
  else
    fail "GET /health status='$status_field' (expected 'ok')"
  fi
else
  fail "GET /health returned HTTP $HTTP_STATUS (expected 200)"
fi

http_get "$BASE_API_URL/version"
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /version returned 200 (version=$(json_field version))"
elif [[ "$HTTP_STATUS" == "404" ]]; then
  skip "GET /version returned 404 - route does not exist, skipping"
else
  fail "GET /version returned HTTP $HTTP_STATUS (route exists but is broken)"
fi

# /analytics/digest, /collection/summary, and /saved-views require a
# signed-in session with no admin-token path (by design - see
# scripts/phase8_audit.sh) - 200 or 401 are both healthy without a browser
# session in hand.
public_or_session_get "/analytics/digest"
public_or_session_get "/collection/summary"
public_or_session_get "/saved-views?limit=5"

# /market/opportunities has no auth requirement at all.
http_get "$BASE_API_URL/market/opportunities?limit=5"
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /market/opportunities?limit=5 returned 200"
else
  fail "GET /market/opportunities?limit=5 returned HTTP $HTTP_STATUS (expected 200)"
fi

section "6b. Admin API checks (X-Admin-Token)"
admin_get_required "/admin/system-check"
system_check_status="$(json_field status)"
[[ "$system_check_status" == "critical" ]] && warn "/admin/system-check status=critical - see the /admin/system-check page for detail"

admin_get_optional "/admin/env-check"
env_check_status="$(json_field status)"
[[ "$env_check_status" == "critical" ]] && warn "/admin/env-check status=critical - see docs/deployment.md section 1a"

admin_get_optional "/admin/release-status"

# No dedicated backend "summary" route backs /admin/catalog-ops - it's a
# frontend-only page that aggregates catalog-coverage, price-source-health,
# mapping-quality, card-duplicates, and import-validation-reports (see
# apps/web/src/app/admin/catalog-ops/page.tsx). Nothing to GET here.
skip "GET /admin/catalog-ops summary route - no dedicated API route exists (frontend-only aggregation page), skipping"

admin_get_required "/admin/catalog-coverage"
admin_get_required "/admin/price-source-health"
admin_get_required "/admin/source-mappings/quality?limit=5"
admin_get_required "/admin/card-audit"
admin_get_optional "/admin/performance/summary"
admin_get_optional "/admin/cache/status"
admin_get_optional "/admin/job-locks"

# The literal /admin/file-jobs?limit=5 path from the task spec doesn't exist
# in this codebase - the file-jobs list route lives at /file-jobs (no
# /admin prefix) and accepts the admin token via app.auth.file_job_access
# (see services/api/app/api/file_jobs.py). Try the literal path first (so a
# future rename is picked up automatically), fall back to the real one.
http_get "$BASE_API_URL/admin/file-jobs?limit=5" admin
if [[ "$HTTP_STATUS" == "200" ]]; then
  pass "GET /admin/file-jobs?limit=5 returned 200"
else
  http_get "$BASE_API_URL/file-jobs?limit=5" admin
  if [[ "$HTTP_STATUS" == "200" ]]; then
    pass "GET /file-jobs?limit=5 returned 200 (actual route - /admin/file-jobs?limit=5 does not exist)"
  else
    fail "GET /file-jobs?limit=5 returned HTTP $HTTP_STATUS (expected 200)"
  fi
fi

admin_get_optional "/admin/logs?limit=5"

# --- 7. Web route smoke -------------------------------------------------------
section "7. Web route smoke (BASE_WEB_URL=$BASE_WEB_URL)"

# Route existence is determined by WEB_APP_DIR (detected above - either
# apps/web/src/app or apps/web/app) having a page.tsx/page.ts under that path.
web_route_exists() {
  local dir="$WEB_APP_DIR$1"
  [[ -f "$dir/page.tsx" || -f "$dir/page.ts" ]]
}

check_web_route() {
  local route="$1"
  if ! web_route_exists "$route"; then
    warn "web route $route does not exist in $WEB_APP_DIR - skipping"
    return
  fi
  local http_status
  http_status=$(curl -sS -L -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    "$BASE_WEB_URL$route" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    pass "GET $route returned 200"
  else
    fail "GET $route returned HTTP $http_status (expected 200)"
  fi
}

COLLECTOR_ROUTES=(/dashboard /search /collection /collection/vault /wishlist /grading /activity)
MARKET_ANALYTICS_ROUTES=(
  /market/opportunities /market/signals /market/signal-events
  /analytics/digest /analytics/collection /analytics/wishlist
  /analytics/buy-decisions /analytics/sell-decisions /analytics/grading
  /analytics/portfolio-risk
)
# /admin/source-mappings and /admin/env-check are intentionally kept in this
# list even though neither has a frontend page in this codebase today (the
# API routes they'd correspond to exist and are checked separately in
# section 6b - see docs/release_candidate_report.md's "Known warnings"). They
# always print as a WARN, not a FAIL, since a missing frontend page for these
# is expected, not a regression - kept here as a reminder in case a page is
# ever added and should be wired into this list's HTTP check.
ADMIN_ROUTES=(
  /admin/catalog-ops /admin/cards /admin/import-validation /admin/card-audit
  /admin/card-duplicates /admin/snkrdunk-candidates /admin/source-mappings
  /admin/source-mapping-quality /admin/catalog-coverage /admin/price-source-health
  /admin/system-check /admin/actions /admin/backup /admin/cache
  /admin/data-retention /admin/env-check /admin/file-jobs /admin/job-locks
  /admin/logs /admin/performance /admin/refresh-runs /admin/release-status
)

for route in "${COLLECTOR_ROUTES[@]}" "${MARKET_ANALYTICS_ROUTES[@]}" "${ADMIN_ROUTES[@]}"; do
  check_web_route "$route"
done

# --- 8. Phase audits -----------------------------------------------------------
section "8. Phase audits (RUN_PHASE_AUDITS=$RUN_PHASE_AUDITS)"
if [[ "$RUN_PHASE_AUDITS" != "true" ]]; then
  skip "phase audits (RUN_PHASE_AUDITS=false)"
else
  # final_audit.sh is fail-fast on its own, and SKIP_TESTS is forwarded so
  # the (already-run, above) test suites aren't run a second time.
  SKIP_TESTS="$SKIP_TESTS" WEB_BASE_URL="$BASE_WEB_URL" bash scripts/final_audit.sh \
    || fail "scripts/final_audit.sh"
  pass "scripts/final_audit.sh"

  if [[ -f scripts/phase7_audit.sh ]]; then
    SKIP_TESTS=true WEB_BASE_URL="$BASE_WEB_URL" ADMIN_TOKEN="$ADMIN_TOKEN" BASE_API_URL="$BASE_API_URL" \
      bash scripts/phase7_audit.sh || fail "scripts/phase7_audit.sh"
    pass "scripts/phase7_audit.sh"
  else
    skip "scripts/phase7_audit.sh does not exist"
  fi

  if [[ -f scripts/phase8_audit.sh ]]; then
    SKIP_TESTS=true WEB_BASE_URL="$BASE_WEB_URL" ADMIN_TOKEN="$ADMIN_TOKEN" BASE_API_URL="$BASE_API_URL" \
      bash scripts/phase8_audit.sh || fail "scripts/phase8_audit.sh"
    pass "scripts/phase8_audit.sh"
  else
    skip "scripts/phase8_audit.sh does not exist"
  fi

  if [[ -f scripts/phase9_audit.sh ]]; then
    SKIP_TESTS=true WEB_BASE_URL="$BASE_WEB_URL" ADMIN_TOKEN="$ADMIN_TOKEN" BASE_API_URL="$BASE_API_URL" \
      bash scripts/phase9_audit.sh || fail "scripts/phase9_audit.sh"
    pass "scripts/phase9_audit.sh"
  else
    skip "scripts/phase9_audit.sh does not exist"
  fi

  if [[ -f scripts/phase10_ux_audit.sh ]]; then
    SKIP_TESTS=true BASE_WEB_URL="$BASE_WEB_URL" ADMIN_TOKEN="$ADMIN_TOKEN" BASE_API_URL="$BASE_API_URL" \
      bash scripts/phase10_ux_audit.sh || fail "scripts/phase10_ux_audit.sh"
    pass "scripts/phase10_ux_audit.sh"
  else
    skip "scripts/phase10_ux_audit.sh does not exist"
  fi
fi

# --- 9. Backup/restore dry checks ----------------------------------------------
section "9. Backup/restore dry checks"

for f in scripts/db_backup.sh scripts/db_restore.sh scripts/db_backup_prune.sh; do
  if [[ -x "$f" ]]; then
    pass "$f exists and is executable"
  else
    fail "$f is missing or not executable"
  fi
done

backup_file="$TMP_DIR/rc_audit_backup.json"
http_get "$BASE_API_URL/admin/backup/export" admin
if [[ "$HTTP_STATUS" == "200" ]]; then
  cp "$BODY_FILE" "$backup_file"
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$backup_file" 2>/dev/null; then
    pass "GET /admin/backup/export returned 200 with valid JSON"
  else
    fail "GET /admin/backup/export returned 200 but the body is not valid JSON"
  fi

  http_post_file "$BASE_API_URL/admin/backup/validate" "$backup_file"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    valid_field="$(json_field valid)"
    if [[ "$valid_field" == "true" ]]; then
      pass "POST /admin/backup/validate on the fresh export reports valid=true"
    else
      warn "POST /admin/backup/validate on the fresh export reports valid=$valid_field - review before tagging"
    fi
  else
    fail "POST /admin/backup/validate returned HTTP $HTTP_STATUS (expected 200)"
  fi

  # dry_run=true is the endpoint's own default - never overridden here, this
  # never writes to the database (see app.services.backup.restore_backup).
  http_post_file "$BASE_API_URL/admin/backup/restore?dry_run=true&mode=merge" "$backup_file"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    dry_run_field="$(json_field dry_run)"
    if [[ "$dry_run_field" == "true" ]]; then
      pass "POST /admin/backup/restore (dry_run=true) returned 200 with dry_run=true"
    else
      fail "POST /admin/backup/restore (dry_run=true) responded with dry_run=$dry_run_field - refusing to trust this endpoint's dry-run guarantee"
    fi
  else
    fail "POST /admin/backup/restore (dry_run=true) returned HTTP $HTTP_STATUS (expected 200)"
  fi
else
  warn "GET /admin/backup/export returned HTTP $HTTP_STATUS - skipping validate/restore dry-run checks"
fi

# --- 10. Import/export dry checks -----------------------------------------------
section "10. Import/export dry checks"

http_get "$BASE_API_URL/admin/cards/export.csv" admin
[[ "$HTTP_STATUS" == "200" ]] && pass "GET /admin/cards/export.csv returned 200" \
  || fail "GET /admin/cards/export.csv returned HTTP $HTTP_STATUS (expected 200)"

# /collection/export.csv and /wishlist/export.csv require a signed-in
# session with no admin-token path - 401 without one is healthy.
public_or_session_get "/collection/export.csv"
public_or_session_get "/wishlist/export.csv"

http_get "$BASE_API_URL/admin/import-templates/card_catalog.csv" admin
[[ "$HTTP_STATUS" == "200" ]] && pass "GET /admin/import-templates/card_catalog.csv returned 200" \
  || fail "GET /admin/import-templates/card_catalog.csv returned HTTP $HTTP_STATUS (expected 200)"

# Invalid card_catalog CSV (missing the required card_code column) must be
# reported invalid - this endpoint only validates, it never imports.
invalid_csv="$TMP_DIR/invalid_card_catalog.csv"
cat > "$invalid_csv" <<'EOF'
card_code,name_en,variant,language
,Release Candidate Audit Missing Code,base,jp
EOF
http_post_file "$BASE_API_URL/admin/import-validation/card_catalog?strict=false&max_preview_rows=10" "$invalid_csv"
if [[ "$HTTP_STATUS" == "200" ]]; then
  invalid_valid_field="$(json_field valid)"
  invalid_error_rows="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(data.get('summary', {}).get('error_rows', 0))
except Exception:
    print(0)
" "$BODY_FILE")"
  if [[ "$invalid_valid_field" == "false" || "${invalid_error_rows:-0}" -gt 0 ]]; then
    pass "invalid card_catalog CSV reported valid=false or error_rows > 0"
  else
    fail "invalid card_catalog CSV validation did not report an error (valid=$invalid_valid_field, error_rows=$invalid_error_rows)"
  fi
else
  fail "POST /admin/import-validation/card_catalog (invalid CSV) returned HTTP $HTTP_STATUS (expected 200)"
fi

# --- 11. Admin safety checks -----------------------------------------------------
section "11. Admin safety checks (static grep)"
WEB_SRC="apps/web/src"

# The admin token must only ever be persisted via getAdminToken/setAdminToken/
# clearAdminToken in lib/api.ts (see scripts/phase10_ux_audit.sh, same check).
if grep -rniE "localStorage\.(get|set|remove)Item\(['\"].*(admin|token)" "$WEB_SRC" --include="*.ts" --include="*.tsx" | grep -v 'lib/api.ts' | grep -v '\.test\.'; then
  fail "found localStorage admin/token access above outside lib/api.ts"
else
  pass "admin token localStorage access confined to lib/api.ts"
fi

# The admin token must never be saved into a saved-view/recent-workflow
# payload (same check as scripts/phase10_ux_audit.sh).
if grep -rniE "(payload_json|currentFilters|filters)[^;]*:\s*\{[^}]*\btoken\b" "$WEB_SRC" --include="*.tsx" --include="*.ts" | grep -v '\.test\.'; then
  fail "found a token field inside a saved-view/recent-workflow payload above"
else
  pass "no admin token found in saved-view/recent-workflow payloads"
fi

# Confirmation-text persistence is a softer, harder-to-grep-precisely check
# than the two above - warn rather than fail if this pattern is found, since
# a false positive here (e.g. a test fixture) shouldn't block a release.
if grep -rniE "localStorage\.setItem\(['\"].*confirm" "$WEB_SRC" --include="*.ts" --include="*.tsx" | grep -v '\.test\.'; then
  warn "found a localStorage key that looks like it might persist confirmation text - review manually"
else
  pass "no localStorage key that looks like persisted confirmation text"
fi

# Best-effort check that ConfirmActionModal (the shared confirmation gate -
# see 'Admin safety rules' in docs/interface_design_system.md) is actually
# used somewhere in the admin surface, not just defined and never wired up.
# This can't reliably verify every dangerous action is gated (would need a
# real per-action audit), so it only warns, not fails, on an unexpected
# zero count.
confirm_modal_usage=$(grep -rl "ConfirmActionModal" "$WEB_APP_DIR/admin" --include="*.tsx" 2>/dev/null | grep -v '\.test\.' | wc -l | tr -d ' ')
if [[ "${confirm_modal_usage:-0}" -gt 0 ]]; then
  pass "ConfirmActionModal is used in $confirm_modal_usage admin page(s)"
else
  warn "ConfirmActionModal was not found used in any $WEB_APP_DIR/admin page - verify merge/restore/import actions are gated manually (see docs/manual_qa_checklist.md)"
fi

# --- 12. UI text sanity checks -----------------------------------------------------
section "12. UI text sanity checks (static grep, warn-only)"

# These mirror scripts/phase10_ux_audit.sh's stricter (fail-on-match)
# versions of the same checks - phase10 already gates these hard. Here they
# are intentionally soft (warn, not fail) per this audit's own "don't make
# grep too brittle" instruction - this section is a last-mile sanity re-check,
# not a duplicate hard gate.
if grep -rnE '>(undefined|null|NaN)<' "$WEB_SRC" --include="*.tsx" 2>/dev/null | grep -v '\.test\.tsx' | grep -q .; then
  warn "found literal undefined/null/NaN rendered as JSX text - see scripts/phase10_ux_audit.sh section 5 for the authoritative check"
else
  pass "no literal undefined/null/NaN rendered as JSX text"
fi

if grep -rn '>Market<' "$WEB_SRC" --include="*.tsx" 2>/dev/null | grep -v 'SidebarNav.tsx' | grep -q .; then
  warn "found a standalone \"Market\" price-basis label - see scripts/phase10_ux_audit.sh section 5 for the authoritative check"
else
  pass "no standalone \"Market\" price-basis label found"
fi

# --- 13. Production smoke -----------------------------------------------------------
section "13. Production smoke (RUN_PROD_SMOKE=$RUN_PROD_SMOKE)"
if [[ "$RUN_PROD_SMOKE" == "true" ]]; then
  if [[ -f scripts/prod_smoke_test.sh ]]; then
    WEB_BASE_URL="$BASE_WEB_URL" bash scripts/prod_smoke_test.sh || fail "scripts/prod_smoke_test.sh"
    pass "scripts/prod_smoke_test.sh"
  else
    skip "scripts/prod_smoke_test.sh does not exist"
  fi
else
  skip "production smoke test (RUN_PROD_SMOKE=true to enable)"
fi

# --- 14. Load tests ------------------------------------------------------------------
section "14. Load tests (RUN_LOAD_TESTS=$RUN_LOAD_TESTS)"
if [[ "$RUN_LOAD_TESTS" == "true" ]]; then
  if [[ -f scripts/load_test_api.sh ]]; then
    REQUESTS=20 CONCURRENCY=5 BASE_API_URL="$BASE_API_URL" ADMIN_TOKEN="$ADMIN_TOKEN" \
      bash scripts/load_test_api.sh || fail "scripts/load_test_api.sh"
    pass "scripts/load_test_api.sh"
  else
    skip "scripts/load_test_api.sh does not exist"
  fi
  if [[ -f scripts/load_test_web.sh ]]; then
    REQUESTS=20 CONCURRENCY=5 WEB_BASE_URL="$BASE_WEB_URL" bash scripts/load_test_web.sh \
      || fail "scripts/load_test_web.sh"
    pass "scripts/load_test_web.sh"
  else
    skip "scripts/load_test_web.sh does not exist"
  fi
else
  skip "load tests (RUN_LOAD_TESTS=true to enable)"
fi

# --- 15. Release artifact checks ----------------------------------------------------
section "15. Release artifact checks"
REQUIRED_ARTIFACTS=(
  VERSION
  CHANGELOG.md
  docs/operations.md
  docs/deployment.md
  docs/release_checklist.md
  docs/interface_design_system.md
  docs/manual_qa_checklist.md
  docs/route_inventory.md
)
for f in "${REQUIRED_ARTIFACTS[@]}"; do
  if [[ -f "$f" ]]; then
    pass "$f exists"
  else
    fail "$f is missing"
  fi
done

if [[ -f docs/frontend_styling_audit.md ]]; then
  pass "docs/frontend_styling_audit.md exists"
else
  skip "docs/frontend_styling_audit.md does not exist"
fi

# --- Final result --------------------------------------------------------------------
echo
echo "======================================================"
if [[ "${#WARNINGS[@]}" -eq 0 ]]; then
  echo "Release candidate audit passed"
else
  echo "Release candidate audit passed with warnings"
  echo
  echo "Warnings (${#WARNINGS[@]}):"
  for w in "${WARNINGS[@]}"; do
    echo "  - $w"
  done
  echo
  echo "See docs/release_blockers.md to track any of these as a real blocker."
fi
echo "======================================================"
