"""Record that a verified display image is now owned by us, in R2.

One additive block, `display_image.owned_asset`, written onto one mapping,
only after that mapping's asset has been re-verified end to end in the same
run. Nothing else in the evidence is touched and nothing outside
match_explanation_json is written at all.

Why this is a separate module from app.services.display_image_upload: the
uploader is asserted - by a token-level test over its own source - to contain
no commit, no flush and no reference to match_explanation_json. That
guarantee is worth more than the convenience of one file, so the only code in
this repository that can write an owned_asset lives here, in about a hundred
lines that do nothing else.

What is stored, and what is deliberately not
--------------------------------------------
Stored: provider, the content-addressed object key, the full SHA-256, byte
size, decoded width/height, the content type and cache policy the object
actually carries, and when and how it was verified.

Not stored: **any URL**. The r2.dev hostname is environment configuration -
it differs between environments, and it will be replaced by a custom domain -
so persisting it would bake a deployment detail into evidence and create a
second, staler source of truth next to R2_PUBLIC_BASE_URL. The delivery URL
is `R2_PUBLIC_BASE_URL + object_key`, computed at read time by
R2ObjectStorage.public_url(), and that is the only place it should ever come
from.

Also not stored: the source URL. It already lives in `display_image.url` with
its fetch provenance beside it; copying it here would give the record two
places to disagree with itself.

Ordering, and the guard
-----------------------
All network work - the source fetch, the R2 HEAD/GET, the public GET, the
decode - happens in the mirror phase, before this function is called and
before any transaction is opened. This function then runs one short
transaction that re-reads the mapping and re-checks its evidence against what
was verified. Any drift aborts and rolls back rather than writing a record
about bytes nobody checked.

Idempotency is by content: an owned_asset that already matches what was just
verified is left exactly as it is, `verified_at` included. Refreshing that
timestamp on every run would turn a fact ("these bytes were proven to be in
R2 at this moment") into a heartbeat, and would rewrite a row that nothing
about the asset had changed. An owned_asset that *conflicts* is a hard
failure and is never overwritten: under a content-addressed key, a
disagreement means something is wrong, not stale.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import SourceCardMapping
from app.services.display_image_mirror import collect_candidates
from app.services.display_image_upload import MirrorOutcome

OWNED_ASSET_KEY = "owned_asset"

PROVIDER = "cloudflare_r2"

# Names the three independent reads that had to agree for this record to be
# written: the source fetch, the authenticated R2 GET and the unauthenticated
# public GET, all hashed and compared against the stored evidence digest.
VERIFICATION_METHOD = "source_private_public_sha256"

# Everything except `verified_at`. Two records that agree on all of these
# describe the same object, so the older timestamp is kept and nothing is
# rewritten.
IDENTITY_FIELDS = (
    "provider",
    "object_key",
    "sha256",
    "byte_size",
    "width",
    "height",
    "content_type",
    "cache_control",
    "verification_method",
)


@dataclass
class PersistOutcome:
    """What the write phase did. Exactly one of these is true at a time:
    `written`, `already_recorded`, or `abort_reason` set."""

    mapping_id: int | None = None
    written: bool = False
    already_recorded: bool = False
    owned_asset: dict | None = None
    abort_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.abort_reason is None and (self.written or self.already_recorded)


def build_owned_asset(outcome: MirrorOutcome, verified_at: str) -> dict:
    """The record, built only from values the mirror phase actually proved.

    Every field here was compared against something during mirroring:
    `sha256` against the stored evidence digest and both read-backs,
    `byte_size` against all three reads, `width`/`height` against the decode
    of the *public* bytes, and `content_type`/`cache_control` against what R2
    reported on HEAD rather than what was sent to it.
    """
    width, height = outcome.public_dimensions
    return {
        "provider": PROVIDER,
        "object_key": outcome.object_key,
        "sha256": outcome.stored_sha256,
        "byte_size": outcome.source_byte_length,
        "width": width,
        "height": height,
        "content_type": outcome.head_content_type,
        "cache_control": outcome.head_cache_control,
        "verified_at": verified_at,
        "verification_method": VERIFICATION_METHOD,
    }


def _conflicts(existing: dict, candidate: dict) -> list[str]:
    """Which identity fields disagree. `verified_at` is excluded by design."""
    return [
        name
        for name in IDENTITY_FIELDS
        if existing.get(name) != candidate.get(name)
    ]


def persist_owned_asset(
    db: Session, outcome: MirrorOutcome, now: datetime | None = None
) -> PersistOutcome:
    """Write `display_image.owned_asset` for the mapping `outcome` verified.

    Precondition: `outcome.ok`. A mirror run that failed at any stage - or
    that never ran - cannot produce a record here, because every value in the
    record comes from a check that stage performed.
    """
    result = PersistOutcome(mapping_id=outcome.mapping_id)

    if not outcome.ok:
        result.abort_reason = (
            f"mirror verification did not pass (failed at stage "
            f"{outcome.failed_stage!r}) - nothing persisted"
        )
        return result

    verified = outcome.verification.evidence

    # End the read transaction the mirror phase held open, so the re-read
    # below sees the latest committed state and not an older snapshot.
    db.rollback()

    fresh_candidates, _ = collect_candidates(db, card_print_ids=[verified.card_print_id])
    fresh = next(
        (e for e in fresh_candidates if e.mapping_id == verified.mapping_id),
        None,
    )
    if fresh is None:
        result.abort_reason = (
            f"mapping {verified.mapping_id} is no longer an eligible display-image "
            "asset - it changed between verification and write"
        )
        db.rollback()
        return result
    if fresh.write_fingerprint != verified.write_fingerprint:
        result.abort_reason = (
            f"mapping {verified.mapping_id} evidence changed between verification and "
            "write - stale verification, nothing persisted"
        )
        db.rollback()
        return result
    if fresh.existing_sha256 != verified.existing_sha256:
        # Not part of write_fingerprint (see persist_bootstrap_digests), but
        # it is the digest this whole record is keyed on, so it is checked.
        result.abort_reason = (
            f"mapping {verified.mapping_id} stored fetch.sha256 changed between "
            "verification and write - nothing persisted"
        )
        db.rollback()
        return result

    mapping = db.get(SourceCardMapping, verified.mapping_id)
    if mapping is None:  # pragma: no cover - collect_candidates just read it
        result.abort_reason = f"mapping {verified.mapping_id} disappeared before write"
        db.rollback()
        return result

    verified_at = (now or datetime.now(timezone.utc)).isoformat()
    candidate = build_owned_asset(outcome, verified_at)
    result.owned_asset = candidate

    existing = (mapping.match_explanation_json or {}).get("display_image", {}).get(
        OWNED_ASSET_KEY
    )
    if existing is not None:
        if not isinstance(existing, dict):
            result.abort_reason = (
                f"mapping {verified.mapping_id} already carries a non-object "
                f"{OWNED_ASSET_KEY} - refusing to overwrite"
            )
            db.rollback()
            return result
        differing = _conflicts(existing, candidate)
        if differing:
            result.abort_reason = (
                f"mapping {verified.mapping_id} already carries an {OWNED_ASSET_KEY} that "
                f"disagrees on {differing} - refusing to overwrite; investigate before "
                "recording anything"
            )
            db.rollback()
            return result
        # Identical: keep the original record, timestamp included.
        result.already_recorded = True
        result.owned_asset = existing
        db.rollback()
        return result

    # Copy first, mutate the copy, assign the whole object. The column is a
    # plain JSON type with no MutableDict wrapper, so an in-place edit is not
    # tracked - and an in-place edit *followed* by assigning a copy is worse
    # still: the committed value is that same mutated dict, old == new at
    # flush time, and the UPDATE is silently skipped.
    explanation = copy.deepcopy(mapping.match_explanation_json)
    explanation["display_image"][OWNED_ASSET_KEY] = candidate
    mapping.match_explanation_json = explanation

    db.commit()
    result.written = True
    return result
