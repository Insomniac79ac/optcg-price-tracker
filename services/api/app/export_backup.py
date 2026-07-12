import argparse
import json
import os

from app.db import SessionLocal
from app.services.backup import export_backup

DEFAULT_OUTPUT = "data/exports/opcg_backup.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a tracker data backup to a JSON file.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output JSON file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--include-prices", action="store_true", help="Include price_observations"
    )
    parser.add_argument(
        "--include-raw-snapshots", action="store_true", help="Include raw_snapshots"
    )
    parser.add_argument(
        "--include-refresh-runs", action="store_true", help="Include price_refresh_runs"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        backup = export_backup(
            db,
            include_prices=args.include_prices,
            include_raw_snapshots=args.include_raw_snapshots,
            include_refresh_runs=args.include_refresh_runs,
        )
    finally:
        db.close()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2)

    row_counts = {table: len(rows) for table, rows in backup["tables"].items()}
    print(f"Exported backup to {args.output}")
    for table, count in row_counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
