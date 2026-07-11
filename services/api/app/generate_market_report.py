import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import MarketIntelligenceReport
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
    argparse.ArgumentParser(
        description="Generate and store one market intelligence report from current data."
    ).parse_args()

    db: Session = SessionLocal()
    try:
        report = generate_market_report(db)
    finally:
        db.close()

    print_report(report)


if __name__ == "__main__":
    main()
