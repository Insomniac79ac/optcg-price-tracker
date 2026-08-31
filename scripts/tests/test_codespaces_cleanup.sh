#!/usr/bin/env bash
# Safety tests for scripts/codespaces_cleanup.sh.
#
# These assert the properties that would have prevented the 2026-08-31
# incident, in which a dangling-volume filter destroyed all three named
# project volumes. They deliberately do NOT create or delete real Docker
# resources: every assertion is about what the script refuses, what it plans,
# and what it never discovers on its own.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEANUP="$SCRIPT_DIR/../codespaces_cleanup.sh"

PASS=0
FAIL=0

ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

check_contains() {  # description, haystack, needle
  if [[ "$2" == *"$3"* ]]; then ok "$1"; else bad "$1 (expected to contain: $3)"; fi
}
check_not_contains() {
  if [[ "$2" != *"$3"* ]]; then ok "$1"; else bad "$1 (should NOT contain: $3)"; fi
}

echo "== codespaces_cleanup.sh safety tests =="

# 1. A protected volume is refused, even when explicitly supplied.
for protected in optcg-price-tracker_postgres_data \
                 optcg-prod_opcg_postgres_data_prod \
                 optcg-prod_opcg_redis_data_prod; do
  out="$(bash "$CLEANUP" --volumes "$protected" --apply \
        --confirm-volumes "delete these volumes" 2>&1 || true)"
  check_contains "protected volume refused: $protected" "$out" "refusing to touch protected project volume"
done

# 2. A protected volume is refused even when hidden among disposable ones.
out="$(bash "$CLEANUP" --volumes "scratch_a,optcg-prod_opcg_redis_data_prod,scratch_b" --apply \
      --confirm-volumes "delete these volumes" 2>&1 || true)"
check_contains "protected volume refused when mixed with others" "$out" "refusing to touch protected project volume"
check_not_contains "no volume removal planned once a protected name appears" "$out" "remove volume: scratch_a"

# 3. Dry-run is the default: an arbitrary named volume is NOT removed.
out="$(bash "$CLEANUP" --volumes some_scratch_volume 2>&1 || true)"
check_contains "dry-run plans the removal" "$out" "remove volume: some_scratch_volume"
check_contains "dry-run announces itself" "$out" "PLAN (dry-run"
check_contains "dry-run tells you how to apply" "$out" "Re-run with --apply"

# 4. Destructive volume mode requires the confirmation phrase.
out="$(bash "$CLEANUP" --volumes some_scratch_volume --apply 2>&1 || true)"
check_contains "--apply on volumes without confirmation is refused" "$out" "requires --confirm-volumes"
out="$(bash "$CLEANUP" --volumes some_scratch_volume --apply --confirm-volumes "wrong phrase" 2>&1 || true)"
check_contains "wrong confirmation phrase is refused" "$out" "requires --confirm-volumes"

# 5. Nothing is selected unless explicitly named.
out="$(bash "$CLEANUP" 2>&1 || true)"
check_contains "no containers selected by default" "$out" "-- containers --"
check_contains "no volumes discovered by default" "$out" "this script never discovers volumes to delete"
check_not_contains "default run removes nothing" "$out" "remove volume:"

# 6. The script must never use dangling/prune-based volume discovery in any
#    EXECUTABLE line. Comments are excluded deliberately: the script's header
#    quotes the dangerous commands in order to explain why they are banned,
#    and a test that cannot tell an explanation from an instruction would
#    push that explanation out of the codebase.
code_only() { sed 's/[[:space:]]*#.*$//' "$1" | sed '/^[[:space:]]*$/d'; }
src="$(code_only "$CLEANUP")"
check_not_contains "no executable 'docker volume prune'" "$src" "docker volume prune"
check_not_contains "no executable 'docker system prune'" "$src" "docker system prune"
check_not_contains "no executable dangling filter" "$src" "dangling=true"
check_not_contains "no executable bulk volume listing" "$src" "docker volume ls -q"

# 7. The repository at large must not reintroduce the hazard in automation.
#    Same comment-stripping rule, and this test file is excluded because its
#    assertions necessarily contain the very strings being banned.
repo_root="$(cd "$SCRIPT_DIR/../.." && pwd)"
hits=""
while IFS= read -r f; do
  [[ "$f" == "$SCRIPT_DIR/test_codespaces_cleanup.sh" ]] && continue
  if code_only "$f" | grep -qE "docker volume prune|docker system prune[^|]*--volumes|dangling=true|docker volume ls -q"; then
    hits="$hits $f"
  fi
done < <(find "$repo_root" -name node_modules -prune -o \( -name '*.sh' -o -name 'Makefile' \) -print 2>/dev/null)
if [[ -z "$hits" ]]; then
  ok "no shell script or Makefile executes destructive volume discovery"
else
  bad "destructive volume discovery found in:$hits"
fi

echo
echo "passed=$PASS failed=$FAIL"
[[ $FAIL -eq 0 ]]
