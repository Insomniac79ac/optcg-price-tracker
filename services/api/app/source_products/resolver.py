"""Exact-print resolution for new-source products (new-sources plan §2.3).

Every outcome is decided by `exact_print_approval.resolve_exact_print`, called unchanged, on the
evidence the product itself carries: the card code from its title, the release from its list-page
group, and an official asset variant only where a reviewed `source_variant_renderings` row says
what a marker means. The only absence-based rule is the Yuyu-Tei F1 two-way-unique kind rule
(owner 2026-10-17): inside one release, exactly one product of a kind on this source and exactly
one print of that kind, and the print is not already held by another product.

Nothing here writes, fetches or commits. `resolve_product` returns a `Resolution`;
`apply_resolution` copies it onto a SourceProduct and never touches a manual match.
Condition (grade_key) never takes part in identity. Every non-exact outcome is quarantined,
except the two the plan refuses outright: sealed product and a product in two releases.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardPrint, ReleaseProduct, Source
from app.services.exact_print_approval import (
    REFUSAL_AMBIGUOUS,
    REFUSAL_NO_SOURCE_CARD_CODE,
    ExactPrintApprovalError,
    SourceEvidence,
    _norm,
    resolve_exact_print,
    sibling_prints_for_card_code,
)
from app.services.source_mapping_proposals import print_listing_kind
from app.source_products.models import SourceProduct, SourceProductGroup, SourceVariantRendering
from app.source_products.titles import KINDLESS_RARITIES, PARALLEL_MARKERS, ParsedTitle

KIND_RULE_KINDS = frozenset({"plain", "parallel", "special", "foil"})

QUARANTINE_LISTING_GRADED = "listing_kind_graded"
QUARANTINE_LISTING_UNKNOWN = "listing_kind_unknown"
QUARANTINE_RELEASE_UNRESOLVED = "release_group_unresolved"
QUARANTINE_RELEASE_UNCODED = "release_product_uncoded"
QUARANTINE_MARKER_UNRENDERED = "variant_marker_unrendered"
QUARANTINE_RENDERINGS_CONFLICT = "variant_renderings_conflict"
QUARANTINE_ARTWORK_RULE = "artwork_rule_not_supported"
QUARANTINE_NO_CANDIDATE = "no_print_in_release"
QUARANTINE_FOIL_WITHOUT_FOIL_PRINT = "foil_listing_has_no_foil_print"
QUARANTINE_KIND_CONTRADICTS_PRINT = "listing_kind_contradicts_print"
REFUSE_SEALED = "listing_kind_sealed"
REFUSE_TWO_RELEASES = "product_in_two_release_groups"


@dataclass(frozen=True)
class Rendering:
    official_asset_variant: str | None
    artwork_rule: str | None = None


@dataclass(frozen=True)
class Resolution:
    match_status: str
    card_print_id: int | None = None
    refusal_code: str | None = None
    detail: str = ""
    evidence_used: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_exact(self) -> bool:
        return self.match_status == "exact"


def _quarantine(code: str, detail: str) -> Resolution:
    return Resolution("quarantined", refusal_code=code, detail=detail)


def _refuse(code: str, detail: str) -> Resolution:
    return Resolution("refused", refusal_code=code, detail=detail)


def effective_kind(parsed: ParsedTitle) -> str:
    """The parsed kind, except that a bare promo P never decides one (plan §2.3)."""
    if parsed.rarity in KINDLESS_RARITIES and parsed.kind in {"plain", "parallel"}:
        return "unknown"
    return parsed.kind


def identity_markers(parsed: ParsedTitle) -> tuple[str, ...]:
    """Every title fact that may tell prints apart: the markers, plus a leading qualifier as `(text)`."""
    return parsed.markers + ((f"({parsed.qualifier})",) if parsed.qualifier else ())


def rendered_variant(
    parsed: ParsedTitle, renderings: Mapping[str, Rendering]
) -> tuple[str | None, Resolution | None]:
    """The official asset variant the product's markers name, or the quarantine that stops it.

    Parallel words and SP decide a kind without a rendering; every other marker needs one.
    """
    variants: set[str] = set()
    for marker in identity_markers(parsed):
        rendering = renderings.get(marker)
        if rendering is None:
            if marker in PARALLEL_MARKERS or marker == "SP":
                continue
            return None, _quarantine(QUARANTINE_MARKER_UNRENDERED, f"No reviewed rendering for {marker!r}.")
        if rendering.official_asset_variant is None:
            return None, _quarantine(
                QUARANTINE_ARTWORK_RULE, f"{marker!r} is rendered as an artwork rule, which S3 does not apply."
            )
        variants.add(rendering.official_asset_variant.strip().lower())
    if len(variants) > 1:
        return None, _quarantine(QUARANTINE_RENDERINGS_CONFLICT, f"Markers render to {sorted(variants)}.")
    return (variants.pop() if variants else None), None


def resolve_product(
    db: Session,
    *,
    source_name: str,
    url: str,
    listing_identity: str,
    parsed: ParsedTitle,
    release_product_ids: Collection[int],
    renderings: Mapping[str, Rendering],
    same_kind_listings: Collection[str],
    prints_held_elsewhere: Collection[int] = (),
) -> Resolution:
    """Resolve one product.

    `release_product_ids`: the releases of every group the product is listed in.
    `same_kind_listings`: listing identities of this source's products with the same card code,
    release and kind (this one included). `prints_held_elsewhere`: prints already exact or manual
    for another product of this source.
    """
    kind = effective_kind(parsed)
    if kind == "sealed":
        return _refuse(REFUSE_SEALED, "Sealed product is not a card.")
    if kind == "graded":
        return _quarantine(QUARANTINE_LISTING_GRADED, "Graded slabs are not resolved while PSA10 is OFF.")
    if _norm(parsed.card_code) is None:
        return _quarantine(REFUSAL_NO_SOURCE_CARD_CODE, "The title carries no card code.")

    releases = set(release_product_ids)
    if len(releases) > 1:
        return _refuse(REFUSE_TWO_RELEASES, f"Listed in groups of {len(releases)} releases {sorted(releases)}.")
    if not releases:
        return _quarantine(QUARANTINE_RELEASE_UNRESOLVED, "No group of this product names a release.")
    release = db.get(ReleaseProduct, next(iter(releases)))
    if release is None or _norm(release.official_code) is None:
        return _quarantine(QUARANTINE_RELEASE_UNCODED, "The group's release has no official code.")

    variant, stop = rendered_variant(parsed, renderings)
    if stop is not None:
        return stop
    if kind == "unknown" and any(m not in renderings for m in identity_markers(parsed)):
        return _quarantine(QUARANTINE_LISTING_UNKNOWN, "The title's markers do not decide a kind.")

    candidates = [
        p for p, _ in sibling_prints_for_card_code(db, parsed.card_code)
        if _norm(p.release_product_code) == _norm(release.official_code)
        and (variant is None or _norm(p.official_asset_variant) == _norm(variant))
    ]
    if not candidates:
        return _quarantine(
            QUARANTINE_NO_CANDIDATE,
            f"No active verified print of {parsed.card_code} in {release.official_code}"
            + (f" with variant {variant}." if variant else "."),
        )

    kind_choice: CardPrint | None = None
    if len(candidates) == 1:
        chosen = candidates[0]
    else:
        kind_choice = _two_way_unique(kind, candidates, listing_identity, same_kind_listings, prints_held_elsewhere)
        if kind_choice is None:
            return _quarantine(
                REFUSAL_AMBIGUOUS,
                f"{len(candidates)} prints {sorted(p.id for p in candidates)} survive and nothing tells them apart.",
            )
        chosen = kind_choice

    if kind == "foil" and print_listing_kind(chosen) != "foil":
        return _quarantine(QUARANTINE_FOIL_WITHOUT_FOIL_PRINT, f"Print {chosen.id} is not a foil print.")
    if kind in KIND_RULE_KINDS and print_listing_kind(chosen) != kind:
        return _quarantine(
            QUARANTINE_KIND_CONTRADICTS_PRINT,
            f"The listing is {kind} but print {chosen.id} is {print_listing_kind(chosen)}.",
        )

    evidence = SourceEvidence(
        source_name=source_name,
        source_url=url,
        card_code=parsed.card_code,
        set_code=release.official_code,
        variant=variant,
        rarity=parsed.rarity,
        title=parsed.title,
    )
    try:
        decision = resolve_exact_print(db, card_print_id=chosen.id, evidence=evidence)
    except ExactPrintApprovalError as error:
        if not (kind_choice is not None and error.code == REFUSAL_AMBIGUOUS and chosen.id in error.alternatives):
            return _quarantine(error.code, error.detail)
        # Every positive check passed and only the absence-based kind rule tells the survivors apart.
        return Resolution(
            "exact",
            card_print_id=chosen.id,
            evidence_used=(
                f"card code {parsed.card_code}",
                f"product {release.official_code}",
                *((f"asset variant {variant}",) if variant else ()),
                f"unique {kind} listing and unique {kind} print in release",
            ),
        )
    return Resolution("exact", card_print_id=decision.card_print.id, evidence_used=tuple(decision.evidence_used))


def _two_way_unique(
    kind: str,
    candidates: list[CardPrint],
    listing_identity: str,
    same_kind_listings: Collection[str],
    prints_held_elsewhere: Collection[int],
) -> CardPrint | None:
    if kind not in KIND_RULE_KINDS:
        return None
    kinds = {p.id: print_listing_kind(p) for p in candidates}
    if None in kinds.values():
        return None
    same = [p for p in candidates if kinds[p.id] == kind]
    if len(same) != 1 or set(same_kind_listings) != {listing_identity}:
        return None
    if same[0].id in set(prints_held_elsewhere):
        return None
    return same[0]


# --- stored products ---------------------------------------------------------


def load_renderings(db: Session, source_id: int) -> dict[str, Rendering]:
    rows = db.scalars(select(SourceVariantRendering).where(SourceVariantRendering.source_id == source_id))
    return {r.marker_text: Rendering(r.official_asset_variant, r.artwork_rule) for r in rows}


def release_ids_for(db: Session, source_id: int, group_keys: Collection[str]) -> set[int]:
    """Releases named by the product's groups. A group with no release names none."""
    if not group_keys:
        return set()
    rows = db.scalars(
        select(SourceProductGroup.release_product_id).where(
            SourceProductGroup.source_id == source_id,
            SourceProductGroup.group_key.in_(list(group_keys)),
            SourceProductGroup.release_product_id.is_not(None),
        )
    )
    return set(rows)


