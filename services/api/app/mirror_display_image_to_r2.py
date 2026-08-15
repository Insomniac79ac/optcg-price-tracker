"""CLI: mirror ONE verified display image to R2 and verify it end to end.

    python -m app.mirror_display_image_to_r2 --print-id 1
    python -m app.mirror_display_image_to_r2 --print-id 1 --persist-owned-asset

Deliberately one print per invocation. There is no --all, and --print-id is
not repeatable: the first tranche that writes a real card asset to object
storage should be impossible to point at the whole catalogue by habit or by
typo. Widening this is a later decision, made once the single-asset path has
been proven in production.

What one run does, in order, stopping at the first failure:

    verify   the existing display_image_mirror verifier, unchanged
    digest   stored fetch.sha256 == digest of the bytes fetched just now
    key      display-images/sha256/<ab>/<64 hex>.webp, derived from that digest
    head     does the object already exist?
    upload   PUT the exact verified bytes, only if it does not
    private  authenticated GET + HEAD: bytes, digest, length, type, cache
    public   unauthenticated GET over R2_PUBLIC_BASE_URL: bytes, digest, and
             the decoded natural size the frontend geometry guard depends on
    db       the session holds nothing pending

With --persist-owned-asset, and only if all eight stages passed, one further
short transaction re-reads the mapping, re-checks its evidence against what
was just verified, and adds an additive display_image.owned_asset block
recording the object key, digest, size, dimensions and cache policy. No URL
is stored - the delivery host comes from R2_PUBLIC_BASE_URL at read time.
Without the flag nothing is written to the database at all; persistence is
never the default and never implied.

Writes at most two things: one object, at a key that is the SHA-256 of its
own contents and only when that key is empty, and - when asked - one additive
evidence key on one mapping row. An object already at the key is never
overwritten, and neither is an existing owned_asset: an identical one is left
alone (timestamp included) and a conflicting one is a hard failure. Nothing
else is written. No image_url or artwork_key change, no migration, and
GET /prints, the frontend and the collectors are untouched - the public
response has no owned_asset field to leak into. Mirrored bytes are not yet
visible to anybody; making them visible is a separate tranche.

Exit codes:

    0  every stage passed
    1  a stage failed (the failing stage is named)
    2  R2 is not configured in this environment
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.check_r2_connectivity import scrub
from app.db import SessionLocal
from app.services.display_image_upload import (
    CACHE_CONTROL,
    CONTENT_TYPE,
    MirrorOutcome,
    mirror_print,
)
from app.services.display_image_asset_persist import (
    PersistOutcome,
    persist_owned_asset,
)
from app.services.object_storage import R2ConfigurationError, R2ObjectStorage
from app.settings import settings

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2


def emit(line: str = "") -> None:
    print(scrub(line))


def _database_target() -> str:
    """The database this run reads from, with the password removed."""
    try:
        return make_url(settings.DATABASE_URL).render_as_string(hide_password=True)
    except Exception:  # pragma: no cover - never let reporting break the run
        return "<unparseable DATABASE_URL>"


def print_banner(card_print_id: int, storage: R2ObjectStorage, persist: bool) -> None:
    emit("Display-image mirror to R2 - single asset")
    emit(f"  card_print_id : {card_print_id}")
    emit(f"  bucket        : {storage.bucket_name}")
    emit(f"  database      : {_database_target()} (read-only)")
    emit(f"  object policy : ContentType={CONTENT_TYPE}, CacheControl={CACHE_CONTROL}")
    emit("  write policy  : PUT only when the key is empty; never overwrite, never delete")
    emit(f"  db write      : {'display_image.owned_asset (additive, one mapping)' if persist else 'none - verification only'}")
    emit()


def print_outcome(outcome: MirrorOutcome, persisting: bool = False) -> None:
    verification = outcome.verification
    evidence = verification.evidence if verification else None

    emit(f"  mapping id    : {outcome.mapping_id}")
    emit(f"  source        : {evidence.source if evidence else '-'}")
    emit(f"  source url    : {outcome.source_url or '-'}")
    emit(f"  source bytes  : {outcome.source_byte_length}")
    emit(f"  stored sha256 : {outcome.stored_sha256 or '- (not bootstrapped)'}")
    emit(f"  fetched sha256: {outcome.computed_sha256 or '-'}")
    emit(f"  object key    : {outcome.object_key or '-'}")
    emit(f"  public url    : {outcome.public_url or '-'}")
    emit()
    for stage in outcome.stages:
        emit(f"  [{'OK' if stage.ok else 'FAIL'}] {stage.name:<8}{stage.detail}")
    emit()
    if outcome.uploaded is not None:
        emit(f"  action        : {'UPLOADED (key was empty)' if outcome.uploaded else 'ALREADY PRESENT (not overwritten)'}")
    emit(f"  private GET   : {outcome.private_byte_length} bytes  sha256={outcome.private_sha256}")
    emit(f"  public GET    : status={outcome.public_status} {outcome.public_byte_length} bytes  "
         f"sha256={outcome.public_sha256}")
    emit(f"  public decoded: {outcome.public_dimensions}  expected canvas_px={outcome.expected_canvas_px}")
    emit()
    if outcome.ok:
        emit(
            "[OK] source bytes == R2 bytes == public bytes, and the public asset decodes to "
            "the recorded canvas size."
        )
    else:
        emit(f"[FAIL] mirroring failed at stage: {outcome.failed_stage}")
    if persisting:
        emit(
            "the mirror phase itself wrote nothing to the database; any write happens "
            "below, in its own transaction, and touches one additive evidence key on one "
            "mapping."
        )
    else:
        emit(
            "no database row was created, updated or deleted: no owned_asset, no "
            "match_explanation_json edit, no image_url or artwork_key change."
        )
    emit(
        "GET /prints, the frontend and the collectors are unchanged, and no other print "
        "was processed."
    )


def print_persist_banner(outcome: MirrorOutcome) -> None:
    """The database write is the only thing here that changes durable state
    outside object storage, so it announces itself before it happens."""
    emit()
    emit("=" * 72)
    emit("  DATABASE WRITE - recording display_image.owned_asset")
    emit("=" * 72)
    emit(f"  target        : {_database_target()}")
    emit(f"  mapping       : {outcome.mapping_id} (card_print_id {outcome.card_print_id})")
    emit(f"  writing       : match_explanation_json.display_image.owned_asset")
    emit("  not touched   : display_image.url, fetch evidence, geometry, every other")
    emit("                  evidence key, card_prints.image_url, artwork_key, identity")
    emit("  no url stored : delivery host comes from R2_PUBLIC_BASE_URL at read time")
    emit("=" * 72)
    emit()


def print_persist_outcome(result: PersistOutcome) -> None:
    if not result.ok:
        emit(f"ABORTED: {result.abort_reason}")
        emit("transaction rolled back - no row was modified.")
        return
    if result.already_recorded:
        emit(f"owned_asset already recorded on mapping {result.mapping_id} and matches this "
             "run exactly - left untouched, verified_at not refreshed.")
    else:
        emit(f"owned_asset written to mapping {result.mapping_id}.")
    for name, value in (result.owned_asset or {}).items():
        emit(f"    {name:<21}: {value}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror one verified SNKRDUNK display image to R2 under its "
            "content-addressed key, then verify it byte-for-byte over both the "
            "authenticated S3 API and the public delivery origin. Writes at most one "
            "object and never touches the database."
        )
    )
    parser.add_argument(
        "--print-id",
        type=int,
        required=True,
        help="The single card_print_id to mirror. Not repeatable; there is no --all.",
    )
    parser.add_argument(
        "--persist-owned-asset",
        action="store_true",
        dest="persist",
        help=(
            "After every stage passes, additively record display_image.owned_asset on "
            "this mapping. Off by default: without it nothing is written to the database."
        ),
    )
    args = parser.parse_args(argv)

    try:
        storage = R2ObjectStorage.from_settings()
    except R2ConfigurationError as exc:
        emit(f"[FAIL] not configured: {scrub(str(exc))}")
        sys.exit(EXIT_NOT_CONFIGURED)

    print_banner(args.print_id, storage, args.persist)

    db: Session = SessionLocal()
    try:
        outcome = mirror_print(db, args.print_id, storage)
        print_outcome(outcome, persisting=args.persist)

        if not args.persist:
            sys.exit(EXIT_OK if outcome.ok else EXIT_FAILED)
        if not outcome.ok:
            emit("\nverification did not pass - nothing will be written to the database.")
            sys.exit(EXIT_FAILED)

        print_persist_banner(outcome)
        result = persist_owned_asset(db, outcome)
        print_persist_outcome(result)
        sys.exit(EXIT_OK if result.ok else EXIT_FAILED)
    finally:
        # Read-only by construction; rolled back regardless so no accidental
        # state could survive this process.
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
