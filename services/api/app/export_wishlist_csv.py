import argparse
import os

from app.db import SessionLocal
from app.services.wishlist_csv import export_wishlist_csv

DEFAULT_OUTPUT = "data/exports/wishlist_export.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a user's wishlist to a CSV file.")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output CSV file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Id of the user whose wishlist to export",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        csv_text = export_wishlist_csv(db, user_id=args.user_id)
    finally:
        db.close()

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        f.write(csv_text)

    print(f"Exported wishlist to {args.output}")


if __name__ == "__main__":
    main()
