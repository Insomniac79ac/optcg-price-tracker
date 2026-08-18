"""Record verified Yuyu-Tei display evidence, in the v2 evidence contract.

The write half of the Yuyu-Tei display-image migration. One additive
`display_image` block, written onto the *Yuyu-Tei* mapping for a print, only
after that print's mirrored R2 object has been re-verified end to end in the
same run (see app.persist_yuyutei_display_evidence).

Why a separate module from app.services.display_image_asset_persist: that one
records an `owned_asset` onto a mapping whose `display_image` was already
written by the 2026-08-13 SNKRDUNK tranche. Here there is no prior evidence at
all - the Yuyu-Tei mappings carry `match_explanation_json IS NULL` - so this
module writes the whole block, `owned_asset` included, in one guarded
assignment. Keeping the two apart means the SNKRDUNK write path is not
touched, and cannot be touched, by this migration.

The v2 evidence contract
------------------------
v1 (SNKRDUNK, 2026-08-13) asserted an image was free of *any* overlay. The
approved MVP display policy relaxes that for a retailer watermark, so v2 makes
the watermark an explicit, recorded fact rather than an omission:

  * ``retailer_overlay_present: true`` - the Yuyu-Tei watermark IS on this
    image. It is never described as absent.
  * ``overlay_obscures_card: false`` - and it does not *materially obscure*
    the collectible card content, which is the property the display contract
    actually turns on.

Those two fields together are the whole semantic difference, and both are
required on v2 evidence. Historical v1 evidence is not reinterpreted, not
rewritten, and keeps qualifying under its own terms - see
app.services.display_image._qualifies.

Geometry for a card-only asset
------------------------------
A Yuyu-Tei product image is the card itself: no canvas, no alpha, no padding.
So the card box is the whole frame, and `card_bbox_source` records that this
box was *not* measured from an alpha channel the way SNKRDUNK's was. Nothing
here invents canvas padding to imitate the SNKRDUNK asset shape.

What is stored, and what is deliberately not
--------------------------------------------
Not stored: any delivery hostname. `owned_asset` holds object identity only,
exactly as app.services.display_image_asset_persist does, because the public
URL is `R2_PUBLIC_BASE_URL + object_key` computed at read time.

Idempotency is by content. A record that already matches what was verified is
left exactly as it is, `verified_at` included; re-running must not rewrite a
row that nothing about the asset has changed. A record that *conflicts* is a
hard failure for that print and is never overwritten.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import SourceCardMapping

DISPLAY_IMAGE_KEY = "display_image"
OWNED_ASSET_KEY = "owned_asset"

SOURCE = "yuyutei"

VERIFICATION_VERSION = "display-image-v2"

# Same three-way proof the SNKRDUNK owned assets carry: the source bytes, the
# authenticated R2 GET and the unauthenticated public GET, all hashed and
# compared. Kept identical on purpose - app.services.display_image only trusts
# this exact string.
OWNED_ASSET_PROVIDER = "cloudflare_r2"
OWNED_ASSET_VERIFICATION_METHOD = "source_private_public_sha256"

VERIFICATION_METHOD = "offline_image_comparison_vs_bandai_canonical"

# The card box is the whole asset, and was not derived from an alpha channel.
# Recorded so no later reader mistakes a full-frame box for a measured one.
CARD_BBOX_SOURCE = "full_frame_card_only_asset"

# Why `overlay_obscures_card` is false on an image that demonstrably carries a
# watermark. Persisted as evidence so the record explains itself without
# anyone having to find the approval it came from.
OVERLAY_POLICY_NOTE = (
    "The Yuyu-Tei retailer watermark is present on this image and is accepted "
    "under the approved MVP public display policy: it does not materially "
    "obscure the collectible card content (artwork, card name, code, rarity "
    "and frame all remain legible), so overlay_obscures_card is false. The "
    "watermark is never described as absent - see retailer_overlay_present."
)

EVIDENCE_PROVENANCE = (
    "Exact-print candidate re-derived from retained raw_snapshots HTML only "
    "(JSON-LD Product.image, img.vimg and flontImage in agreement); original "
    "asset fetched once, mirrored to R2 byte-for-byte, and re-verified "
    "source == private == public. No image processing of any kind was applied."
)

# Everything except the two timestamps. Two records agreeing on all of these
# describe the same verified asset, so the stored record is left alone.
IDENTITY_FIELDS = (
    "url",
    "source",
    "card_print_id",
    "classification",
    "exact_print_verified",
    "full_card_preserved",
    "sample_present",
    "overlay_obscures_card",
    "retailer_overlay_present",
    "verification_version",
    "verification_method",
    "fetch",
    "geometry",
    "owned_asset",
)

# Excluded from the owned_asset comparison for the same reason.
OWNED_ASSET_VOLATILE_FIELDS = ("verified_at",)


@dataclass(frozen=True)
class VerifiedYuyuteiAsset:
    """One print's verified, already-mirrored Yuyu-Tei asset.

    Every field here was checked against something before this object was
    built: the digest against all three reads, byte size against all three,
    width/height against the decode of the *public* bytes, and content
    type/cache control against what R2 reported on HEAD.
    """

    card_print_id: int
    mapping_id: int
    source_url: str
    sha256: str
    byte_size: int
    width: int
    height: int
    content_type: str
    cache_control: str
    object_key: str


@dataclass
class PersistOutcome:
    """What the write phase did. Exactly one of `written`,
    `already_recorded`, or `abort_reason` is set at a time."""

    card_print_id: int | None = None
    mapping_id: int | None = None
    written: bool = False
    already_recorded: bool = False
    display_image: dict | None = None
    abort_reason: str | None = None
    conflicts: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.abort_reason is None and (self.written or self.already_recorded)


def build_owned_asset(asset: VerifiedYuyuteiAsset, verified_at: str) -> dict:
    """The owned-asset record: object identity and nothing else.

    No URL and no hostname - see the module docstring. The field set and the
    two constant values are exactly what app.services.display_image requires
    before it will serve our own copy in place of the source.
    """
    return {
        "provider": OWNED_ASSET_PROVIDER,
        "object_key": asset.object_key,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
        "content_type": asset.content_type,
        "cache_control": asset.cache_control,
        "verified_at": verified_at,
        "verification_method": OWNED_ASSET_VERIFICATION_METHOD,
    }


def build_geometry(asset: VerifiedYuyuteiAsset) -> dict:
    """Full-frame geometry for a card-only asset.

    `card_bbox_px` is inclusive `[left, top, right, bottom]`, matching the v1
    convention that app.services.display_image._geometry converts to x/y/w/h
    by adding one pixel per span. The card is the whole asset, so the box is
    the whole asset - not padding invented to imitate a canvas.
    """
    return {
        "canvas_px": [asset.width, asset.height],
        "card_px": [asset.width, asset.height],
        "card_bbox_px": [0, 0, asset.width - 1, asset.height - 1],
        "card_bbox_source": CARD_BBOX_SOURCE,
    }


def build_display_image(asset: VerifiedYuyuteiAsset, verified_at: str) -> dict:
    """The complete v2 display_image block for one print."""
    return {
        "url": asset.source_url,
        "source": SOURCE,
        "card_print_id": asset.card_print_id,
        "classification": "VERIFIED_DISPLAY",
        "exact_print_verified": True,
        "full_card_preserved": True,
        "sample_present": False,
        # Present, and recorded as present. See OVERLAY_POLICY_NOTE.
        "retailer_overlay_present": True,
        "overlay_obscures_card": False,
        "overlay_policy": OVERLAY_POLICY_NOTE,
        "verification_version": VERIFICATION_VERSION,
        "verification_method": VERIFICATION_METHOD,
        "verified_at": verified_at,
        "evidence_provenance": EVIDENCE_PROVENANCE,
        "fetch": {
            "bytes": asset.byte_size,
            "sha256": asset.sha256,
            "content_type": asset.content_type,
        },
        "geometry": build_geometry(asset),
        OWNED_ASSET_KEY: build_owned_asset(asset, verified_at),
    }


def _owned_asset_identity(record: object) -> dict:
    """An owned_asset with its volatile fields dropped, for comparison."""
    if not isinstance(record, dict):
        return {}
    return {k: v for k, v in record.items() if k not in OWNED_ASSET_VOLATILE_FIELDS}


def conflicts(existing: dict, candidate: dict) -> list[str]:
    """Which identity fields disagree. Timestamps are excluded by design."""
    differing: list[str] = []
    for name in IDENTITY_FIELDS:
        if name == OWNED_ASSET_KEY:
            if _owned_asset_identity(existing.get(name)) != _owned_asset_identity(
                candidate.get(name)
            ):
                differing.append(name)
            continue
        if existing.get(name) != candidate.get(name):
            differing.append(name)
    return differing


def persist_display_image(
    db: Session, asset: VerifiedYuyuteiAsset, now: datetime | None = None
) -> PersistOutcome:
    """Write `display_image` onto `asset.mapping_id`, additively and once.

    One short transaction: re-read the mapping, compare, then either write a
    whole new `match_explanation_json` value or leave the row untouched.

    The JSON is never mutated in place. SQLAlchemy tracks a plain `dict`
    column by identity, so mutating the loaded object and committing emits no
    UPDATE at all - the write silently does nothing. Deep-copying, editing the
    copy and assigning the whole value is what makes the change visible to the
    session, and it also means a conflict check can compare against the
    unmodified original.
    """
    outcome = PersistOutcome(card_print_id=asset.card_print_id, mapping_id=asset.mapping_id)
    verified_at = (now or datetime.now(timezone.utc)).isoformat()
    candidate = build_display_image(asset, verified_at)

    mapping = db.get(SourceCardMapping, asset.mapping_id)
    if mapping is None:
        outcome.abort_reason = f"mapping {asset.mapping_id} does not exist"
        return outcome
    if mapping.card_print_id != asset.card_print_id:
        outcome.abort_reason = (
            f"mapping {asset.mapping_id} points at card_print "
            f"{mapping.card_print_id}, not {asset.card_print_id}"
        )
        return outcome

    explanation = copy.deepcopy(mapping.match_explanation_json) or {}
    if not isinstance(explanation, dict):
        outcome.abort_reason = (
            f"mapping {asset.mapping_id} match_explanation_json is "
            f"{type(explanation).__name__}, not an object"
        )
        return outcome

    existing = explanation.get(DISPLAY_IMAGE_KEY)
    if existing is not None:
        if not isinstance(existing, dict):
            outcome.abort_reason = (
                f"mapping {asset.mapping_id} display_image is "
                f"{type(existing).__name__}, not an object"
            )
            return outcome
        differing = conflicts(existing, candidate)
        if differing:
            # Never overwritten. A disagreement about a content-addressed
            # asset means something is wrong, not that the record is stale.
            outcome.abort_reason = (
                f"mapping {asset.mapping_id} already has conflicting Yuyu-Tei "
                f"display evidence: {', '.join(differing)}"
            )
            outcome.conflicts = tuple(differing)
            return outcome
        outcome.already_recorded = True
        outcome.display_image = existing
        return outcome

    explanation[DISPLAY_IMAGE_KEY] = candidate
    mapping.match_explanation_json = explanation
    db.commit()

    outcome.written = True
    outcome.display_image = candidate
    return outcome
