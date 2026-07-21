"""CLI: `python -m app.price_source_health_report` - prints (or writes) the
same report GET /admin/price-source-health returns, for scripting/ops use
without going through the API. Read-only - see
app.services.price_source_health.
"""

import argparse
import json
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.schemas import PriceSourceHealthReportOut
from app.services.price_source_health import PriceSourceHealthFilters, compute_price_source_health


def print_summary(summary: dict) -> None:
    for key, value in summary.items():
        print(f"{key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a price source health report.")
    parser.add_argument("--source", default=None, help="Restrict the report to one source (yuyutei/snkrdunk).")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    parser.add_argument("--output", default=None, help="Write the full report as JSON to this path.")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        report = compute_price_source_health(db, PriceSourceHealthFilters(source=args.source))
    finally:
        db.close()

    payload = PriceSourceHealthReportOut.model_validate(report.to_dict()).model_dump(mode="json")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"Wrote price source health report to {args.output}")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print_summary(payload["summary"])

    sys.exit(0)


if __name__ == "__main__":
    main()
