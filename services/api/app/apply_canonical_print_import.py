"""CLI: apply the safe, verified subset of a canonical print import.

    # plan only - the default, writes nothing
    python -m app.apply_canonical_print_import --database-url postgresql+psycopg://...

    # actually write, to a disposable database
    python -m app.apply_canonical_print_import --database-url ... \
        --environment test --apply

WHY THIS IS A SEPARATE COMMAND. `app.plan_canonical_print_import` is
read-only by construction and documents itself as having no write path. Adding
`--apply` to it would make that promise conditional, and the promise is the
point. This module is the only one that writes, so "does this command write?"
is answered by which module you typed.

FOUR THINGS MUST ALL BE TRUE BEFORE A SINGLE ROW IS WRITTEN

    1. `--apply` is passed. Without it this is a dry run that opens a
       transaction, composes nothing and rolls back.
    2. `--environment` names an allowlisted environment. `production` and
       `prod` are hard-refused by name; `staging` is refused too, because
       canonical staging writes are not authorised in this tranche.
    3. The database is at the alembic revision the plan was built against.
    4. The counts the plan was built against still hold, and - when
       `--expect-snapshot` is given - the snapshot on disk is still the one
       the plan was reviewed from.

INPUT IS FROZEN. Entries, series and asset digests are read from the local
snapshot under `data/official_snapshots/<catalogue>/current`, never from
Bandai. The snapshot's identity hash is pinned into the run and reported, so
an apply can be traced to the exact bytes it was planned from. There is no
flag that makes this command fetch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.canonical_import_apply import (
    ALLOWED_APPLY_ENVIRONMENTS,
    REFUSED_APPLY_ENVIRONMENTS,
    ApplyPinning,
    ApplyRunFailed,
    CanonicalImportApplier,
    current_counts,
    db_revision,
)
from app.services.print_import_planner import plan_entries
from app.services.snapshot_planner_input import (
    SnapshotInputError,
    default_snapshot_root,
    load_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy URL of the target database. Must be a disposable or restored "
        "copy - canonical staging is refused by --environment.",
    )
    parser.add_argument(
        "--environment",
        default=None,
        help="Target environment, acknowledged explicitly. Allowed: "
        f"{', '.join(ALLOWED_APPLY_ENVIRONMENTS)}. Refused: "
        f"{', '.join(REFUSED_APPLY_ENVIRONMENTS)}.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without this the run is a dry run and rolls back.",
    )
    parser.add_argument(
        "--snapshot-root",
        default=None,
        help="Snapshot directory to read. Defaults to the repo's bandai_jp current snapshot.",
    )
    parser.add_argument(
        "--source-catalogue",
        default="bandai_jp",
        help="Catalogue to apply. Only bandai_jp is supported in this tranche.",
    )
    parser.add_argument(
        "--expect-revision",
        default=None,
        help="Alembic revision the plan was built against. The run aborts if the "
        "database is at a different one.",
    )
    parser.add_argument(
        "--expect-snapshot",
        default=None,
        help="Snapshot identity the plan was reviewed against. The run aborts if the "
        "snapshot on disk has been recollected since.",
    )
    parser.add_argument(
        "--expect-counts",
        default=None,
        help="JSON object of table->count the plan was built against. The run aborts "
        "if the database has drifted.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    environment = (args.environment or "").strip().lower()
    if args.apply:
        if not environment:
            print(
                "FAIL: --apply requires --environment naming the target explicitly "
                f"(allowed: {', '.join(ALLOWED_APPLY_ENVIRONMENTS)}).",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if environment in REFUSED_APPLY_ENVIRONMENTS:
            print(
                f"REFUSED: this command never applies to '{environment}'.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if environment not in ALLOWED_APPLY_ENVIRONMENTS:
            print(
                f"REFUSED: environment '{environment}' is not in the apply allowlist "
                f"({', '.join(ALLOWED_APPLY_ENVIRONMENTS)}).",
                file=sys.stderr,
            )
            return EXIT_USAGE

    if args.source_catalogue != "bandai_jp":
        print("FAIL: only --source-catalogue bandai_jp is supported.", file=sys.stderr)
        return EXIT_USAGE

    root = Path(args.snapshot_root) if args.snapshot_root else default_snapshot_root(
        REPO_ROOT, source_catalogue=args.source_catalogue
    )
    try:
        snapshot = load_snapshot(root, source_catalogue=args.source_catalogue)
    except SnapshotInputError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_USAGE

    expected_counts = None
    if args.expect_counts:
        try:
            expected_counts = json.loads(args.expect_counts)
        except json.JSONDecodeError as exc:
            print(f"FAIL: --expect-counts is not valid JSON: {exc}", file=sys.stderr)
            return EXIT_USAGE

    if not args.json:
        print("== canonical print import apply ==")
        for key, value in snapshot.describe().items():
            print(f"  {key:<24} {value}")
        print(f"  {'mode':<24} {'APPLY' if args.apply else 'dry-run (no writes)'}")
        print(f"  {'environment':<24} {environment or '<unset>'}")

    engine = create_engine(args.database_url)
    with Session(engine) as session:
        plan = plan_entries(
            session,
            snapshot.entries,
            series_index=snapshot.series,
            source_catalogue=args.source_catalogue,
            digest_provider=snapshot.digest_provider(),
            classify_mappings=False,
        )
        pinning = ApplyPinning(
            snapshot_identity=snapshot.identity,
            source_catalogue=args.source_catalogue,
            expected_db_revision=args.expect_revision or db_revision(session),
            expected_pre_counts=expected_counts,
            expected_snapshot_identity=args.expect_snapshot,
        )
        applier = CanonicalImportApplier(
            session,
            plan,
            pinning=pinning,
            environment=environment,
            entries={entry.entry_id: entry for entry in snapshot.entries},
        )
        try:
            report = applier.run(apply=args.apply)
        except ApplyRunFailed as exc:
            print(json.dumps(exc.report.to_dict(), indent=2, ensure_ascii=False))
            print(
                f"\nROLLED BACK: {exc.report.rollback_reason} - {exc.report.rollback_detail}",
                file=sys.stderr,
            )
            return EXIT_FAILED

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if not args.json:
        print(
            "\nOK: "
            + ("applied" if report.applied else "dry run complete, nothing written")
        )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
