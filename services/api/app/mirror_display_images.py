"""CLI: verify the approved SNKRDUNK display images against their retained
evidence, and - only when explicitly asked - persist the full SHA-256 that
verification computed.

Two mutually exclusive modes, both of which run the identical verification
first:

    python -m app.mirror_display_images --dry-run --all
    python -m app.mirror_display_images --dry-run --print-id 1 --print-id 2

        Read-only. Writes nothing to the database, nothing to disk, and talks
        to no object storage (none exists yet).

    python -m app.mirror_display_images --persist-bootstrap-sha256 --all
    python -m app.mirror_display_images --persist-bootstrap-sha256 --print-id 1

        Verifies exactly as above and then, only if every selected asset
        passed, writes `fetch.sha256`, `fetch.sha256_recorded_at` and
        `fetch.sha256_origin` additively into each asset's existing evidence.
        Nothing else is modified. One failure anywhere means no row is
        written at all.

Persistence is never the default and never implied: neither mode is assumed,
one of the two flags must be given. See
app.services.display_image_mirror for what a PASS does and does not prove, and
why the persisted digest is provenance-tagged as a bootstrap re-fetch rather
than as historical evidence.

Exit code is 0 only when every selected asset verified and, in persistence
mode, the write completed.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.settings import settings
from app.services.display_image_mirror import (
    EXPECTED_APPROVED_ASSET_COUNT,
    PASS_SEMANTICS,
    AssetVerification,
    PersistOutcome,
    VerificationReport,
    persist_bootstrap_digests,
    run_verification,
)


def _fmt_pair(expected: object, actual: object) -> str:
    """"expected -> actual", collapsed to one value when they agree."""
    return str(expected) if str(expected) == str(actual) else f"{expected} -> {actual}"


def _database_target() -> str:
    """The database this run would write to, with the password removed."""
    try:
        return make_url(settings.DATABASE_URL).render_as_string(hide_password=True)
    except Exception:  # pragma: no cover - never let reporting break the run
        return "<unparseable DATABASE_URL>"


def print_asset(verification: AssetVerification) -> None:
    evidence = verification.evidence
    fetch = verification.fetch
    inspection = verification.inspection

    print(
        f"[{verification.status}] print {evidence.card_print_id} "
        f"(mapping {evidence.mapping_id}, {evidence.source})"
    )
    if fetch is not None:
        print(
            f"    http           : {fetch.http_status} host={fetch.final_host} "
            f"redirected={fetch.redirected} content_type={fetch.raw_content_type!r} "
            f"media_type={fetch.media_type}"
        )
    print(
        f"    bytes          : {_fmt_pair(evidence.byte_length, verification.actual_bytes)}"
    )
    print(
        f"    sha256 prefix  : "
        f"{_fmt_pair(evidence.sha256_prefix, verification.sha256_prefix)}"
    )
    print(f"    sha256 (full)  : {verification.sha256 or '-'}")
    print(f"    stored sha256  : {evidence.existing_sha256 or '- (not bootstrapped yet)'}")
    canvas_expected = f"{evidence.canvas_px[0]}x{evidence.canvas_px[1]}"
    canvas_actual = f"{inspection.width}x{inspection.height}" if inspection else None
    print(f"    canvas         : {_fmt_pair(canvas_expected, canvas_actual)}")
    alpha_actual = inspection.alpha_bbox if inspection else None
    print(
        f"    alpha bbox     : {_fmt_pair(verification.expected_alpha_bbox, alpha_actual)}"
        f"  (stored inclusive {list(evidence.card_bbox_px)})"
    )
    print(f"    format         : {verification.image_format or '-'}")
    print(f"    object key     : {verification.proposed_object_key or '-'}")
    for failure in verification.failures:
        print(f"    FAILURE        : {failure}")


def print_report(report: VerificationReport, persisting: bool) -> None:
    for verification in report.verifications:
        print_asset(verification)
        print()

    if report.skipped:
        print("skipped mappings:")
        for skip in report.skipped:
            label = "quarantined" if skip.quarantined else "skipped"
            print(
                f"  mapping {skip.mapping_id} (print {skip.card_print_id}) "
                f"[{label}]: {skip.reason}"
            )
        print()

    print(f"selected            : {report.selected}")
    print(f"attempted           : {report.attempted}")
    print(f"passed              : {report.passed}")
    print(f"failed              : {report.failed}")
    print(f"quarantined skipped : {report.quarantined_skipped}")
    print(f"other skipped       : {report.other_skipped}")

    if report.population_drift:
        print(f"\nDRIFT: {report.population_drift}")

    print()
    if not persisting:
        print("nothing was written: no database write, no file, no object storage.")
    if report.passed:
        print(PASS_SEMANTICS)


def print_write_banner(report: VerificationReport) -> None:
    """Persistence is the only thing in this command that changes state, so it
    announces itself unmistakably before it happens."""
    to_write = sum(1 for v in report.verifications if v.evidence.existing_sha256 is None)
    already = report.selected - to_write
    print()
    print("=" * 72)
    print("  DATABASE WRITE - persisting bootstrap SHA-256 evidence")
    print("=" * 72)
    print(f"  target                : {_database_target()}")
    print(f"  verified assets       : {report.passed}/{report.selected} passed")
    print(f"  rows to update        : {to_write}")
    print(f"  already bootstrapped  : {already}")
    print("  writing               : display_image.fetch.sha256,")
    print("                          display_image.fetch.sha256_recorded_at,")
    print("                          display_image.fetch.sha256_origin")
    print("  not touched           : every other evidence key, all identity")
    print("                          columns, quarantined mappings, image bytes")
    print("=" * 72)
    print()


def print_persist_outcome(outcome: PersistOutcome) -> None:
    if not outcome.ok:
        print(f"ABORTED: {outcome.abort_reason}")
        print("transaction rolled back - no row was modified.")
        return

    print(f"updated             : {len(outcome.updated)} {outcome.updated}")
    print(
        f"already bootstrapped: {len(outcome.already_bootstrapped)} "
        f"{outcome.already_bootstrapped}"
    )
    print(f"sha256_recorded_at  : {outcome.recorded_at or '- (nothing to write)'}")
    print(
        "\nPersisted evidence is provenance-tagged sha256_origin='bootstrap_refetch': "
        "the full digest was established by this re-fetch, not retained from the "
        "historical fetch. fetch.fetched_at, fetch.bytes and fetch.sha256_prefix are "
        "unchanged."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify approved SNKRDUNK display images against their retained "
            "evidence, and optionally persist the full SHA-256 computed by that "
            "verification. Verification is read-only; persistence must be asked "
            "for explicitly."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify only. Nothing is written anywhere.",
    )
    mode.add_argument(
        "--persist-bootstrap-sha256",
        action="store_true",
        dest="persist",
        help=(
            "Verify, then write the full SHA-256 additively into each verified "
            "asset's display_image.fetch evidence. All-or-nothing."
        ),
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all", action="store_true", help="Every eligible display image."
    )
    scope.add_argument(
        "--print-id",
        type=int,
        action="append",
        dest="print_ids",
        help="Only this card_print_id (repeatable).",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        report = run_verification(
            db,
            card_print_ids=args.print_ids,
            # Population drift is only meaningful for a whole-catalogue run.
            expected_asset_count=EXPECTED_APPROVED_ASSET_COUNT if args.all else None,
        )
        print_report(report, persisting=args.persist)

        if not args.persist:
            sys.exit(0 if report.ok else 1)

        if not report.ok:
            print("\nverification did not pass - nothing will be written.")
            sys.exit(1)

        print_write_banner(report)
        outcome = persist_bootstrap_digests(db, report)
        print_persist_outcome(outcome)
        sys.exit(0 if outcome.ok else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
