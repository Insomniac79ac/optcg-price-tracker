"""CLI for the read-only exact-print source-mapping coverage inventory."""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from app.db import SessionLocal
from app.services.exact_print_mapping_coverage import (
    compute_exact_print_mapping_coverage,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap-limit", type=int, default=100)
    parser.add_argument("--gap-offset", type=int, default=0)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--require-postgres-read-only",
        action="store_true",
        help="Fail unless PostgreSQL confirms transaction_read_only=on.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db = SessionLocal()
    try:
        dialect = db.get_bind().dialect.name
        read_only_enforced = False
        if dialect == "postgresql":
            # First statement in the transaction: PostgreSQL itself rejects
            # INSERT/UPDATE/DELETE/DDL after this, independent of app code.
            db.execute(text("SET TRANSACTION READ ONLY"))
            read_only_enforced = db.scalar(text("SHOW transaction_read_only")) == "on"
            if not read_only_enforced:
                raise RuntimeError("PostgreSQL did not enable transaction_read_only")
        elif args.require_postgres_read_only:
            raise RuntimeError(
                f"expected PostgreSQL for server-enforced read-only execution, got {dialect}"
            )

        report = compute_exact_print_mapping_coverage(
            db, gap_limit=args.gap_limit, gap_offset=args.gap_offset
        )
        payload = {
            "execution": {
                "database_dialect": dialect,
                "server_enforced_read_only": read_only_enforced,
            },
            **report.to_dict(),
        }
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2 if args.pretty else None,
                separators=None if args.pretty else (",", ":"),
            )
        )
        return 0
    except Exception as exc:
        print(f"exact-print coverage report failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # Never commit this reporting transaction, even on SQLite/local use.
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
