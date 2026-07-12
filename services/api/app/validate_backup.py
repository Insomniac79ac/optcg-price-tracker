import argparse
import json
import sys

from app.services.backup import validate_backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a tracker data backup JSON file.")
    parser.add_argument("json_path", help="Path to the backup JSON file")
    args = parser.parse_args()

    with open(args.json_path, encoding="utf-8-sig") as f:
        backup = json.load(f)

    result = validate_backup(backup)

    print(f"valid: {result.valid}")
    print(f"backup_version: {result.backup_version}")
    print("summary:")
    for table, count in result.summary.items():
        print(f"  {table}: {count}")

    if result.warnings:
        print("warnings:")
        for w in result.warnings:
            print(f"  - {w}")

    if result.errors:
        print("errors:")
        for e in result.errors:
            print(f"  - {e}")

    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
