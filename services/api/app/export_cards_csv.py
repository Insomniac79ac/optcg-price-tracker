import argparse
import os

from app.db import SessionLocal
from app.services.card_catalog_import import export_cards_csv

DEFAULT_OUTPUT = "data/exports/cards_export.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the canonical card catalog to a CSV file.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output CSV file path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        csv_text = export_cards_csv(db)
    finally:
        db.close()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        f.write(csv_text)

    print(f"Exported card catalog to {args.output}")


if __name__ == "__main__":
    main()