def resolve_stored_product(db: Session, product: SourceProduct, parsed: ParsedTitle) -> Resolution:
    """Resolve a stored product against its siblings on the same source."""
    source = db.get(Source, product.source_id)
    renderings = load_renderings(db, product.source_id)
    releases = release_ids_for(db, product.source_id, product.group_keys or [])
    siblings = db.scalars(
        select(SourceProduct).where(
            SourceProduct.source_id == product.source_id,
            SourceProduct.parsed_code == parsed.card_code,
        )
    ).all()
    same_kind = {
        s.canonical_listing_identity
        for s in siblings
        if s.listing_kind == effective_kind(parsed)
        and release_ids_for(db, product.source_id, s.group_keys or []) == releases
    } | {product.canonical_listing_identity}
    held = {
        s.card_print_id
        for s in siblings
        if s.id != product.id and s.card_print_id is not None and s.match_status in {"exact", "manual"}
    }
    return resolve_product(
        db,
        source_name=source.name,
        url=product.url,
        listing_identity=product.canonical_listing_identity,
        parsed=parsed,
        release_product_ids=releases,
        renderings=renderings,
        same_kind_listings=same_kind,
        prints_held_elsewhere=held,
    )


def apply_resolution(product: SourceProduct, resolution: Resolution) -> bool:
    """Copy a resolution onto the product. A manual match always wins; returns False then."""
    if product.match_status == "manual":
        return False
    product.match_status = resolution.match_status
    product.card_print_id = resolution.card_print_id if resolution.is_exact else None
    product.refusal_code = None if resolution.is_exact else resolution.refusal_code
    return True
