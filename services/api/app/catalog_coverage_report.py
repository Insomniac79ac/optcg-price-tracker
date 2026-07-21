"""CLI: `python -m app.catalog_coverage_report` - prints (or writes) the same
report GET /admin/catalog-coverage returns, for scripting/ops use without
going through the API. Read-only - see app.services.catalog_coverage.
"""

import argparse
import json
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.schemas import CatalogCoverageReportOut
from app.services.catalog_coverage import CatalogCoverageFilters, compute_catalog_coverage


def print_summary(summary: dict) -> None:
    for key, value in summary.items():
        print(f"{key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a canonical card catalog coverage report.")
    parser.add_argument("--set-code", default=None, help="Restrict the report to one set_code.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--output", default=None, help="Write the full report as JSON to this path.")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        report = compute_catalog_coverage(db, CatalogCoverageFilters(set_code=args.set_code))
    finally:
        db.close()

    payload = CatalogCoverageReportOut.model_validate(report.to_dict()).model_dump(mode="json")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"Wrote catalog coverage report to {args.output}")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print_summary(payload["summary"])

    sys.exit(0)


if __name__ == "__main__":
    main()
