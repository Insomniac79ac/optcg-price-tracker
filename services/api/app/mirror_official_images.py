"""CLI: mirror official Bandai card images to R2 (see app.official_images.mirror).

    python -m app.mirror_official_images --dry-run            # count only, no requests
    python -m app.mirror_official_images --write --limit 25   # a bounded batch
    python -m app.mirror_official_images --write              # everything pending
    python -m app.mirror_official_images --write --print-id 5 --print-id 9

Resume-safe: prints that already have a verified copy of their current
image_url are skipped. Bandai is fetched one request at a time, at least
--min-interval seconds apart (never below 1.0). Objects are content-addressed
and never overwritten or deleted. The only database write is one insert-only
card_print_image_assets row per verified print.

Exit codes: 0 all selected prints verified; 1 a failure, digest mismatch or a
stopped run; 2 R2 not configured; 3 another --write run holds the run lock
(app.official_images.lock), so nothing was fetched.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal, engine
from app.official_images.lock import mirror_run_lock
from app.official_images.mirror import MIN_INTERVAL_FLOOR, pending_targets, run_mirror
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Count pending prints; no requests, no writes.")
    mode.add_argument("--write", action="store_true", help="Fetch, upload if absent, verify and record.")
    parser.add_argument("--print-id", type=int, action="append", dest="print_ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-interval", type=float, default=MIN_INTERVAL_FLOOR)
    parser.add_argument("--quiet", action="store_true", help="No per-print progress lines.")
    args = parser.parse_args(argv)

    if args.dry_run:
        with SessionLocal() as db:
            targets = pending_targets(db, print_ids=args.print_ids, limit=args.limit)
        print(json.dumps({"pending": len(targets), "first_print_ids": [t.card_print_id for t in targets[:10]]}))
        return 0
    with mirror_run_lock(engine) as acquired:
        if not acquired:
            print("Another official image mirror run holds the run lock; nothing fetched.", file=sys.stderr)
            return 3
        return _write(args)


def _write(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        targets = pending_targets(db, print_ids=args.print_ids, limit=args.limit)
        try:
            storage = R2ObjectStorage.from_settings()
        except R2ConfigurationError as exc:
            print(f"R2 not configured: {exc}", file=sys.stderr)
            return 2

        def progress(outcome):
            if not args.quiet:
                print(json.dumps({"card_print_id": outcome.card_print_id, "status": outcome.status,
                                  "reason": outcome.reason, "object_key": outcome.object_key}), flush=True)

        report = run_mirror(db, storage, targets, min_interval=args.min_interval, progress=progress)
    print(json.dumps(report.summary(), indent=1))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
