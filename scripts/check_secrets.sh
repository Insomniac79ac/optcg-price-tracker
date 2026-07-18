#!/usr/bin/env bash
# Repo-wide secret scanner - fails if git is tracking anything that looks
# like a real secret: env-style files, Postgres/JSON backup dumps, or
# literal (non-placeholder) values for known secret-shaped variables
# (ADMIN_TOKEN, TELEGRAM_BOT_TOKEN, POSTGRES_PASSWORD, DATABASE_URL, and any
# NEXT_PUBLIC_* variable name that looks like a token/secret/password/key -
# see apps/web/scripts/check-env.js for the runtime-side version of that
# last check).
#
# Usage: scripts/check_secrets.sh   (also wired up as `make check-secrets`)

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

FAILURES=0
pass() { echo "PASS: $1"; }
fail() {
  echo "FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}

# --- 1. No tracked env-style files, other than the two allowed examples -----
# (.env, .env.production, .env.local, .env.*, ...) - the only files allowed
# to be tracked are .env.example and .env.production.example, which must
# only ever contain placeholders (see docs/deployment.md).

echo "== 1. Tracked env files =="
offending_env=$(git ls-files \
  | grep -E '(^|/)\.env(\.[^/]*)?$' \
  | grep -v -E '(^|/)\.env\.example$' \
  | grep -v -E '(^|/)\.env\.production\.example$' \
  || true)

if [[ -n "$offending_env" ]]; then
  fail "git is tracking env file(s) that must never be committed:"
  echo "$offending_env" | sed 's/^/  - /' >&2
  echo "  Fix: git rm --cached <file>   (keeps your local copy, only untracks it)" >&2
  echo "  Then make sure the file is covered by .gitignore, and rotate any secrets" >&2
  echo "  it contained - see docs/deployment.md." >&2
else
  pass "no tracked .env-style files (other than the allowed .example files)"
fi
echo

# --- 2. No tracked backup files ---------------------------------------------
# Postgres dumps (scripts/db_backup.sh) and JSON backup exports
# (services/api/app/export_backup.py) always land under data/backups/ locally
# and must never be committed - both can contain real production data.

echo "== 2. Tracked backup files =="
offending_backups=$(git ls-files \
  | grep -E '(\.sql\.gz$|(^|/)opcg_backup_.*\.json$|(^|/)opcg_db_backup_.*\.sql\.gz$)' \
  || true)

if [[ -n "$offending_backups" ]]; then
  fail "git is tracking backup file(s) that must never be committed:"
  echo "$offending_backups" | sed 's/^/  - /' >&2
  echo "  Fix: git rm --cached <file>   (keeps your local copy, only untracks it)" >&2
else
  pass "no tracked *.sql.gz / opcg_backup_*.json backup files"
fi
echo

# --- 3. Placeholder-only values in the two allowed example env files -------
# .env.example / .env.production.example are allowed to be tracked, but must
# never contain anything other than an obvious placeholder for a secret-
# shaped key - see docs/deployment.md.

echo "== 3. Example env files contain placeholders only =="
EXAMPLE_FILES=(.env.example .env.production.example)
SECRET_KEYS_PATTERN='(ADMIN_TOKEN|TELEGRAM_BOT_TOKEN|POSTGRES_PASSWORD|API_JWT_SECRET|AUTH_SECRET|AUTH_GOOGLE_SECRET)'
# A value counts as an obvious placeholder if it's empty, or matches one of
# these case-insensitive substrings. Anything else (e.g. a real-looking
# random hex/base64 string) fails.
PLACEHOLDER_PATTERN='change-me|changeme|your-|example|placeholder|^$'

example_failures=0
for f in "${EXAMPLE_FILES[@]}"; do
  [[ -f "$f" ]] || continue
  while IFS= read -r line; do
    key="${line%%=*}"
    value="${line#*=}"
    if ! echo "$value" | grep -qiE "$PLACEHOLDER_PATTERN"; then
      fail "$f: $key has a non-placeholder-looking value - use 'change-me' or similar."
      example_failures=$((example_failures + 1))
    fi
  done < <(grep -E "^${SECRET_KEYS_PATTERN}=" "$f" || true)
done
[[ "$example_failures" -eq 0 ]] && pass "${EXAMPLE_FILES[*]} only contain placeholder values"
echo

# --- 4. No literal secret-shaped values committed elsewhere -----------------
# Everywhere else in the tracked tree, these keys should never be assigned a
# literal (non-shell-variable, non-doc-placeholder) value. Excludes the two
# example files (checked separately above, with placeholders allowed), test
# fixtures (which routinely use obviously-fake values), CI workflow files
# (which use throwaway values like ADMIN_TOKEN=x to exercise failure paths),
# and prose docs (which use <angle-bracket> placeholders).
echo "== 4. No literal secret values committed outside the example files =="

CONTENT_SCAN_EXCLUDES=(
  ':!.env.example'
  ':!.env.production.example'
  ':!scripts/check_secrets.sh'
  ':!*/tests/*'
  ':!.github/workflows/*'
  ':!docs/*.md'
  ':!*.md'
)

# Known-safe placeholder/test-fixture literals seen in this repo's scripts -
# extend this list rather than loosening the pattern above if a new
# legitimate placeholder is added.
SAFE_LITERAL_PATTERN='change-me|changeme|placeholder|local-dev-admin-token|opcg:opcg@|^x$'

content_failures=0
while IFS=: read -r file lineno rest; do
  [[ -z "$file" ]] && continue
  value="${rest#*=}"
  # Shell variable references (${VAR}, "$VAR") and doc-style <placeholder>
  # values are never real secrets.
  stripped_value="${value#\"}"
  [[ "$stripped_value" == \$* || "$stripped_value" == \<* ]] && continue
  if echo "$value" | grep -qiE "$SAFE_LITERAL_PATTERN"; then
    continue
  fi
  fail "$file:$lineno: literal value for a secret-shaped key: ${rest%%=*}=..."
  content_failures=$((content_failures + 1))
done < <(git grep -nE "\\b${SECRET_KEYS_PATTERN}=[^\$[:space:]<]" -- . "${CONTENT_SCAN_EXCLUDES[@]}" 2>/dev/null || true)

# DATABASE_URL=postgresql://... with a password other than the known local
# dev default (opcg:opcg) or a shell/placeholder reference.
while IFS=: read -r file lineno rest; do
  [[ -z "$file" ]] && continue
  fail "$file:$lineno: DATABASE_URL with a non-default-looking password."
  content_failures=$((content_failures + 1))
done < <(git grep -nE 'DATABASE_URL=postgresql(\+psycopg)?://[^:]+:[^@]+@' \
  -- . "${CONTENT_SCAN_EXCLUDES[@]}" 2>/dev/null \
  | grep -viE 'opcg:opcg@|change-me|\$\{|placeholder' || true)

[[ "$content_failures" -eq 0 ]] && pass "no literal secret values found outside example files/tests/CI/docs"
echo

# --- 5. No secret-shaped NEXT_PUBLIC_* variable names -----------------------
# Next.js inlines every NEXT_PUBLIC_* var into the client bundle verbatim -
# see apps/web/scripts/check-env.js (the runtime counterpart of this check).
# Any *reference* to such a name (not just an assignment) is worth catching
# here, since even declaring one is a mistake waiting to happen.

echo "== 5. No secret-shaped NEXT_PUBLIC_* variable names =="
next_public_offenders=$(git grep -niE 'NEXT_PUBLIC_[A-Z0-9_]*(TOKEN|SECRET|PASSWORD|KEY)' \
  -- . ':!apps/web/scripts/check-env.js' ':!apps/web/scripts/check-env.test.js' ':!docs/*.md' ':!*.md' \
  2>/dev/null || true)

if [[ -n "$next_public_offenders" ]]; then
  fail "secret-shaped NEXT_PUBLIC_* variable name(s) found:"
  echo "$next_public_offenders" | sed 's/^/  - /' >&2
else
  pass "no secret-shaped NEXT_PUBLIC_* variable names found"
fi
echo

echo "== Summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "check_secrets: OK - no secrets found."
else
  echo "check_secrets: FAILED - $FAILURES issue(s) found." >&2
  exit 1
fi
