"""Run the A2 Market Value replay without writing database state."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import text

from app.db import SessionLocal
from app.services.market_value_replay import build_market_value_replay_report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay archived Market Index snapshots through Market Value v1."
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--require-postgres-read-only",
        action="store_true",
        help="Fail unless PostgreSQL confirms transaction_read_only=on.",
    )
    return parser.parse_args()


def _with_execution(
    report: dict[str, Any], *, dialect: str, read_only_enforced: bool
) -> dict[str, Any]:
    return {
        "execution": {
            "database_dialect": dialect,
            "server_enforced_read_only": read_only_enforced,
        },
        **report,
    }


def main() -> int:
    args = _parse_args()
    db = SessionLocal()
    try:
        dialect = db.get_bind().dialect.name
        read_only_enforced = False
        if dialect == "postgresql":
            # This is the first statement. PostgreSQL itself rejects every
            # write and DDL statement for the rest of this transaction.
            db.execute(
                text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            )
            read_only_enforced = (
                db.scalar(text("SHOW transaction_read_only")) == "on"
            )
            if not read_only_enforced:
                raise RuntimeError("PostgreSQL did not enable transaction_read_only")
        elif args.require_postgres_read_only:
            raise RuntimeError(
                "expected PostgreSQL for server-enforced read-only execution, "
                f"got {dialect}"
            )

        payload = _with_execution(
            build_market_value_replay_report(db),
            dialect=dialect,
            read_only_enforced=read_only_enforced,
        )
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
        print(f"market-value replay failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # A report transaction is rolled back and closed even though the
        # server guard already makes writes impossible on PostgreSQL.
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
