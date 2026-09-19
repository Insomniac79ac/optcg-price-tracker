"""Print a read-only JSON inventory of historical pricing lineage.

Usage:
  python -m app.historical_lineage_inventory
  python -m app.historical_lineage_inventory --sample-limit 5 --compact
"""

from __future__ import annotations

import argparse
import json

from app.db import SessionLocal
from app.services.historical_lineage_inventory import (
    build_historical_lineage_inventory,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="Maximum number of row/group samples retained per category.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of indented JSON.",
    )
    args = parser.parse_args(argv)
    if args.sample_limit < 0:
        parser.error("--sample-limit must be >= 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db = SessionLocal()
    try:
        report = build_historical_lineage_inventory(
            db, sample_limit=args.sample_limit
        )
        print(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=None if args.compact else 2,
            )
        )
    finally:
        # The service issues SELECTs only. Rollback rather than commit also
        # makes the command's transaction boundary explicitly non-writing.
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
