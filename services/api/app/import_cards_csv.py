import argparse

from app.db import SessionLocal
from app.services.card_catalog_import import ImportResult, import_cards_csv


def print_report(result: ImportResult) -> None:
    lines = [
        f"dry_run: {result.dry_run}",
        f"overwrite: {result.overwrite}",
        f"total_rows: {result.total_rows}",
        f"valid_rows: {result.valid_rows}",
        f"error_rows: {result.error_rows}",
        f"created: {result.created}",
        f"updated: {result.updated}",
        f"skipped: {result.skipped}",
    ]
    for line in lines:
        print(line)

    if result.errors:
        print("\nerrors:")
        for e in result.errors:
            print(f"  row {e.row_number} ({e.card_code}): {e.error}")

    if result.preview:
        print("\npreview:")
        for p in result.preview:
            changed_fields = ", ".join(p.changes.keys())
            print(f"  row {p.row_number} {p.card_code} -> {p.action} ({changed_fields})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a canonical card catalog CSV file.")
    parser.add_argument("csv_path", help="Path to the card catalog CSV file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the import without writing to the database",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing non-empty fields (default: only fill in blank fields)",
    )
    args = parser.parse_args()

    with open(args.csv_path, encoding="utf-8-sig") as f:
        csv_text = f.read()

    db = SessionLocal()
    try:
        result = import_cards_csv(
            db, csv_text, dry_run=args.dry_run, overwrite=args.overwrite
        )
    finally:
        db.close()

    print_report(result)


if __name__ == "__main__":
    main()
