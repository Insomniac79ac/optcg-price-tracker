"""Record verified official Card List display evidence, in the v3 contract.

The write half of the official-image migration (2026-08-18). One additive
`display_image` block per print, on a mapping owned by the *official* source,
only after that print's mirrored R2 object has been re-verified end to end in
the same run (see app.persist_official_display_evidence).

The source identifier is ``bandai``
------------------------------------
Deliberately not a new name. ``app.services.display_image.BANDAI`` has always
been "bandai", the public API has always reported that string for the
canonical card-list image, and the frontend already maps it to a human label.
onepiece-cardgame.com *is* that source - the 2026-08-18 audit proved the Card
List assets are byte-identical to the canonical images we already store, with
SHA-256 equal to ``card_prints.artwork_key`` on all twenty. Inventing
"official_cardlist" beside "bandai" would give one source two identifiers and
force every reader to know both.

Why this source needs mapping rows
----------------------------------
Display evidence lives on ``source_card_mappings.match_explanation_json``, and
until now the official source had no rows there - it was only ever the
fallback, read straight off ``card_prints.image_url``. So this migration
creates one ``sources`` row and one mapping per print. Those mappings carry no
prices and never will: ``source_coverage`` and the Market Index are derived
from ``price_observations`` (rows with an ``observed_at``), so a source with
zero observations cannot appear as a market source or move a price.

The v3 evidence contract
------------------------
v1 (SNKRDUNK) asserted an image free of every overlay. v2 (Yuyu-Tei) allowed a
retailer watermark, recorded explicitly. v3 allows the official SAMPLE mark,
and again records it rather than hiding it:

  * ``sample_present: true`` - the SAMPLE overlay IS on this image. It is
    never described as absent, and no attempt is made to remove, crop or mask
    it.
  * ``overlay_obscures_card: false`` - it does not obscure the card's
    identity: artwork, name, code, rarity and frame all stay legible.
  * ``overlay_policy: "official_sample_accepted"`` - the marker that licenses
    a true ``sample_present``. Without it, ``sample_present: true`` still
    fails qualification, so an image cannot acquire an accepted SAMPLE by
    accident.

Those three fields are what let a future reader tell "clean official image"
apart from "official image carrying an accepted SAMPLE overlay". Existing
field names are reused rather than adding parallel ones (`sample_present`
rather than a second `sample_overlay_present`, `overlay_obscures_card` rather
than a second `overlay_obscures_identity`), so there is exactly one place each
fact is recorded.

Geometry, idempotency and conflict handling follow
app.services.yuyutei_display_evidence exactly; the only difference is that the
official assets are 600x838 rather than 500x700, and the dimensions are taken
from the asset rather than assumed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Source, SourceCardMapping

DISPLAY_IMAGE_KEY = "display_image"
OWNED_ASSET_KEY = "owned_asset"

# The identifier the codebase already uses for onepiece-cardgame.com.
SOURCE = "bandai"
SOURCE_BASE_URL = "https://www.onepiece-cardgame.com"

VERIFICATION_VERSION = "display-image-v3"

# The marker that licenses `sample_present: true`. Qualification requires it,
# so a SAMPLE can never be accepted implicitly.
OVERLAY_POLICY = "official_sample_accepted"

OWNED_ASSET_PROVIDER = "cloudflare_r2"
OWNED_ASSET_VERIFICATION_METHOD = "source_private_public_sha256"

VERIFICATION_METHOD = "first_party_digest_equals_artwork_key"

CARD_BBOX_SOURCE = "full_frame_card_only_asset"

OVERLAY_POLICY_NOTE = (
    "This is the first-party ONE PIECE Card List asset for this exact "
    "printing. It carries the official SAMPLE overlay, which is present and "
    "recorded as present, and is accepted under the approved MVP public "
    "display policy: it does not obscure the card's identity (artwork, card "
    "name, code, rarity and frame all remain legible). The overlay is never "
    "removed, cropped, masked or otherwise altered."
)

EVIDENCE_PROVENANCE = (
    "Exact printing established by first-party digest identity: the SHA-256 "
    "of the official Card List asset equals card_prints.artwork_key for this "
    "print. Variant identity taken from the official card list entry id, not "
    "from the card code or a filename suffix rule. Original bytes mirrored to "
    "R2 and re-verified source == private == public. No image processing of "
    "any kind was applied."
)

IDENTITY_FIELDS = (
    "url",
    "source",
    "card_print_id",
    # Which official printing this is. Two records disagreeing here describe
    # different variants of the same card code, which is exactly the mistake
    # this migration exists to avoid - so it is an identity field, not detail.
    "variant_id",
    "classification",
    "exact_print_verified",
    "full_card_preserved",
    "sample_present",
    "overlay_obscures_card",
    "overlay_policy",
    "verification_version",
    "verification_method",
    "fetch",
    "geometry",
    "owned_asset",
)

OWNED_ASSET_VOLATILE_FIELDS = ("verified_at",)


@dataclass(frozen=True)
class VerifiedOfficialAsset:
    """One print's verified, already-mirrored official Card List asset."""

    card_print_id: int
    variant_id: str
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
    card_print_id: int | None = None
    mapping_id: int | None = None
    mapping_created: bool = False
    written: bool = False
    already_recorded: bool = False
    display_image: dict | None = None
    abort_reason: str | None = None
    conflicts: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.abort_reason is None and (self.written or self.already_recorded)


