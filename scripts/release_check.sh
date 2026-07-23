#!/usr/bin/env bash
# Pre-release readiness check - see "Release script" in
# docs/release_checklist.md (section A, "Pre-release"). Fails fast on the
# first hard problem (dirty working tree) but otherwise runs every check and
# prints a single pass/fail summary at the end, same style as
# scripts/prod_verify.sh (which this script is a release-flavored sibling
# of - prod_verify.sh is the "is docker-compose.prod.yml itself sound"
# check; this one is the "am I ready to cut *this* release" check: branch,
# commit, VERSION, working tree, secrets, and compose config).
#
# Usage: scripts/release_check.sh   (also wired up as `make release-check`)
#
# Env vars:
#   ALLOW_DIRTY   default false - set ALLOW_DIRTY=true to allow an unclean
#                 git working tree (uncommitted changes). Off by default: a
#                 release should be cut from a clean, committed tree.
#   RUN_TESTS     default false - set RUN_TESTS=true to also run the backend
#                 and worker test suites inside the (already running) dev
#                 compose stack (`docker compose exec api pytest` /
#                 `docker compose run --rm worker pytest`). Requires
#                 `docker compose up -d` to already be running for the api
#                 exec to succeed - `make dev-up` first if it isn't.

set -uo pipefail

# Resolve the repo root from this script's own location rather than
# `git rev-parse --show-toplevel` (which depends on the caller's current
# working directory and fails outright if invoked from outside the repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$repo_root"

FAILURES=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILURES=$((FAILURES + 1)); }

echo "== Release info =="
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT="$(git rev-parse --short HEAD)"
VERSION="$(cat VERSION 2>/dev/null || echo 'unknown (no VERSION file)')"
echo "Branch:  $BRANCH"
echo "Commit:  $COMMIT"
echo "Version: $VERSION"
echo

ALLOW_DIRTY="${ALLOW_DIRTY:-false}"
echo "== 1. git status clean (ALLOW_DIRTY=$ALLOW_DIRTY) =="
if [[ -z "$(git status --porcelain)" ]]; then
  pass "git working tree is clean"
elif [[ "$ALLOW_DIRTY" == "true" ]]; then
  echo "SKIP: working tree has uncommitted changes, but ALLOW_DIRTY=true"
else
  fail "git working tree has uncommitted changes (set ALLOW_DIRTY=true to override)"
  git status --porcelain | sed 's/^/  /'
fi
echo

echo "== 2. Secret check =="
if bash scripts/check_secrets.sh; then
  pass "scripts/check_secrets.sh"
else
  fail "scripts/check_secrets.sh"
fi
echo

# Prefers the real .env.production if it exists on this machine (a genuine
# pre-deploy check of the actual resolved config). Every api/worker/beat/web
# service in docker-compose.prod.yml declares `env_file: .env.production`,
# which Compose resolves at `config` time regardless of any --env-file flag
# - the file must merely exist, even empty - so on a fresh checkout without
# one yet, create an empty placeholder for the duration of this check only
# (removed again below, via the EXIT trap) rather than failing outright.
# Required (${VAR:?...}) substitutions in the compose file itself (
# POSTGRES_DB, NEXT_PUBLIC_API_URL, ...) come from the shell environment, not
# from .env.production, so those get dummy placeholder values in that case
# too - never real secrets.
CREATED_ENV_PRODUCTION=false
if [[ -f .env.production ]]; then
  echo "== 3. docker compose config (using .env.production) =="
else
  touch .env.production
  CREATED_ENV_PRODUCTION=true
  export POSTGRES_DB="${POSTGRES_DB:-release-check}"
  export POSTGRES_USER="${POSTGRES_USER:-release-check}"
  export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-release-check-placeholder}"
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
  echo "== 3. docker compose config (no .env.production found - using an empty placeholder + dummy values) =="
fi
trap '[[ "$CREATED_ENV_PRODUCTION" == "true" ]] && rm -f .env.production' EXIT

if docker compose -f docker-compose.prod.yml --env-file .env.production config >/dev/null; then
  pass "docker compose -f docker-compose.prod.yml config"
else
  fail "docker compose -f docker-compose.prod.yml config"
fi

if docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml \
  --env-file .env.production config >/dev/null; then
  pass "docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml config"
else
  fail "docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml config"
fi
echo

RUN_TESTS="${RUN_TESTS:-false}"
echo "== 4. Test suites (RUN_TESTS=$RUN_TESTS) =="
if [[ "$RUN_TESTS" == "true" ]]; then
  if docker compose exec api pytest; then
    pass "api test suite (docker compose exec api pytest)"
  else
    fail "api test suite (docker compose exec api pytest) - is the dev stack up (make dev-up)?"
  fi

  if docker compose run --rm worker pytest; then
    pass "worker test suite (docker compose run --rm worker pytest)"
  else
    fail "worker test suite (docker compose run --rm worker pytest)"
  fi
else
  echo "skipped (set RUN_TESTS=true to run)"
fi
echo

echo "== Release readiness summary =="
echo "Branch:  $BRANCH"
echo "Commit:  $COMMIT"
echo "Version: $VERSION"
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Result:  READY - all checks passed."
else
  echo "Result:  NOT READY - $FAILURES check(s) failed."
fi
echo "See docs/release_checklist.md for the full pre-release/build/deploy/rollback checklist."

if [[ "$FAILURES" -ne 0 ]]; then
  exit 1
fi
