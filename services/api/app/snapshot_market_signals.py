import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.market_signal_events import SnapshotResult, snapshot_market_signals


def print_report(result: SnapshotResult) -> None:
    print(f"created: {result.created}")
    print(f"updated: {result.updated}")
    print(f"resolved: {result.resolved}")
    print(f"total_active: {result.total_active}")


def main() -> None:
    argparse.ArgumentParser(
        description="Snapshot the current GET /market/signals equivalent into "
        "market_signal_events (create/update/resolve)."
    ).parse_args()

    db: Session = SessionLocal()
    try:
        result = snapshot_market_signals(db)
    finally:
        db.close()

    print_report(result)


if __name__ == "__main__":
    main()
