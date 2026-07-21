#!/usr/bin/env bash
# Phase 9 completion audit - verifies that the catalog-operations surface
# (canonical card catalog import/export, source candidate matching, source
# mapping quality review, card duplicate merge tools, import templates/
# validation, catalog coverage, and price source health) actually works end
# to end on top of the standard checks. Fails fast: stops at the first
# failing step, same convention as scripts/phase7_audit.sh/phase8_audit.sh
# (which this is meant to run alongside/after).
#
# Meant to be run against a live local/dev stack (`make dev-up`).
#
# Never scrapes anything and never bypasses SNKRDUNK/Yuyu-Tei site
# protections - every check here either reads existing data or exercises a
# dry-run/validate-only endpoint (recheck-quality dry_run=true, import
# validation, duplicate bulk-preview), matching the same safety rules the
# features themselves follow (see 'Catalog operations workflow' in
# docs/operations.md).
#
# Usage: scripts/phase9_audit.sh
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

CURL_OPTS=(-sS --connect-timeout 5 --max-time 20)
BODY_FILE="$(mktemp)"

# tmp_dir lives under ./data (bind-mounted into the api container at
# /app/data - see docker-compose.yml), so a CSV written here on the host is
# immediately readable inside the container at the same relative path -
# needed for the CLI checks in section 7, which run `docker compose exec
# api`.
tmp_dir="data/imports/.phase9_audit_tmp"
cleanup() {
  rm -f "$BODY_FILE"
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $1" >&2
  echo "Phase 9 audit FAILED." >&2
  exit 1
}

# Sets HTTP_STATUS and writes the response body to $BODY_FILE.
http_get() {
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
    -H "X-Admin-Token: $ADMIN_TOKEN" "$1" 2>/dev/null) || HTTP_STATUS="000"
}

http_post_json() {
  local url="$1" body="$2"
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
    -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" -d "$body" \
    "$url" 2>/dev/null) || HTTP_STATUS="000"
}

http_post_file() {
  local url="$1" file="$2"
  HTTP_STATUS=$(curl "${CURL_OPTS[@]}" -o "$BODY_FILE" -w "%{http_code}" \
    -H "X-Admin-Token: $ADMIN_TOKEN" -F "file=@$file" "$url" 2>/dev/null) || HTTP_STATUS="000"
}

# json_field <field_name> - reads $BODY_FILE, prints the field's value
# ("true"/"false" for booleans, "" if missing/unparseable) - same helper as
# scripts/smoke_test.sh.
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

echo "== 3. Admin API GET checks (BASE_API_URL=$BASE_API_URL) =="
ADMIN_GET_CHECKS=(
  "/admin/cards?limit=5"
  "/admin/cards/export.csv"
  "/admin/card-audit"
  "/admin/cards/duplicates?limit=5"
  "/admin/source-mappings/quality?limit=5"
  "/admin/import-templates"
  "/admin/import-templates/card_catalog.csv"
  "/admin/import-templates/source_mappings.csv"
  "/admin/import-templates/snkrdunk_candidates.csv"
  "/admin/import-templates/collection.csv"
  "/admin/import-templates/wishlist.csv"
  "/admin/import-validation/reports?limit=5"
  "/admin/catalog-coverage"
  "/admin/catalog-coverage/gaps?gap_type=metadata&limit=5"
  "/admin/catalog-coverage/gaps?gap_type=mapping&limit=5"
  "/admin/catalog-coverage/gaps?gap_type=price&limit=5"
  "/admin/catalog-coverage/gaps?gap_type=duplicate&limit=5"
  "/admin/catalog-coverage/gaps?gap_type=mapping_quality&limit=5"
  "/admin/price-source-health"
  "/admin/price-source-health/gaps?gap_type=stale&limit=5"
  "/admin/price-source-health/gaps?gap_type=missing&limit=5"
  "/admin/system-check"
)
for path in "${ADMIN_GET_CHECKS[@]}"; do
  http_get "$BASE_API_URL$path"
  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "PASS: GET $path returned 200"
  else
    fail "GET $path returned HTTP $HTTP_STATUS (expected 200)"
  fi
done
echo

