"""CLI for catalogue-wide exact-print proposal analysis and persistence."""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import text

from app.db import SessionLocal
from app.services.source_mapping_proposals import (
    ProposalFilters,
    analyse_source_mapping_proposals,
    persist_proposals,
)


CONFIRM_PERSIST = "persist source mapping proposals"


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("all", "yuyutei", "snkrdunk"), default="all")
    parser.add_argument("--all-releases", action="store_true")
    parser.add_argument("--release-product-id", type=int)
    parser.add_argument("--release-code")
    parser.add_argument(
        "--resolution-status",
        choices=("exact", "ambiguous", "unresolved_identity", "release_unresolved", "conflict", "stale", "superseded"),
    )
    parser.add_argument("--candidate-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--require-postgres-read-only", action="store_true")
    parser.add_argument("--include-groups", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run == args.persist:
        parser.error("choose exactly one of --dry-run or --persist")
    if args.persist and args.confirm != CONFIRM_PERSIST:
        parser.error(f'--persist requires --confirm "{CONFIRM_PERSIST}"')
    if args.all_releases and (args.release_product_id or args.release_code):
        parser.error("--all-releases cannot be combined with a release filter")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.offset < 0:
        parser.error("--offset must be >= 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    db = SessionLocal()
    try:
        dialect = db.get_bind().dialect.name
        server_read_only = False
        if args.dry_run and dialect == "postgresql":
            # First statement: PostgreSQL, not application convention, blocks writes.
            db.execute(text("SET TRANSACTION READ ONLY"))
            server_read_only = db.scalar(text("SHOW transaction_read_only")) == "on"
            if not server_read_only:
                raise RuntimeError("PostgreSQL did not enable transaction_read_only")
        elif args.require_postgres_read_only:
            raise RuntimeError(
                "--require-postgres-read-only requires PostgreSQL dry-run execution"
            )
        analysis = analyse_source_mapping_proposals(
            db,
            ProposalFilters(
                source=args.source,
                release_product_id=args.release_product_id,
                release_code=args.release_code,
                resolution_status=args.resolution_status,
                candidate_id=args.candidate_id,
                limit=args.limit,
                offset=args.offset,
            ),
        )
        persistence = None
        if args.persist:
            result = persist_proposals(db, analysis.plans)
            db.commit()
            persistence = result.__dict__
        else:
            db.rollback()
        payload = {
            "execution": {
                "database_dialect": dialect,
                "dry_run": args.dry_run,
                "server_enforced_read_only": server_read_only,
                "persisted": bool(args.persist),
            },
            **analysis.to_dict(include_groups=args.include_groups),
        }
        if persistence is not None:
            payload["persistence"] = persistence
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"source mapping proposal report failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

