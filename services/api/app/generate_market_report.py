import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import MarketIntelligenceReport
from app.services.job_locks import LockHeldError
from app.services.market_report import generate_market_report


def print_report(report: MarketIntelligenceReport) -> None:
    lines = [
        f"report_id: {report.id}",
        f"report_date: {report.report_date}",
        f"total_opportunities: {report.total_opportunities}",
        f"highest_score: {report.highest_score}",
    ]
    for line in lines:
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and store one market intelligence report from current data."
    )
    parser.add_argument(
        "--skip-lock", action="store_true",
        help="Skip the market_report_generation concurrency lock. Test/dev only.",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        try:
            report = generate_market_report(db, skip_lock=args.skip_lock)
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            sys.exit(2)
    finally:
        db.close()

    print_report(report)


if __name__ == "__main__":
    main()