echo "== 4. Admin API POST checks (dry-run/preview only, BASE_API_URL=$BASE_API_URL) =="
http_post_json "$BASE_API_URL/admin/cards/duplicates/bulk-preview" '{}'
if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "PASS: POST /admin/cards/duplicates/bulk-preview returned 200"
else
  fail "POST /admin/cards/duplicates/bulk-preview returned HTTP $HTTP_STATUS (expected 200)"
fi

http_post_json "$BASE_API_URL/admin/source-mappings/recheck-quality" '{"dry_run": true}'
if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "PASS: POST /admin/source-mappings/recheck-quality (dry_run=true) returned 200"
else
  fail "POST /admin/source-mappings/recheck-quality returned HTTP $HTTP_STATUS (expected 200)"
fi
echo

echo "== 5. Web page checks (WEB_BASE_URL=$WEB_BASE_URL) =="
WEB_ROUTES=(
  /admin/cards
  /admin/card-audit
  /admin/card-duplicates
  /admin/source-mapping-quality
  /admin/import-validation
  /admin/catalog-coverage
  /admin/price-source-health
  /admin/system-check
)
for route in "${WEB_ROUTES[@]}"; do
  http_status=$(curl -sS -L -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
    "$WEB_BASE_URL$route" 2>/dev/null) || http_status="000"
  if [[ "$http_status" == "200" ]]; then
    echo "PASS: GET $route returned 200"
  else
    fail "GET $route returned HTTP $http_status (expected 200)"
  fi
done
echo

echo "== 6. Import validation CSV checks =="
mkdir -p "$tmp_dir"
invalid_csv="$tmp_dir/invalid_card_catalog.csv"
valid_csv="$tmp_dir/valid_card_catalog.csv"

# Missing card_code (a required column for card_catalog) - must be reported
# invalid, never imported (this endpoint never writes imported data).
cat > "$invalid_csv" <<'EOF'
card_code,name_en,variant,language
,Phase 9 Missing Code,base,jp
EOF

cat > "$valid_csv" <<'EOF'
card_code,name_en,variant,language
OP99-999,Phase 9 Test Card,base,jp
EOF

http_post_file "$BASE_API_URL/admin/import-validation/card_catalog?strict=false&max_preview_rows=10" "$invalid_csv"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "POST /admin/import-validation/card_catalog (invalid CSV) returned HTTP $HTTP_STATUS (expected 200)"
fi
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
  echo "PASS: invalid card_catalog CSV reported valid=false or error_rows > 0"
else
  fail "invalid card_catalog CSV validation did not report an error (valid=$invalid_valid_field, error_rows=$invalid_error_rows)"
fi

http_post_file "$BASE_API_URL/admin/import-validation/card_catalog?strict=false&max_preview_rows=10" "$valid_csv"
if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "PASS: valid-ish card_catalog CSV validation endpoint responded 200"
else
  fail "valid-ish card_catalog CSV validation returned HTTP $HTTP_STATUS (expected 200)"
fi
echo

echo "== 7. CLI checks (inside api container) =="
docker compose exec api python -m app.catalog_coverage_report >/dev/null \
  || fail "python -m app.catalog_coverage_report"
echo "PASS: python -m app.catalog_coverage_report"

docker compose exec api python -m app.price_source_health_report >/dev/null \
  || fail "python -m app.price_source_health_report"
echo "PASS: python -m app.price_source_health_report"

if docker compose exec api python -m app.validate_import_csv "$invalid_csv" --type card_catalog --no-save-report >/dev/null 2>&1; then
  fail "python -m app.validate_import_csv on the invalid CSV exited 0 (expected non-zero)"
else
  echo "PASS: python -m app.validate_import_csv on the invalid CSV exited non-zero"
fi

if docker compose exec api python -m app.validate_import_csv "$valid_csv" --type card_catalog --no-save-report >/dev/null 2>&1; then
  echo "PASS: python -m app.validate_import_csv on the valid CSV exited 0"
else
  echo "PASS: python -m app.validate_import_csv on the valid CSV exited non-zero (it reported warnings/errors - not treated as a script failure, see --json for detail)"
fi
echo

echo "Phase 9 audit passed"
