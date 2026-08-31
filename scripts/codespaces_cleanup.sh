#!/usr/bin/env bash
# Safe removal of Codespaces scratch Docker resources.
#
# WHY THIS EXISTS. On 2026-08-31 a cleanup step ran
# `docker volume ls -qf dangling=true | while read v; do docker volume rm $v; done`
# and destroyed all three named project volumes
# (optcg-price-tracker_postgres_data, optcg-prod_opcg_postgres_data_prod,
# optcg-prod_opcg_redis_data_prod). docs/operations.md already forbade
# blanket `docker volume prune`, but nothing said that a *dangling filter* is
# the same mistake wearing a different hat.
#
# DANGLING DOES NOT MEAN DISPOSABLE. Docker calls a volume "dangling" when no
# CONTAINER currently references it. A compose database whose stack is simply
# stopped - the normal state in a Codespace - is dangling by that definition.
# The word describes attachment, not value, and nothing may ever be deleted
# because Docker used it.
#
# THE RULE THIS SCRIPT ENFORCES: disposability is asserted by the caller, by
# exact name, and never inferred. There is no discovery mode for volumes. A
# volume is removed only if you typed its name, and never if it is protected.
#
# Usage:
#   scripts/codespaces_cleanup.sh                          # plan (default)
#   scripts/codespaces_cleanup.sh --containers NAME[,NAME]
#   scripts/codespaces_cleanup.sh --images REPO:TAG[,...]
#   scripts/codespaces_cleanup.sh --build-cache
#   scripts/codespaces_cleanup.sh --volumes NAME[,NAME]    # exact names only
#   ... plus --apply to actually delete.
#
# Nothing is deleted without --apply. --volumes additionally requires
# --confirm-volumes "$VOLUME_CONFIRM_PHRASE" (below), because a volume is the
# only resource here that holds data which cannot be rebuilt from the repo.

set -euo pipefail

# Named volumes that are PROJECT DATA, never scratch. Derived from the compose
# files: docker-compose.yml (project "optcg-price-tracker") declares
# postgres_data; docker-compose.prod.yml (name: optcg-prod) declares
# opcg_postgres_data_prod and opcg_redis_data_prod.
#
# Refused unconditionally - including when passed explicitly to --volumes.
# Removing one of these is a deliberate act that must happen by hand, with the
# operator looking at what they are destroying.
PROTECTED_VOLUMES=(
  "optcg-price-tracker_postgres_data"
  "optcg-prod_opcg_postgres_data_prod"
  "optcg-prod_opcg_redis_data_prod"
)

VOLUME_CONFIRM_PHRASE="delete these volumes"

APPLY=false
BUILD_CACHE=false
CONTAINERS=""
IMAGES=""
VOLUMES=""
VOLUME_CONFIRM=""

die() { echo "FAIL: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    --build-cache) BUILD_CACHE=true; shift ;;
    --containers) CONTAINERS="${2:-}"; shift 2 ;;
    --images) IMAGES="${2:-}"; shift 2 ;;
    --volumes) VOLUMES="${2:-}"; shift 2 ;;
    --confirm-volumes) VOLUME_CONFIRM="${2:-}"; shift 2 ;;
    -h|--help) sed -n '1,40p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

is_protected() {
  local candidate="$1" protected
  for protected in "${PROTECTED_VOLUMES[@]}"; do
    [[ "$candidate" == "$protected" ]] && return 0
  done
  return 1
}

split_csv() {
  [[ -z "$1" ]] && return 0
  echo "$1" | tr ',' '\n' | sed '/^[[:space:]]*$/d' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

if $APPLY; then MODE="APPLY"; else MODE="PLAN (dry-run - nothing will be deleted)"; fi
echo "== Codespaces cleanup: $MODE =="
echo

# --- volumes: refuse protected names before anything else happens -----------
mapfile -t WANTED_VOLUMES < <(split_csv "$VOLUMES")
if [[ ${#WANTED_VOLUMES[@]} -gt 0 ]]; then
  for v in "${WANTED_VOLUMES[@]}"; do
    if is_protected "$v"; then
      die "refusing to touch protected project volume '$v'. It holds local database data and is never scratch. Remove it by hand if you truly mean to."
    fi
  done
  if $APPLY && [[ "$VOLUME_CONFIRM" != "$VOLUME_CONFIRM_PHRASE" ]]; then
    die "--volumes with --apply requires --confirm-volumes \"$VOLUME_CONFIRM_PHRASE\"."
  fi
fi

echo "-- protected volumes (never removed by this script) --"
for v in "${PROTECTED_VOLUMES[@]}"; do
  if docker volume inspect "$v" >/dev/null 2>&1; then echo "  present: $v"; else echo "  absent : $v"; fi
done
echo

echo "-- containers --"
mapfile -t WANTED_CONTAINERS < <(split_csv "$CONTAINERS")
for c in "${WANTED_CONTAINERS[@]:-}"; do
  [[ -z "${c:-}" ]] && continue
  echo "  remove container: $c"
  $APPLY && docker rm -f "$c" >/dev/null 2>&1 || true
done
[[ ${#WANTED_CONTAINERS[@]} -eq 0 ]] && echo "  (none requested)"
echo

echo "-- images --"
mapfile -t WANTED_IMAGES < <(split_csv "$IMAGES")
for i in "${WANTED_IMAGES[@]:-}"; do
  [[ -z "${i:-}" ]] && continue
  echo "  remove image: $i"
  $APPLY && docker rmi "$i" >/dev/null 2>&1 || true
done
[[ ${#WANTED_IMAGES[@]} -eq 0 ]] && echo "  (none requested)"
echo

echo "-- build cache --"
if $BUILD_CACHE; then
  echo "  prune build cache (regenerable)"
  $APPLY && docker builder prune -f >/dev/null 2>&1 || true
else
  echo "  (not requested)"
fi
echo

echo "-- volumes --"
if [[ ${#WANTED_VOLUMES[@]} -eq 0 ]]; then
  echo "  (none requested - this script never discovers volumes to delete)"
else
  for v in "${WANTED_VOLUMES[@]}"; do
    echo "  remove volume: $v"
    $APPLY && docker volume rm "$v" >/dev/null 2>&1 || true
  done
fi
echo

if ! $APPLY; then
  echo "Plan only. Re-run with --apply to perform the actions above."
fi
echo "Disk now:"
df -h / /tmp | sed 's/^/  /'
