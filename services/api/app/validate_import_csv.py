import argparse
import json
import sys

from app.db import SessionLocal
from app.models import ImportValidationReport
from app.services.import_validation import IMPORT_TYPES, ValidationResult, validate_import_csv


def print_report(result: ValidationResult) -> None:
    summary = result.summary
    lines = [
        f"import_type: {result.import_type}",
        f"valid: {result.valid}",
        f"total_rows: {summary.total_rows}",
        f"valid_rows: {summary.valid_rows}",
        f"error_rows: {summary.error_rows}",
        f"warning_rows: {summary.warning_rows}",
        f"duplicate_rows: {summary.duplicate_rows}",
        f"would_create: {summary.would_create}",
        f"would_update: {summary.would_update}",
        f"would_skip: {summary.would_skip}",
    ]
    for line in lines:
        print(line)

    if result.columns.missing_required_columns:
        print(f"\nmissing required columns: {result.columns.missing_required_columns}")
    if result.columns.unknown_columns:
        print(f"unknown columns: {result.columns.unknown_columns}")

    if result.errors:
        print("\nerrors:")
        for e in result.errors:
            print(f"  row {e.row_number} [{e.field}] ({e.code}): {e.message}")

    if result.warnings:
        print("\nwarnings:")
        for w in result.warnings:
            print(f"  row {w.row_number} [{w.field}] ({w.code}): {w.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a bulk-import CSV file without writing to the database.")
    parser.add_argument("csv_path", help="Path to the CSV file to validate")
    parser.add_argument("--type", required=True, choices=IMPORT_TYPES, help="Import type")
    parser.add_argument("--strict", action="store_true", help="Treat unknown columns as errors")
    parser.add_argument("--max-preview-rows", type=int, default=100, help="Maximum preview rows to include")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report instead of a summary")
    parser.add_argument("--user-id", type=int, default=None, help="Scope collection/wishlist duplicate detection to a user")
    parser.add_argument(
        "--no-save-report",
        dest="save_report",
        action="store_false",
        default=True,
        help="Do not persist a row to import_validation_reports (default: save)",
    )
    args = parser.parse_args()

    with open(args.csv_path, "rb") as f:
        csv_bytes = f.read()

    db = SessionLocal()
    try:
        result = validate_import_csv(
            db,
            args.type,
            csv_bytes,
            strict=args.strict,
            max_preview_rows=args.max_preview_rows,
            user_id=args.user_id,
        )

        if args.save_report:
            report = ImportValidationReport(
                import_type=args.type,
                filename=args.csv_path,
                valid=result.valid,
                strict=args.strict,
                total_rows=result.summary.total_rows,
                valid_rows=result.summary.valid_rows,
                error_rows=result.summary.error_rows,
                warning_rows=result.summary.warning_rows,
                duplicate_rows=result.summary.duplicate_rows,
                report_payload_json=result.to_dict(),
            )
            db.add(report)
            db.commit()
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print_report(result)

    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
