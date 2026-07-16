#!/usr/bin/env bash
# Pre-deploy sanity check for the production stack (docker-compose.prod.yml).
# Safe to run in CI or before .env.production exists on this machine - it
# never touches real secrets or starts any containers. Confirms:
#   1. git isn't tracking a real env file (scripts/check_secrets.sh)
#   2. docker-compose.prod.yml is well-formed and its required vars resolve
#   3. the production images actually build
#   4. (optional) the backend/worker test suites pass
# ...then prints the next real deploy commands.
#
# Usage: scripts/prod_verify.sh   (also wired up as `make prod-verify`)
#
# Env vars:
#   RUN_TESTS   default false - set RUN_TESTS=true to also run the backend
#               and worker test suites (services/api, services/worker). Both
#               use an in-memory SQLite DB in tests (see their conftest.py),
#               so no real Postgres/Redis is required either way - off by
#               default here only because it's slower, not because it needs
#               more infrastructure.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

FAILURES=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }

echo "== 1. Secret check =="
if bash scripts/check_secrets.sh; then
  pass "scripts/check_secrets.sh"
else
  fail "scripts/check_secrets.sh"
fi
echo

# Dummy placeholder values only - never real secrets - just enough to
# satisfy docker-compose.prod.yml's required (${VAR:?...}) substitutions.
# Deliberately does NOT pass --env-file .env.production: both commands below
# must work even before that file exists on this machine (e.g. in CI, or
# before the very first deploy).
VERIFY_ENV=(
  POSTGRES_DB=verify
  POSTGRES_USER=verify
  POSTGRES_PASSWORD=verify-placeholder
  NEXT_PUBLIC_API_URL=http://localhost:8000
)

echo "== 2. docker compose config =="
if env "${VERIFY_ENV[@]}" docker compose -f docker-compose.prod.yml config >/dev/null; then
  pass "docker compose -f docker-compose.prod.yml config"
else
  fail "docker compose -f docker-compose.prod.yml config"
fi
echo

echo "== 3. docker compose build =="
if env "${VERIFY_ENV[@]}" docker compose -f docker-compose.prod.yml build; then
  pass "docker compose -f docker-compose.prod.yml build"
else
  fail "docker compose -f docker-compose.prod.yml build"
fi
echo

RUN_TESTS="${RUN_TESTS:-false}"
echo "== 4. Test suites (RUN_TESTS=$RUN_TESTS) =="
if [[ "$RUN_TESTS" == "true" ]]; then
  if (cd services/api && python3 -m pytest -q); then
    pass "services/api test suite"
  else
    fail "services/api test suite"
  fi

  if (cd services/worker && python3 -m pytest -q); then
    pass "services/worker test suite"
  else
    fail "services/worker test suite"
  fi
else
  echo "skipped (set RUN_TESTS=true to run)"
fi
echo

echo "== Summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Production verification passed."
else
  echo "$FAILURES check(s) failed."
fi
echo

echo "== Next deploy commands =="
cat <<'EOF'
  cp .env.production.example .env.production   # then fill in real values
  make prod-build
  make prod-up
  make prod-migrate
  ADMIN_TOKEN=<token> make prod-smoke
  make prod-logs
EOF

if [[ "$FAILURES" -ne 0 ]]; then
  exit 1
fi
