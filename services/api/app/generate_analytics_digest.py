import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AnalyticsDigestReport
from app.services.analytics_digest import NoUsersError, generate_analytics_digest
from app.services.job_locks import LockHeldError

VALUATION_MODES = ("raw_market", "graded_adjusted")


def print_report(report: AnalyticsDigestReport) -> None:
    lines = [
        f"report_id: {report.id}",
        f"valuation_mode: {report.valuation_mode}",
        f"risk_score: {report.portfolio_risk_score}",
        f"buy_review_count: {report.buy_review_count}",
        f"sell_review_count: {report.sell_review_count}",
    ]
    for line in lines:
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and store one analytics digest report from current data."
    )
    parser.add_argument(
        "--valuation-mode", choices=VALUATION_MODES, default="raw_market",
        help="Which valuation figure to score/rank against (default: raw_market).",
    )
    parser.add_argument(
        "--skip-lock", action="store_true",
        help="Skip the analytics_digest_generation concurrency lock. Test/dev only.",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        try:
            report = generate_analytics_digest(
                db, valuation_mode=args.valuation_mode, skip_lock=args.skip_lock
            )
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            sys.exit(2)
        except NoUsersError as exc:
            print(str(exc))
            sys.exit(1)
    finally:
        db.close()

    print_report(report)


if __name__ == "__main__":
    main()
