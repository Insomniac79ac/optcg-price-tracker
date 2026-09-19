"""Print a read-only JSON plan for raw snapshot retention eligibility.

Usage:
  python -m app.raw_snapshot_retention_plan
  python -m app.raw_snapshot_retention_plan --sample-limit 20 --compact

This command never invokes the existing prune path. It emits an analytical
report and rolls back its SELECT-only session on exit.
"""

from __future__ import annotations

import argparse
import json

from app.db import SessionLocal
from app.services.raw_snapshot_retention_plan import (
    build_raw_snapshot_retention_plan,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=10,
        help="Maximum snapshot IDs retained as samples per category.",
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
        report = build_raw_snapshot_retention_plan(db, sample_limit=args.sample_limit)
        print(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=None if args.compact else 2,
            )
        )
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
