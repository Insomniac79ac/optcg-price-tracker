import argparse

from app.db import SessionLocal
from app.services.wishlist_csv import IMPORT_MODES, ImportResult, import_wishlist_csv


def print_report(result: ImportResult) -> None:
    lines = [
        f"dry_run: {result.dry_run}",
        f"mode: {result.mode}",
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
            print(
                f"  row {p.row_number} {p.card_code} -> {p.action} "
                f"(card_id={p.matched_card_id}, priority={p.priority}, status={p.status})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a wishlist CSV file.")
    parser.add_argument("csv_path", help="Path to the wishlist CSV file")
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Id of the user whose wishlist this import writes into",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the import without writing to the database",
    )
    parser.add_argument(
        "--mode",
        default="upsert",
        choices=IMPORT_MODES,
        help="Import mode (default: upsert)",
    )
    args = parser.parse_args()

    with open(args.csv_path, encoding="utf-8-sig") as f:
        csv_text = f.read()

    db = SessionLocal()
    try:
        result = import_wishlist_csv(
            db, csv_text, dry_run=args.dry_run, mode=args.mode, user_id=args.user_id
        )
    finally:
        db.close()

    print_report(result)


if __name__ == "__main__":
    main()
