import argparse
import json
import sys

from app.db import SessionLocal
from app.services.backup import RESTORE_MODES, RestoreConfirmationRequired, restore_backup


def print_report(result) -> None:
    print(f"dry_run: {result.dry_run}")
    print(f"mode: {result.mode}")
    print(f"valid: {result.valid}")
    print(f"backup_version: {result.backup_version}")

    if result.errors:
        print("errors:")
        for e in result.errors:
            print(f"  - {e}")

    if result.warnings:
        print("warnings:")
        for w in result.warnings:
            print(f"  - {w}")

    if result.preview:
        print("preview:")
        for table, counts in result.preview.items():
            print(f"  {table}: {counts}")

    for section in ("created", "updated", "deleted", "skipped"):
        counts = result.summary.get(section, {})
        if counts:
            print(f"{section}:")
            for table, count in counts.items():
                print(f"  {table}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a tracker data backup JSON file.")
    parser.add_argument("json_path", help="Path to the backup JSON file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview the restore without writing to the database"
    )
    parser.add_argument(
        "--mode", default="merge", choices=RESTORE_MODES, help="Restore mode (default: merge)"
    )
    parser.add_argument(
        "--confirm",
        default=None,
        help="Must be 'RESTORE' when using --mode replace without --dry-run",
    )
    args = parser.parse_args()

    with open(args.json_path, encoding="utf-8-sig") as f:
        backup = json.load(f)

    db = SessionLocal()
    try:
        try:
            result = restore_backup(
                db, backup, dry_run=args.dry_run, mode=args.mode, confirm=args.confirm
            )
        except RestoreConfirmationRequired as exc:
            print(f"error: {exc}")
            sys.exit(1)
    finally:
        db.close()

    print_report(result)
    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
