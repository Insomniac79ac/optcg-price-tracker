import argparse
import sys

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.job_locks import LockHeldError
from app.services.market_signal_events import SnapshotResult, snapshot_market_signals


def print_report(result: SnapshotResult) -> None:
    print(f"created: {result.created}")
    print(f"updated: {result.updated}")
    print(f"resolved: {result.resolved}")
    print(f"total_active: {result.total_active}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Snapshot the current GET /market/signals equivalent into "
        "market_signal_events (create/update/resolve)."
    )
    parser.add_argument(
        "--skip-lock", action="store_true",
        help="Skip the market_signal_snapshot concurrency lock. Test/dev only.",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        try:
            result = snapshot_market_signals(db, skip_lock=args.skip_lock)
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            sys.exit(2)
    finally:
        db.close()

    print_report(result)


if __name__ == "__main__":
    main()