def build_owned_asset(asset: VerifiedOfficialAsset, verified_at: str) -> dict:
    """Object identity only - no URL, no hostname. The delivery origin comes
    from R2_PUBLIC_BASE_URL at read time."""
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


def build_geometry(asset: VerifiedOfficialAsset) -> dict:
    """Full-frame geometry taken from the asset's real dimensions.

    The official assets are card-only and full-bleed, so the card box is the
    whole frame. Dimensions are read from the asset, never assumed - these are
    600x838, deliberately not forced into the 500x700 Yuyu-Tei shape.
    """
    return {
        "canvas_px": [asset.width, asset.height],
        "card_px": [asset.width, asset.height],
        "card_bbox_px": [0, 0, asset.width - 1, asset.height - 1],
        "card_bbox_source": CARD_BBOX_SOURCE,
    }


def build_display_image(asset: VerifiedOfficialAsset, verified_at: str) -> dict:
    return {
        "url": asset.source_url,
        "source": SOURCE,
        "card_print_id": asset.card_print_id,
        "variant_id": asset.variant_id,
        "classification": "VERIFIED_DISPLAY",
        "exact_print_verified": True,
        "full_card_preserved": True,
        # Present, and recorded as present. See OVERLAY_POLICY_NOTE.
        "sample_present": True,
        "retailer_overlay_present": False,
        "overlay_obscures_card": False,
        "overlay_policy": OVERLAY_POLICY,
        "overlay_policy_note": OVERLAY_POLICY_NOTE,
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
    if not isinstance(record, dict):
        return {}
    return {k: v for k, v in record.items() if k not in OWNED_ASSET_VOLATILE_FIELDS}


def conflicts(existing: dict, candidate: dict) -> list[str]:
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


def get_or_create_source(db: Session) -> Source:
    """The official source row, created once. Carries no prices, ever."""
    source = db.execute(select(Source).where(Source.name == SOURCE)).scalar_one_or_none()
    if source is not None:
        return source
    source = Source(name=SOURCE, base_url=SOURCE_BASE_URL)
    db.add(source)
    db.flush()
    return source


def _existing_mapping(
    db: Session, source_id: int, asset: "VerifiedOfficialAsset"
) -> SourceCardMapping | None:
    """This source's mapping for the print, or for the same source URL.

    Matching on the URL as well as the print matters: (source_id, source_url)
    is unique, so a row already holding this asset's URL must be found and
    validated rather than stepped over - stepping over it would either create
    a duplicate the database rejects, or silently record this print's evidence
    while an existing row still claims the URL for a different print.
    """
    return (
        db.execute(
            select(SourceCardMapping)
            .where(
                SourceCardMapping.source_id == source_id,
                or_(
                    SourceCardMapping.card_print_id == asset.card_print_id,
                    SourceCardMapping.source_url == asset.source_url,
                ),
            )
            .order_by(SourceCardMapping.id.asc())
        )
        .scalars()
        .first()
    )


def persist_display_image(
    db: Session,
    asset: VerifiedOfficialAsset,
    card_id: int,
    now: datetime | None = None,
) -> PersistOutcome:
    """Write `display_image` for one print on the official source's mapping.

    Creates the mapping the first time (the official source has never had one
    - it was only ever the fallback read off card_prints.image_url) and then
    behaves exactly like the Yuyu-Tei writer: add when absent, no-op when
    identical, hard-fail on conflict, never overwrite.

    The JSON is never mutated in place. SQLAlchemy tracks a plain dict column
    by identity, so mutating the loaded object emits no UPDATE at all.
    """
    outcome = PersistOutcome(card_print_id=asset.card_print_id)
    verified_at = (now or datetime.now(timezone.utc)).isoformat()
    candidate = build_display_image(asset, verified_at)

    source = get_or_create_source(db)
    mapping = _existing_mapping(db, source.id, asset)

    if mapping is None:
        mapping = SourceCardMapping(
            card_id=card_id,
            source_id=source.id,
            card_print_id=asset.card_print_id,
            source_card_id=asset.variant_id,
            source_url=asset.source_url,
            review_status="approved",
            manual_verified=True,
            is_active=True,
            match_explanation_json={DISPLAY_IMAGE_KEY: candidate},
        )
        db.add(mapping)
        db.commit()
        outcome.mapping_id = mapping.id
        outcome.mapping_created = True
        outcome.written = True
        outcome.display_image = candidate
        return outcome

    outcome.mapping_id = mapping.id
    if mapping.card_print_id != asset.card_print_id:
        outcome.abort_reason = (
            f"mapping {mapping.id} points at card_print {mapping.card_print_id}, "
            f"not {asset.card_print_id}"
        )
        return outcome

    explanation = copy.deepcopy(mapping.match_explanation_json) or {}
    if not isinstance(explanation, dict):
        outcome.abort_reason = f"mapping {mapping.id} match_explanation_json is not an object"
        return outcome

    existing = explanation.get(DISPLAY_IMAGE_KEY)
    if existing is not None:
        if not isinstance(existing, dict):
            outcome.abort_reason = f"mapping {mapping.id} display_image is not an object"
            return outcome
        differing = conflicts(existing, candidate)
        if differing:
            outcome.abort_reason = (
                f"mapping {mapping.id} already has conflicting official display "
                f"evidence: {', '.join(differing)}"
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
