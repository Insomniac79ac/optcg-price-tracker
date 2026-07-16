#!/usr/bin/env bash
# Deletes old Postgres backups created by scripts/db_backup.sh, keeping the
# newest BACKUP_KEEP files. Dry-run by default - prints what would be
# deleted without touching anything; pass --apply to actually delete.
#
# Usage:
#   bash scripts/db_backup_prune.sh            # dry run
#   bash scripts/db_backup_prune.sh --apply     # actually delete
#   (also wired up as `make prod-db-backup-prune` / `make prod-db-backup-prune-apply`)
#
# Env vars:
#   BACKUP_DIR   default data/backups/db
#   BACKUP_KEEP  default 14 - number of newest backups to keep

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-data/backups/db}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"

APPLY=false
for arg in "$@"; do
  case "$arg" in
    --apply)
      APPLY=true
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: bash scripts/db_backup_prune.sh [--apply]" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "No backup directory at $BACKUP_DIR - nothing to prune."
  exit 0
fi

# Newest first by modification time.
mapfile -t backups < <(ls -1t "$BACKUP_DIR"/opcg_db_backup_*.sql.gz 2>/dev/null || true)
total=${#backups[@]}

if (( total <= BACKUP_KEEP )); then
  echo "$total backup(s) found in $BACKUP_DIR (keep=$BACKUP_KEEP) - nothing to prune."
  exit 0
fi

to_delete=("${backups[@]:$BACKUP_KEEP}")

echo "$total backup(s) found in $BACKUP_DIR, keeping newest $BACKUP_KEEP, ${#to_delete[@]} to remove:"
for f in "${to_delete[@]}"; do
  echo "  $f"
done

if [[ "$APPLY" != true ]]; then
  echo
  echo "Dry run - no files deleted. Re-run with --apply to delete the file(s) above."
  exit 0
fi

for f in "${to_delete[@]}"; do
  rm -f "$f"
done
echo "Deleted ${#to_delete[@]} backup(s)."
