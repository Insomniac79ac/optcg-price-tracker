"""CLI: the ONLY supported path that writes the frozen Bandai catalogue to the
one canonical Railway staging database.

    # dry run - the default, database-level read-only, writes nothing
    python -m app.import_frozen_bandai_to_canonical_staging

    # apply - requires the exact confirmation phrase, nothing else works
    python -m app.import_frozen_bandai_to_canonical_staging --apply \\
        --confirm IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING

WHY A SEPARATE COMMAND. `app.apply_canonical_print_import` refuses
`--environment staging`, and 4D-1 does not change that: it must stay true that
no flag on the generic command reaches canonical staging, because the generic
command also accepts `--database-url`, and "staging" would then be a label an
operator could paste onto any database. This command has NO `--database-url`.
The connection is resolved from the Railway `staging` environment itself and
verified before it is used, so the target is a fact about the infrastructure
rather than a claim in an argument list.

WHAT IT DOES NOT DO. It does not plan, does not decide identity, and does not
write a row itself. Every decision is made by the existing engine:
`print_import_planner` plans, `CanonicalImportApplier` applies, and every
protection they carry - planner conflicts, asset-digest drift, snapshot
identity pinning, stale pre-apply counts, the advisory lock, the untouched
tables invariant - runs unchanged and cannot be skipped from here. This module
resolves a target, proves it, asks for a confirmation phrase, and gets out of
the way.

FOUR THINGS MUST ALL BE TRUE BEFORE A SINGLE ROW IS WRITTEN

    1. `--apply` is passed. Without it the session is opened read-only at the
       server, so a write would be rejected by PostgreSQL rather than trusted
       not to happen.
    2. `--confirm` matches IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING exactly.
       A typo refuses. There is no --force and no --yes.
    3. The connection attests as canonical Atlas staging: a fresh
       `railway connect --tunnel-only` tunnel into environment `staging`,
       every fail-closed fingerprint from scripts/staging_db_read_check.py
       PASSing, and an alembic revision equal to this checkout's head.
    4. The existing engine's own preflight agrees: revision, snapshot identity
       and current counts are re-proved inside the writing transaction.

SECRETS. The tunnel URL is never printed - not on success, not in a refusal,
not in the JSON report, and not in a traceback. Logs identify the Railway
environment, the service, the redacted host:port/database and the alembic
revision, all of which the established read checker already treats as
non-secret.

Containment is three layers, and only the third is a filter:

    1. `railway connect`'s stdout and stderr are CAPTURED by
       `staging_db_read_check.open_tunnel` (`stdout=PIPE`, `stderr=STDOUT`)
       and read line by line by that function. The child never writes to the
       operator's terminal, and only the `URL:` line is parsed out.
    2. The URL lives in one field, `VerifiedStagingTarget.url`, which is
       `repr=False`, is never passed to a logger, and is never interpolated
       into a message. Everything an operator sees comes from
       `.redacted` (host:port/database) or the attestation.
    3. Every unexpected exception this module reports goes through
       `scrub_credentials` before it is printed, including the traceback, so
       a driver message that quotes a DSN is redacted rather than shown.

Exit codes
----------
    0  the dry run completed, or the apply committed
    1  a check inside the run refused - nothing was written
    2  usage, confirmation or target-verification refusal - no write was reached
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.services import canonical_staging_target as target_authority
from app.services.canonical_import_apply import (
    CANONICAL_STAGING_ENVIRONMENT,
    STAGING_APPLY_CONFIRMATION,
    ApplyPinning,
    ApplyRunFailed,
    CanonicalImportApplier,
    grant_canonical_staging_write,
)
from app.services.canonical_staging_target import (
    StagingTargetRefused,
    scrub_credentials,
)
from app.services.print_import_planner import plan_entries
from app.services.snapshot_planner_input import (
    SnapshotInputError,
    default_snapshot_root,
    load_snapshot,
)
from app.settings import normalize_database_url

REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_CATALOGUE = "bandai_jp"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="There is no --database-url: the target is resolved from Railway.",
    )
    parser.add_argument(
        "--railway-environment",
        default=CANONICAL_STAGING_ENVIRONMENT,
        help="Railway environment to resolve. Only "
        f"{CANONICAL_STAGING_ENVIRONMENT!r} is accepted; the flag exists so a "
        "wrong value is a visible refusal rather than a silent assumption.",
    )
    parser.add_argument(
        "--railway-service",
        default=None,
        help="Railway database service name (default: the read checker's).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write. Without this the run is a dry run on a read-only session.",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        metavar="PHRASE",
        help=f"Required with --apply. Must be exactly {STAGING_APPLY_CONFIRMATION}.",
    )
    parser.add_argument(
        "--snapshot-root",
        default=None,
        help="Snapshot directory to read. Defaults to the repo's bandai_jp current "
        "snapshot. Never fetches from Bandai.",
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
        help="JSON object of table->count the plan was reviewed against. The run "
        "aborts if canonical staging has drifted since the dry run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report.",
    )
    return parser


def _session_factory(url: str, *, read_only: bool):
    """An engine for the verified tunnel, read-only unless applying.

    On a dry run the server itself is told to reject writes, so "the dry run
    wrote nothing" is enforced by PostgreSQL rather than asserted by this
    module.
    """
    engine = create_engine(normalize_database_url(url), pool_pre_ping=True)
    if read_only and engine.dialect.name == "postgresql":

        @event.listens_for(engine, "connect")
        def _set_read_only(dbapi_connection, _record):  # pragma: no cover - driver level
            dbapi_connection.read_only = True

    return engine


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    emit = (lambda line="": None) if args.json else (lambda line="": print(line, flush=True))

    # --- refusals that need no connection, checked first ------------------
    environment = (args.railway_environment or "").strip().lower()
    if environment != CANONICAL_STAGING_ENVIRONMENT:
        print(
            f"REFUSED: this runner only writes the canonical "
            f"{CANONICAL_STAGING_ENVIRONMENT!r} environment; got "
            f"{args.railway_environment!r}. There is no fallback target.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.apply and args.confirm != STAGING_APPLY_CONFIRMATION:
        print(
            "REFUSED: --apply requires --confirm with the exact phrase "
            f"{STAGING_APPLY_CONFIRMATION}. Nothing was connected to and nothing "
            "was written.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if not args.apply and args.confirm is not None:
        print(
            "REFUSED: --confirm was given without --apply. Re-run with neither "
            "for a dry run, or with both to write.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    root = (
        Path(args.snapshot_root)
        if args.snapshot_root
        else default_snapshot_root(REPO_ROOT, source_catalogue=SOURCE_CATALOGUE)
    )
    try:
        snapshot = load_snapshot(root, source_catalogue=SOURCE_CATALOGUE)
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

    # --- resolve and prove the target -------------------------------------
    try:
        verified = target_authority.verified_staging_target(
            environment=environment,
            service=args.railway_service,
            emit=emit,
        )
    except StagingTargetRefused as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"FAIL: could not resolve canonical staging: {exc}", file=sys.stderr)
        return EXIT_USAGE

    attestation = verified.attestation
    emit("== canonical staging Bandai catalogue import ==")
    for key, value in snapshot.describe().items():
        emit(f"  {key:<24} {value}")
    for key, value in attestation.describe().items():
        emit(f"  {key:<24} {value}")
    emit(f"  {'target':<24} {verified.redacted}")
    emit(f"  {'mode':<24} {'APPLY' if args.apply else 'dry-run (read-only session)'}")
    emit("")

    # Engine construction is INSIDE the guard on purpose: parsing the DSN is
    # the single most likely place for an exception to be handed the URL, so
    # it must not sit outside the handler that scrubs one.
    engine = None
    try:
        engine = _session_factory(verified.url, read_only=not args.apply)
        with Session(engine) as session:
            plan = plan_entries(
                session,
                snapshot.entries,
                series_index=snapshot.series,
                source_catalogue=SOURCE_CATALOGUE,
                digest_provider=snapshot.digest_provider(),
                classify_mappings=False,
            )
            pinning = ApplyPinning(
                snapshot_identity=snapshot.identity,
                source_catalogue=SOURCE_CATALOGUE,
                # Bound to the revision the target ATTESTED at, not to whatever
                # the session happens to report later.
                expected_db_revision=attestation.db_revision,
                expected_pre_counts=expected_counts,
                expected_snapshot_identity=args.expect_snapshot,
            )
            grant = (
                grant_canonical_staging_write(
                    confirmation=args.confirm or "", attestation=attestation
                )
                if args.apply
                else None
            )
            applier = CanonicalImportApplier(
                session,
                plan,
                pinning=pinning,
                environment=CANONICAL_STAGING_ENVIRONMENT,
                entries={entry.entry_id: entry for entry in snapshot.entries},
                staging_grant=grant,
            )
            try:
                report = applier.run(apply=args.apply)
            except ApplyRunFailed as exc:
                print(json.dumps(exc.report.to_dict(), indent=2, ensure_ascii=False))
                print(
                    f"\nROLLED BACK: {exc.report.rollback_reason} - "
                    f"{exc.report.rollback_detail}",
                    file=sys.stderr,
                )
                return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 - see below
        # Nothing below the tunnel is allowed to fail loudly with a raw
        # message. A driver or SQLAlchemy error is the one thing in this
        # process that has ever been handed the DSN, so both the summary and
        # the traceback are scrubbed rather than trusted. The traceback is
        # still printed: containment must not cost the operator the ability to
        # see what broke.
        print(
            f"FAIL: the canonical staging import raised {type(exc).__name__}: "
            + scrub_credentials(str(exc)),
            file=sys.stderr,
        )
        print(scrub_credentials(traceback.format_exc()), file=sys.stderr)
        return EXIT_FAILED
    finally:
        # The tunnel is closed whether the run committed, refused or raised -
        # including when the engine itself never got built.
        verified.close()
        if engine is not None:
            engine.dispose()

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if not args.json:
        print(
            "\nOK: "
            + (
                "applied to canonical staging"
                if report.applied
                else "dry run complete, nothing written"
            )
        )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
