"""CLI wrapper around app.services.data_retention.prune_tables - the same
logic behind POST /admin/data-retention/prune, for use without going through
the API (e.g. a cron job or one-off maintenance on the deploy host). See
"Data retention and pruning" in docs/operations.md.

Usage:
  python -m app.prune_data_retention                              # dry run, all tables
  python -m app.prune_data_retention --tables raw_snapshots,app_log_events
  python -m app.prune_data_retention --apply --confirm PRUNE       # actually deletes

Exit code is non-zero only for a fatal *validation* failure (e.g. --apply
without --confirm PRUNE) - a per-table prune error is reported as that
table's warning in the printed summary, not a nonzero exit, matching how
POST /admin/data-retention/prune itself never fails the whole request over
one table's error.
"""

from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.services.data_retention import CONFIRM_PHRASE, PRUNABLE_TABLES, prune_tables
from app.services.job_locks import LockHeldError


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune old high-volume data per the retention policy in "
        "app.services.data_retention."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete rows. Default is a dry run (count only, delete nothing).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run_flag",
        action="store_true",
        help="Explicit dry run (default behavior - this flag exists for scripts that "
        "want to be explicit about it).",
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help=f"Comma-separated table names (default: all prunable tables - "
        f"{', '.join(PRUNABLE_TABLES)}).",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default=None,
        help=f"Must be exactly {CONFIRM_PHRASE!r} when --apply is set.",
    )
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        help="Skip the data_retention_prune concurrency lock. Test/dev only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.apply

    if args.apply and args.confirm != CONFIRM_PHRASE:
        print(f"FAIL: --apply requires --confirm {CONFIRM_PHRASE}", file=sys.stderr)
        return 1

    tables = [t.strip() for t in args.tables.split(",") if t.strip()] if args.tables else None

    db = SessionLocal()
    try:
        try:
            result = prune_tables(
                db, dry_run=dry_run, tables=tables, confirm=args.confirm, skip_lock=args.skip_lock
            )
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            return 2
    finally:
        db.close()

    print(f"dry_run={result.dry_run}")
    for r in result.results:
        line = (
            f"  {r.table}: retention_days={r.retention_days} "
            f"rows_would_delete={r.rows_would_delete} rows_deleted={r.rows_deleted} "
            f"status={r.status}"
        )
        if r.warning:
            line += f" warning={r.warning}"
        print(line)

    summary = result.summary
    print(
        "Summary: "
        f"tables_checked={summary['tables_checked']} "
        f"total_rows_would_delete={summary['total_rows_would_delete']} "
        f"total_rows_deleted={summary['total_rows_deleted']} "
        f"warnings={summary['warnings']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
