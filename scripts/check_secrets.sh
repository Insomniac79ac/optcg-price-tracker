#!/usr/bin/env bash
# Fails if git is tracking any .env-style file that could contain secrets
# (.env, .env.production, .env.local, .env.*, ...) - the only files allowed
# to be tracked are .env.example and .env.production.example, which must
# only ever contain placeholders (see docs/deployment.md).
#
# Usage: scripts/check_secrets.sh   (also wired up as `make check-secrets`)

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

offending=$(git ls-files \
  | grep -E '(^|/)\.env(\.[^/]*)?$' \
  | grep -v -E '(^|/)\.env\.example$' \
  | grep -v -E '(^|/)\.env\.production\.example$' \
  || true)

if [[ -n "$offending" ]]; then
  echo "check_secrets: git is tracking env file(s) that must never be committed:" >&2
  echo "$offending" | sed 's/^/  - /' >&2
  echo >&2
  echo "Fix: git rm --cached <file>   (keeps your local copy, only untracks it)" >&2
  echo "Then make sure the file is covered by .gitignore, and rotate any secrets" >&2
  echo "it contained - see docs/deployment.md." >&2
  exit 1
fi

echo "check_secrets: OK - no tracked env secret files found."
