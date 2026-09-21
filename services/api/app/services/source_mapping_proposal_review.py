"""Bounded, GET-only read model for persisted source-mapping proposals.

The proposal tables are authoritative here.  No resolver is run, no source is
contacted, and every public entry point suppresses ORM autoflush so a read
cannot accidentally persist unrelated pending state from its caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, and_, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.models.source_mapping_proposal import RESOLUTION_STATUSES
from app.services.display_image import get_display_images_for_prints
from app.services.exact_print_approval import printing_label, special_print_label

SOURCES = ("yuyutei", "snkrdunk")
SORTS = (
    "default",
    "id_asc",
    "id_desc",
    "created_newest",
    "created_oldest",
    "release_newest",
    "release_oldest",
    "exact_first",
    "ambiguous_first",
    "source",
    "card_code",
)
ALLOWED_LIMITS = (25, 50, 100, 200)
_RESOLUTION_PRIORITY = {
    "exact": 0,
    "ambiguous": 1,
    "unresolved_identity": 2,
    "release_unresolved": 3,
    "conflict": 4,
    "stale": 5,
    "superseded": 6,
}


@dataclass(frozen=True)
class ReviewFilters:
    source: str | None = None
    release_product_id: int | None = None
    release_code: str | None = None
    unresolved_release: bool = False
    resolution_status: str | None = None
    review_status: str | None = None
    card_code: str | None = None
    candidate_id: int | None = None
    proposal_group_id: int | None = None
    has_candidate_image: bool | None = None
    has_recommended_alternative: bool | None = None
    include_superseded: bool = False
    query: str | None = None
    sort: str = "default"
    limit: int = 50
    offset: int = 0

    def validate(self) -> None:
        if self.source is not None and self.source not in SOURCES:
            raise ValueError(f"unsupported source {self.source!r}")
        if (
            self.resolution_status is not None
            and self.resolution_status not in RESOLUTION_STATUSES
        ):
            raise ValueError(
                f"unsupported resolution_status {self.resolution_status!r}"
            )
        if self.review_status is not None and self.review_status not in (
            "pending",
            "approved",
            "rejected",
        ):
            raise ValueError(f"unsupported review_status {self.review_status!r}")
        if self.unresolved_release and (
            self.release_product_id is not None or self.release_code is not None
        ):
            raise ValueError(
                "unresolved_release cannot be combined with a resolved release filter"
            )
        if self.sort not in SORTS:
            raise ValueError(f"unsupported sort {self.sort!r}")
        if self.limit not in ALLOWED_LIMITS:
            raise ValueError(f"limit must be one of {list(ALLOWED_LIMITS)}")


def _resolution_counts(rows: dict[str, int] | None = None) -> dict[str, int]:
    rows = rows or {}
    return {status: int(rows.get(status, 0)) for status in RESOLUTION_STATUSES}


def _summary_contract() -> dict[str, Any]:
    return {
        "data_source": "persisted_source_mapping_proposal_rows",
        "resolver_rerun": False,
        "read_only": True,
        "current_group_definition": "superseded_at IS NULL",
        "candidate_image_definition": "stored candidate image_url IS NOT NULL",
        "sources": list(SOURCES),
        "resolution_statuses": list(RESOLUTION_STATUSES),
    }


def persisted_review_summary(db: Session) -> dict[str, Any]:
    group = SourceMappingProposalGroup
    alt = SourceMappingProposalAlternative

    alt_counts = (
        select(
            alt.proposal_group_id.label("group_id"),
            func.count(alt.id).label("alternative_count"),
            func.sum(case((alt.recommended.is_(True), 1), else_=0)).label(
                "recommended_count"
            ),
        )
        .group_by(alt.proposal_group_id)
        .subquery()
    )
    yuyu_image = exists(
        select(1).where(
            YuyuteiCandidate.id == group.source_candidate_id,
            YuyuteiCandidate.image_url.is_not(None),
        )
    )
    snkr_image = exists(
        select(1).where(
            SnkrdunkCandidate.id == group.source_candidate_id,
            SnkrdunkCandidate.image_url.is_not(None),
        )
    )
    has_image = or_(
        and_(group.source_candidate_type == "yuyutei_candidate", yuyu_image),
        and_(group.source_candidate_type == "snkrdunk_candidate", snkr_image),
    )
    current = group.superseded_at.is_(None)

    aggregate = db.execute(
        select(
            func.count(group.id).filter(current).label("total_current_groups"),
            func.coalesce(
                func.sum(
                    case(
                        (current, func.coalesce(alt_counts.c.alternative_count, 0)),
                        else_=0,
                    )
                ),
                0,
            ).label("total_current_alternatives"),
            func.count(group.id)
            .filter(current, group.review_status == "pending")
            .label("pending"),
            func.count(group.id)
            .filter(current, group.review_status == "approved")
            .label("approved"),
            func.count(group.id)
            .filter(current, group.review_status == "rejected")
            .label("rejected"),
            func.count(group.id)
            .filter(current, group.resulting_source_card_mapping_id.is_not(None))
            .label("resulting"),
            func.count(group.id)
            .filter(group.superseded_at.is_not(None))
            .label("superseded"),
            func.count(group.id)
            .filter(current, func.coalesce(alt_counts.c.alternative_count, 0) == 1)
            .label("one_alt"),
            func.count(group.id)
            .filter(current, func.coalesce(alt_counts.c.alternative_count, 0) > 1)
            .label("multi_alt"),
            func.coalesce(
                func.max(
                    case(
                        (current, func.coalesce(alt_counts.c.alternative_count, 0)),
                        else_=0,
                    )
                ),
                0,
            ).label("max_alt"),
            func.count(group.id)
            .filter(current, group.release_product_id.is_not(None))
            .label("release_resolved"),
            func.count(group.id)
            .filter(current, group.release_product_id.is_(None))
            .label("null_release"),
            func.count(group.id).filter(current, has_image).label("with_image"),
            func.count(group.id).filter(current, ~has_image).label("without_image"),
            func.count(group.id)
            .filter(current, func.coalesce(alt_counts.c.recommended_count, 0) > 0)
            .label("with_recommended"),
            func.count(group.id)
            .filter(current, func.coalesce(alt_counts.c.recommended_count, 0) == 0)
            .label("without_recommended"),
        )
        .select_from(group)
        .outerjoin(alt_counts, alt_counts.c.group_id == group.id)
    ).one()

    grouped = db.execute(
        select(
            Source.name,
            group.resolution_status,
            func.count(group.id),
            func.coalesce(
                func.sum(func.coalesce(alt_counts.c.alternative_count, 0)), 0
            ),
        )
        .join(Source, Source.id == group.source_id)
        .outerjoin(alt_counts, alt_counts.c.group_id == group.id)
        .where(current)
        .group_by(Source.name, group.resolution_status)
    ).all()

    by_source: dict[str, dict[str, Any]] = {
        name: {
            "total_current_groups": 0,
            "total_current_alternatives": 0,
            "resolutions": _resolution_counts(),
        }
        for name in SOURCES
    }
    by_resolution = _resolution_counts()
    for source_name, status, count, alternatives in grouped:
        bucket = by_source.setdefault(
            source_name,
            {
                "total_current_groups": 0,
                "total_current_alternatives": 0,
                "resolutions": _resolution_counts(),
            },
        )
        bucket["total_current_groups"] += int(count)
        bucket["total_current_alternatives"] += int(alternatives)
        bucket["resolutions"][status] = int(count)
        by_resolution[status] = by_resolution.get(status, 0) + int(count)

    return {
        "contract": _summary_contract(),
        "total_current_groups": int(aggregate.total_current_groups),
        "total_current_alternatives": int(aggregate.total_current_alternatives),
        "pending_groups": int(aggregate.pending),
        "approved_groups": int(aggregate.approved),
        "rejected_groups": int(aggregate.rejected),
        "resulting_mappings_populated": int(aggregate.resulting),
        "superseded_historical_groups": int(aggregate.superseded),
        "by_resolution": by_resolution,
        "by_source": by_source,
        "by_source_and_resolution": {
            name: bucket["resolutions"] for name, bucket in by_source.items()
        },
        "groups_with_one_alternative": int(aggregate.one_alt),
        "groups_with_multiple_alternatives": int(aggregate.multi_alt),
        "maximum_alternatives_on_one_listing": int(aggregate.max_alt),
        "release_resolved_groups": int(aggregate.release_resolved),
        "null_release_groups": int(aggregate.null_release),
        "groups_with_candidate_images": int(aggregate.with_image),
        "groups_with_no_candidate_image": int(aggregate.without_image),
        "groups_with_recommended_alternatives": int(aggregate.with_recommended),
        "groups_with_no_recommended_alternative": int(aggregate.without_recommended),
    }


def persisted_release_summary(db: Session) -> dict[str, Any]:
    group = SourceMappingProposalGroup
    alt = SourceMappingProposalAlternative
    product_rows = db.scalars(select(ReleaseProduct)).all()

    print_counts = dict(
        db.execute(
            select(CardPrint.release_product_id, func.count(CardPrint.id))
            .where(
                CardPrint.is_active.is_(True),
                CardPrint.verification_status == "verified",
                CardPrint.language == "jp",
            )
            .group_by(CardPrint.release_product_id)
        ).all()
    )
    mapping_counts = dict(
        db.execute(
            select(CardPrint.release_product_id, func.count(SourceCardMapping.id))
            .join(SourceCardMapping, SourceCardMapping.card_print_id == CardPrint.id)
            .where(SourceCardMapping.card_print_id.is_not(None))
            .group_by(CardPrint.release_product_id)
        ).all()
    )

    alternative_counts = dict(
        db.execute(
            select(
                group.release_product_id,
                func.count(alt.id),
            )
            .join(alt, alt.proposal_group_id == group.id)
            .where(group.superseded_at.is_(None), group.review_status == "pending")
            .group_by(group.release_product_id)
        ).all()
    )
    proposal_counts = {
        row.release_product_id: row
        for row in db.execute(
            select(
                group.release_product_id,
                func.count(group.id).label("pending"),
                func.sum(case((group.resolution_status == "exact", 1), else_=0)).label(
                    "exact"
                ),
                func.sum(
                    case((group.resolution_status == "ambiguous", 1), else_=0)
                ).label("ambiguous"),
                func.sum(
                    case((group.resolution_status == "unresolved_identity", 1), else_=0)
                ).label("unresolved_identity"),
                func.sum(
                    case((group.resolution_status == "release_unresolved", 1), else_=0)
                ).label("release_unresolved"),
            )
            .where(group.superseded_at.is_(None), group.review_status == "pending")
            .group_by(group.release_product_id)
        ).all()
    }
    source_rows = db.execute(
        select(
            group.release_product_id,
            Source.name,
            func.count(func.distinct(group.id)).label("pending"),
            func.count(
                func.distinct(case((group.resolution_status == "exact", group.id)))
            ).label("exact"),
            func.count(
                func.distinct(case((group.resolution_status == "ambiguous", group.id)))
            ).label("ambiguous"),
            func.count(
                func.distinct(
                    case((group.resolution_status == "unresolved_identity", group.id))
                )
            ).label("unresolved_identity"),
            func.count(
                func.distinct(
                    case((group.resolution_status == "release_unresolved", group.id))
                )
            ).label("release_unresolved"),
            func.count(alt.id).label("alternatives"),
        )
        .join(Source, Source.id == group.source_id)
        .outerjoin(alt, alt.proposal_group_id == group.id)
        .where(group.superseded_at.is_(None), group.review_status == "pending")
        .group_by(group.release_product_id, Source.name)
    ).all()
    by_release_source: dict[tuple[int | None, str], dict[str, int]] = {}
    for row in source_rows:
        by_release_source[(row.release_product_id, row.name)] = {
            "pending_proposal_groups": int(row.pending),
            "exact_pending_groups": int(row.exact),
            "ambiguous_pending_groups": int(row.ambiguous),
            "unresolved_identity_pending_groups": int(row.unresolved_identity),
            "release_unresolved_pending_groups": int(row.release_unresolved),
            "alternatives": int(row.alternatives),
        }

    approved_prints = select(
        SourceCardMapping.card_print_id.label("card_print_id")
    ).where(
        SourceCardMapping.card_print_id.is_not(None),
        SourceCardMapping.is_active.is_(True),
        SourceCardMapping.review_status == "approved",
    )
    proposed_prints = (
        select(alt.card_print_id.label("card_print_id"))
        .join(group, group.id == alt.proposal_group_id)
        .where(
            group.superseded_at.is_(None),
            group.review_status == "pending",
            group.resolution_status == "exact",
            alt.recommended.is_(True),
        )
    )
    covered = approved_prints.union(proposed_prints).subquery()
    covered_counts = dict(
        db.execute(
            select(
                CardPrint.release_product_id, func.count(func.distinct(CardPrint.id))
            )
            .join(covered, covered.c.card_print_id == CardPrint.id)
            .where(
                CardPrint.is_active.is_(True),
                CardPrint.verification_status == "verified",
                CardPrint.language == "jp",
            )
            .group_by(CardPrint.release_product_id)
        ).all()
    )

    def source_breakdown(release_id: int | None) -> dict[str, dict[str, int]]:
        empty = {
            "pending_proposal_groups": 0,
            "exact_pending_groups": 0,
            "ambiguous_pending_groups": 0,
            "unresolved_identity_pending_groups": 0,
            "release_unresolved_pending_groups": 0,
            "alternatives": 0,
        }
        return {
            name: dict(by_release_source.get((release_id, name), empty))
            for name in SOURCES
        }

    def proposal_bucket(release_id: int | None) -> dict[str, int]:
        row = proposal_counts.get(release_id)
        return {
            "pending_proposal_groups": int(row.pending) if row else 0,
            "exact_pending_groups": int(row.exact or 0) if row else 0,
            "ambiguous_pending_groups": int(row.ambiguous or 0) if row else 0,
            "unresolved_identity_pending_groups": (
                int(row.unresolved_identity or 0) if row else 0
            ),
            "release_unresolved_pending_groups": (
                int(row.release_unresolved or 0) if row else 0
            ),
            "alternatives": alternative_counts.get(release_id, 0),
        }

    items = []
    # There is no authoritative chronology column. Coded products are kept
    # together and sorted by stable surrogate id descending; legitimate
    # uncoded/special products follow, also deterministically by id.
    ordered_products = sorted(
        product_rows,
        key=lambda row: (row.official_code is None, -row.id),
    )
    for product in ordered_products:
        total = int(print_counts.get(product.id, 0))
        items.append(
            {
                "release_product_id": product.id,
                "official_code": product.official_code,
                "display_name": product.display_name,
                "source_catalogue": product.source_catalogue,
                "authoritative_release_order": None,
                "chronology_available": False,
                "total_active_verified_japanese_card_prints": total,
                "existing_exact_source_card_mappings": int(
                    mapping_counts.get(product.id, 0)
                ),
                **proposal_bucket(product.id),
                "remaining_prints_with_no_approved_mapping_after_exact_proposals": max(
                    total - int(covered_counts.get(product.id, 0)), 0
                ),
                "sources": source_breakdown(product.id),
            }
        )

    items.append(
        {
            "release_product_id": None,
            "official_code": None,
            "display_name": "Unresolved release",
            "source_catalogue": None,
            "authoritative_release_order": None,
            "chronology_available": False,
            "total_active_verified_japanese_card_prints": int(
                print_counts.get(None, 0)
            ),
            "existing_exact_source_card_mappings": int(mapping_counts.get(None, 0)),
            **proposal_bucket(None),
            "remaining_prints_with_no_approved_mapping_after_exact_proposals": max(
                int(print_counts.get(None, 0)) - int(covered_counts.get(None, 0)), 0
            ),
            "sources": source_breakdown(None),
        }
    )
    return {
        "contract": {
            **_summary_contract(),
            "release_membership": "card_prints.release_product_id",
            "chronology_available": False,
            "chronology_limitation": (
                "release_products has no authoritative release-date/order field"
            ),
            "fallback_sort": (
                "coded products by release_product_id descending, then uncoded products "
                "by release_product_id descending, unresolved bucket last"
            ),
            "remaining_definition": (
                "active verified Japanese prints not covered by an active approved exact "
                "mapping or a recommended alternative on a current pending exact proposal"
            ),
        },
        "items": items,
    }


def _canonical_context(row: CanonicalCard | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "card_code": row.card_code,
        "name_en": row.name_en,
        "name_jp": row.name_jp,
        "card_type": row.card_type,
        "canonical_rarity": row.rarity,
    }


def _release_context(row: ReleaseProduct | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "official_code": row.official_code,
        "display_name": row.display_name,
        "source_catalogue": row.source_catalogue,
        "source_series_id": row.source_series_id,
        "source_url": row.source_url,
        "verification_status": row.verification_status,
        "authoritative_release_order": None,
        "chronology_available": False,
        "membership_explanation": (
            "Authoritative membership comes from card_prints.release_product_id; "
            "card-code prefixes, source titles, row order, similarity, and legacy "
            "Card.set_code are not used."
        ),
    }


def _candidate_summary(
    group: SourceMappingProposalGroup,
    candidate: YuyuteiCandidate | SnkrdunkCandidate | None,
) -> dict[str, Any]:
    evidence = group.evidence_summary_json or {}
    if isinstance(candidate, YuyuteiCandidate):
        return {
            "candidate_type": group.source_candidate_type,
            "candidate_id": candidate.id,
            "source_url": candidate.source_url,
            "source_native_identity": f"{candidate.set_slug}:{candidate.product_id}",
            "detected_card_code": candidate.detected_card_code,
            "detected_rarity": candidate.detected_rarity,
            "image_url": candidate.image_url,
            "image_missing": candidate.image_url is None,
            "price_jpy": candidate.price_jpy,
            "candidate_missing": False,
            "yuyutei": {
                "set_slug": candidate.set_slug,
                "product_id": candidate.product_id,
                "name_jp": candidate.name_jp,
                "availability": candidate.availability,
                "price_jpy": candidate.price_jpy,
                "image_url": candidate.image_url,
            },
            "snkrdunk": None,
        }
    if isinstance(candidate, SnkrdunkCandidate):
        return {
            "candidate_type": group.source_candidate_type,
            "candidate_id": candidate.id,
            "source_url": candidate.source_url,
            "source_native_identity": group.canonical_source_listing_identity,
            "detected_card_code": candidate.detected_card_code,
            "detected_rarity": candidate.detected_rarity,
            "image_url": candidate.image_url,
            "image_missing": candidate.image_url is None,
            "price_jpy": candidate.price_jpy,
            "candidate_missing": False,
            "yuyutei": None,
            "snkrdunk": {
                "title": candidate.title,
                "listing_count": candidate.listing_count,
                "condition_label": candidate.condition_label,
                "price_jpy": candidate.price_jpy,
                "detected_set_code": candidate.detected_set_code,
                "detected_variant": candidate.detected_variant,
                "image_url": candidate.image_url,
            },
        }
    image_url = evidence.get("image_url")
    return {
        "candidate_type": group.source_candidate_type,
        "candidate_id": group.source_candidate_id,
        "source_url": group.source_url,
        "source_native_identity": group.canonical_source_listing_identity,
        "detected_card_code": evidence.get("detected_card_code"),
        "detected_rarity": evidence.get("detected_rarity"),
        "image_url": image_url,
        "image_missing": image_url is None,
        "price_jpy": evidence.get("price_jpy"),
        "candidate_missing": True,
        "yuyutei": None,
        "snkrdunk": None,
    }


def _print_context(
    alternative: SourceMappingProposalAlternative,
    print_row: CardPrint,
    canonical: CanonicalCard,
    release: ReleaseProduct | None,
    display_images: dict[int, Any],
) -> dict[str, Any]:
    display = display_images.get(print_row.id)
    return {
        "alternative_id": alternative.id,
        "card_print_id": print_row.id,
        "recommended": alternative.recommended,
        "canonical_card": _canonical_context(canonical),
        "release": _release_context(release),
        "language": print_row.language,
        "official_asset_variant": print_row.official_asset_variant,
        "release_product_code": print_row.release_product_code,
        "treatment": print_row.treatment,
        "official_rarity": print_row.official_rarity,
        "official_block_icon": print_row.official_block_icon,
        "official_name": print_row.official_name,
        "official_effect_text": print_row.official_effect_text,
        "artwork_key": print_row.artwork_key,
        "artist": print_row.artist,
        "printing_label": printing_label(print_row),
        "special_print_label": special_print_label(print_row, canonical),
        "canonical_image_url": print_row.image_url,
        "display_image": display,
        "image_missing": display is None,
        "is_active": print_row.is_active,
        "verification_status": print_row.verification_status,
    }


def _candidate_image_condition(group: type[SourceMappingProposalGroup]):
    return or_(
        and_(
            group.source_candidate_type == "yuyutei_candidate",
            exists(
                select(1).where(
                    YuyuteiCandidate.id == group.source_candidate_id,
                    YuyuteiCandidate.image_url.is_not(None),
                )
            ),
        ),
        and_(
            group.source_candidate_type == "snkrdunk_candidate",
            exists(
                select(1).where(
                    SnkrdunkCandidate.id == group.source_candidate_id,
                    SnkrdunkCandidate.image_url.is_not(None),
                )
            ),
        ),
    )


def _filtered_statement(filters: ReviewFilters):
    group = SourceMappingProposalGroup
    stmt = (
        select(group, Source, CanonicalCard, ReleaseProduct)
        .join(Source, Source.id == group.source_id)
        .outerjoin(CanonicalCard, CanonicalCard.id == group.canonical_card_id)
        .outerjoin(ReleaseProduct, ReleaseProduct.id == group.release_product_id)
    )
    conditions = []
    if not filters.include_superseded:
        conditions.append(group.superseded_at.is_(None))
    if filters.source:
        conditions.append(Source.name == filters.source)
    if filters.release_product_id is not None:
        conditions.append(group.release_product_id == filters.release_product_id)
    if filters.release_code:
        conditions.append(
            func.lower(ReleaseProduct.official_code) == filters.release_code.lower()
        )
    if filters.unresolved_release:
        conditions.append(group.release_product_id.is_(None))
    if filters.resolution_status:
        conditions.append(group.resolution_status == filters.resolution_status)
    if filters.review_status:
        conditions.append(group.review_status == filters.review_status)
    if filters.card_code:
        conditions.append(
            func.lower(CanonicalCard.card_code) == filters.card_code.lower()
        )
    if filters.candidate_id is not None:
        conditions.append(group.source_candidate_id == filters.candidate_id)
    if filters.proposal_group_id is not None:
        conditions.append(group.id == filters.proposal_group_id)
    if filters.has_candidate_image is not None:
        image_condition = _candidate_image_condition(group)
        conditions.append(
            image_condition if filters.has_candidate_image else ~image_condition
        )
    if filters.has_recommended_alternative is not None:
        recommended = exists(
            select(1).where(
                SourceMappingProposalAlternative.proposal_group_id == group.id,
                SourceMappingProposalAlternative.recommended.is_(True),
            )
        )
        conditions.append(
            recommended if filters.has_recommended_alternative else ~recommended
        )
    if filters.query and filters.query.strip():
        pattern = f"%{filters.query.strip()}%"
        conditions.append(
            or_(
                CanonicalCard.card_code.ilike(pattern),
                CanonicalCard.name_en.ilike(pattern),
                CanonicalCard.name_jp.ilike(pattern),
                group.canonical_source_listing_identity.ilike(pattern),
                cast(group.source_candidate_id, String).ilike(pattern),
                exists(
                    select(1).where(
                        group.source_candidate_type == "yuyutei_candidate",
                        YuyuteiCandidate.id == group.source_candidate_id,
                        or_(
                            YuyuteiCandidate.name_jp.ilike(pattern),
                            YuyuteiCandidate.detected_card_code.ilike(pattern),
                            cast(YuyuteiCandidate.id, String).ilike(pattern),
                        ),
                    )
                ),
                exists(
                    select(1).where(
                        group.source_candidate_type == "snkrdunk_candidate",
                        SnkrdunkCandidate.id == group.source_candidate_id,
                        or_(
                            SnkrdunkCandidate.title.ilike(pattern),
                            SnkrdunkCandidate.detected_card_code.ilike(pattern),
                            cast(SnkrdunkCandidate.id, String).ilike(pattern),
                        ),
                    )
                ),
            )
        )
    return stmt.where(*conditions) if conditions else stmt


def _order_by(sort: str):
    group = SourceMappingProposalGroup
    null_release = case((group.release_product_id.is_(None), 1), else_=0)
    priority = case(
        *[
            (group.resolution_status == status, rank)
            for status, rank in _RESOLUTION_PRIORITY.items()
        ],
        else_=99,
    )
    if sort == "id_asc":
        return (group.id.asc(),)
    if sort == "id_desc":
        return (group.id.desc(),)
    if sort == "created_newest":
        return (group.created_at.desc(), group.id.desc())
    if sort == "created_oldest":
        return (group.created_at.asc(), group.id.asc())
    if sort == "release_newest":
        return (null_release.asc(), group.release_product_id.desc(), group.id.asc())
    if sort == "release_oldest":
        return (null_release.asc(), group.release_product_id.asc(), group.id.asc())
    if sort == "exact_first":
        return (case((group.resolution_status == "exact", 0), else_=1), group.id.asc())
    if sort == "ambiguous_first":
        return (
            case((group.resolution_status == "ambiguous", 0), else_=1),
            group.id.asc(),
        )
    if sort == "source":
        return (Source.name.asc(), group.id.asc())
    if sort == "card_code":
        return (
            case((CanonicalCard.card_code.is_(None), 1), else_=0),
            CanonicalCard.card_code.asc(),
            group.id.asc(),
        )
    return (
        null_release.asc(),
        group.release_product_id.desc(),
        priority.asc(),
        Source.name.asc(),
        case((CanonicalCard.card_code.is_(None), 1), else_=0),
        CanonicalCard.card_code.asc(),
        group.id.asc(),
    )


def _list_contract(filters: ReviewFilters) -> dict[str, Any]:
    return {
        **_summary_contract(),
        "default_sort": (
            "resolved release_product_id descending; resolution priority exact, ambiguous, "
            "unresolved_identity, release_unresolved, conflict, stale, superseded; source; "
            "card code; proposal id; NULL release last"
        ),
        "release_sort_limitation": (
            "release_product_id is a deterministic fallback because no authoritative "
            "release chronology field exists"
        ),
        "sort": filters.sort,
        "allowed_limits": list(ALLOWED_LIMITS),
        "full_evidence_in_list": False,
        "image_resolution": "stored database evidence only; no network request",
    }


def _load_candidates(db: Session, groups: list[SourceMappingProposalGroup]):
    yuyu_ids = {
        row.source_candidate_id
        for row in groups
        if row.source_candidate_type == "yuyutei_candidate"
    }
    snkr_ids = {
        row.source_candidate_id
        for row in groups
        if row.source_candidate_type == "snkrdunk_candidate"
    }
    yuyu = (
        {
            row.id: row
            for row in db.scalars(
                select(YuyuteiCandidate).where(YuyuteiCandidate.id.in_(yuyu_ids))
            ).all()
        }
        if yuyu_ids
        else {}
    )
    snkr = (
        {
            row.id: row
            for row in db.scalars(
                select(SnkrdunkCandidate).where(SnkrdunkCandidate.id.in_(snkr_ids))
            ).all()
        }
        if snkr_ids
        else {}
    )
    return yuyu, snkr


def _candidate_for(group, yuyu, snkr):
    if group.source_candidate_type == "yuyutei_candidate":
        return yuyu.get(group.source_candidate_id)
    if group.source_candidate_type == "snkrdunk_candidate":
        return snkr.get(group.source_candidate_id)
    return None


def _alternative_contexts(
    db: Session,
    group_ids: list[int],
    *,
    recommended_only: bool,
):
    if not group_ids:
        return {}, {}
    alt = SourceMappingProposalAlternative
    stmt = (
        select(alt, CardPrint, CanonicalCard, ReleaseProduct)
        .join(CardPrint, CardPrint.id == alt.card_print_id)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .outerjoin(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .where(alt.proposal_group_id.in_(group_ids))
        .order_by(alt.proposal_group_id, alt.id)
    )
    if recommended_only:
        stmt = stmt.where(alt.recommended.is_(True))
    rows = db.execute(stmt).all()
    prints = list({row[1].id: row[1] for row in rows}.values())
    display_images = get_display_images_for_prints(db, prints) if prints else {}
    by_group: dict[int, list[dict[str, Any]]] = {group_id: [] for group_id in group_ids}
    raw_by_group: dict[int, list[tuple[Any, Any, Any, Any]]] = {
        group_id: [] for group_id in group_ids
    }
    for alternative, print_row, canonical, release in rows:
        by_group[alternative.proposal_group_id].append(
            _print_context(alternative, print_row, canonical, release, display_images)
        )
        raw_by_group[alternative.proposal_group_id].append(
            (alternative, print_row, canonical, release)
        )
    return by_group, raw_by_group


def list_review_groups(db: Session, filters: ReviewFilters) -> dict[str, Any]:
    filters.validate()
    with db.no_autoflush:
        base = _filtered_statement(filters)
        count_stmt = select(func.count()).select_from(base.order_by(None).subquery())
        total = int(db.scalar(count_stmt) or 0)
        page_rows = db.execute(
            base.order_by(*_order_by(filters.sort))
            .offset(filters.offset)
            .limit(filters.limit)
        ).all()
        groups = [row[0] for row in page_rows]
        yuyu, snkr = _load_candidates(db, groups)
        group_ids = [row.id for row in groups]
        counts = (
            {
                group_id: (int(count), int(recommended or 0))
                for group_id, count, recommended in db.execute(
                    select(
                        SourceMappingProposalAlternative.proposal_group_id,
                        func.count(SourceMappingProposalAlternative.id),
                        func.sum(
                            case(
                                (
                                    SourceMappingProposalAlternative.recommended.is_(
                                        True
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                    )
                    .where(
                        SourceMappingProposalAlternative.proposal_group_id.in_(
                            group_ids
                        )
                    )
                    .group_by(SourceMappingProposalAlternative.proposal_group_id)
                ).all()
            }
            if group_ids
            else {}
        )
        recommended, _ = _alternative_contexts(db, group_ids, recommended_only=True)

        items = []
        for group, source, canonical, release in page_rows:
            alternative_count, recommended_count = counts.get(group.id, (0, 0))
            candidate = _candidate_for(group, yuyu, snkr)
            canonical_payload = _canonical_context(canonical)
            previews = recommended.get(group.id, [])
            items.append(
                {
                    "id": group.id,
                    "source_id": source.id,
                    "source_name": source.name,
                    "source": {"id": source.id, "name": source.name},
                    "canonical_source_listing_identity": group.canonical_source_listing_identity,
                    "source_url": group.source_url,
                    "source_candidate_type": group.source_candidate_type,
                    "source_candidate_id": group.source_candidate_id,
                    "resolution_status": group.resolution_status,
                    "review_status": group.review_status,
                    "resolver_version": group.resolver_version,
                    "created_at": group.created_at,
                    "updated_at": group.updated_at,
                    "superseded_at": group.superseded_at,
                    "resulting_source_card_mapping_id": group.resulting_source_card_mapping_id,
                    "alternative_count": alternative_count,
                    "recommended_alternative_count": recommended_count,
                    "canonical_card_id": group.canonical_card_id,
                    "card_code": canonical.card_code if canonical else None,
                    "name_en": canonical.name_en if canonical else None,
                    "name_jp": canonical.name_jp if canonical else None,
                    "canonical_card": canonical_payload,
                    "release_product_id": group.release_product_id,
                    "release": _release_context(release),
                    "candidate": _candidate_summary(group, candidate),
                    "recommended_print": previews[0] if previews else None,
                }
            )
        return {
            "contract": _list_contract(filters),
            "items": items,
            "pagination": pagination_response(
                items, total, filters.limit, filters.offset
            ),
        }


def _discovery_context(
    db: Session, source_name: str, candidate
) -> dict[str, Any] | None:
    if candidate is None or candidate.discovery_run_id is None:
        return None
    if source_name == "yuyutei":
        run = db.get(YuyuteiDiscoveryRun, candidate.discovery_run_id)
        if run is None:
            return None
        return {
            "id": run.id,
            "source": source_name,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "provenance": {
                "requested_set_slugs": run.requested_set_slugs,
                "pages_fetched": run.pages_fetched,
                "products_seen": run.products_seen,
                "candidates_written": run.candidates_written,
                "stopped_reason": run.stopped_reason,
                "per_slug_metrics": run.per_slug_metrics_json,
            },
        }
    run = db.get(SnkrdunkDiscoveryRun, candidate.discovery_run_id)
    if run is None:
        return None
    return {
        "id": run.id,
        "source": source_name,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "provenance": {
            "seed_url": run.seed_url,
            "pages_fetched": run.pages_fetched,
            "candidates_found": run.candidates_found,
            "candidates_matched": run.candidates_matched,
        },
    }


def review_group_detail(db: Session, proposal_group_id: int) -> dict[str, Any] | None:
    filters = ReviewFilters(
        proposal_group_id=proposal_group_id,
        include_superseded=True,
        limit=25,
    )
    with db.no_autoflush:
        listing = list_review_groups(db, filters)
        if not listing["items"]:
            return None
        item = listing["items"][0]
        group = db.get(SourceMappingProposalGroup, proposal_group_id)
        assert group is not None
        yuyu, snkr = _load_candidates(db, [group])
        candidate = _candidate_for(group, yuyu, snkr)
        source_name = item["source_name"]
        candidate_detail = {
            **item["candidate"],
            "raw_listing_text": (
                candidate.raw_listing_text
                if isinstance(candidate, YuyuteiCandidate)
                else (
                    candidate.raw_text
                    if isinstance(candidate, SnkrdunkCandidate)
                    else None
                )
            ),
            "normalized_title": (
                candidate.normalized_title
                if isinstance(candidate, SnkrdunkCandidate)
                else None
            ),
            "match_status": candidate.match_status if candidate is not None else None,
            "match_explanation": (
                candidate.match_explanation_json if candidate is not None else None
            ),
            "ambiguous_matches": (
                candidate.ambiguous_matches_json
                if isinstance(candidate, SnkrdunkCandidate)
                else None
            ),
            "stored_evidence": (
                {
                    "discovery_run_id": candidate.discovery_run_id,
                    "set_slug": candidate.set_slug,
                    "product_id": candidate.product_id,
                    "source_url": candidate.source_url,
                    "detected_card_code": candidate.detected_card_code,
                    "detected_rarity": candidate.detected_rarity,
                    "name_jp": candidate.name_jp,
                    "image_url": candidate.image_url,
                    "price_jpy": candidate.price_jpy,
                    "availability": candidate.availability,
                    "raw_listing_text": candidate.raw_listing_text,
                    "match_status": candidate.match_status,
                    "matched_card_print_id": candidate.matched_card_print_id,
                    "match_explanation": candidate.match_explanation_json,
                    "created_at": candidate.created_at,
                    "updated_at": candidate.updated_at,
                }
                if isinstance(candidate, YuyuteiCandidate)
                else (
                    {
                        "discovery_run_id": candidate.discovery_run_id,
                        "source_url": candidate.source_url,
                        "title": candidate.title,
                        "price_jpy": candidate.price_jpy,
                        "image_url": candidate.image_url,
                        "listing_count": candidate.listing_count,
                        "condition_label": candidate.condition_label,
                        "raw_text": candidate.raw_text,
                        "normalized_title": candidate.normalized_title,
                        "detected_card_code": candidate.detected_card_code,
                        "detected_set_code": candidate.detected_set_code,
                        "detected_rarity": candidate.detected_rarity,
                        "detected_variant": candidate.detected_variant,
                        "match_status": candidate.match_status,
                        "match_confidence": candidate.match_confidence,
                        "best_match_score": candidate.best_match_score,
                        "best_match_confidence_label": candidate.best_match_confidence_label,
                        "match_explanation": candidate.match_explanation_json,
                        "ambiguous_matches": candidate.ambiguous_matches_json,
                        "created_at": candidate.created_at,
                        "updated_at": candidate.updated_at,
                    }
                    if isinstance(candidate, SnkrdunkCandidate)
                    else dict(group.evidence_summary_json or {})
                )
            ),
            "discovery_run": _discovery_context(db, source_name, candidate),
        }

        alternatives, raw_alternatives = _alternative_contexts(
            db, [proposal_group_id], recommended_only=False
        )
        enriched = []
        for payload, raw in zip(
            alternatives.get(proposal_group_id, []),
            raw_alternatives.get(proposal_group_id, []),
            strict=True,
        ):
            alternative = raw[0]
            enriched.append(
                {
                    **payload,
                    "proposal_group_id": proposal_group_id,
                    "review_disposition": alternative.review_disposition,
                    "review_notes": alternative.review_notes,
                    "reviewed_at": alternative.reviewed_at,
                    "created_at": alternative.created_at,
                    "updated_at": alternative.updated_at,
                    "supporting_evidence": alternative.supporting_evidence_json,
                    "missing_evidence": alternative.missing_evidence_json,
                    "conflict_reasons": alternative.conflict_reasons_json,
                }
            )

        candidate_matched_card_id = (
            candidate.matched_card_id
            if isinstance(candidate, SnkrdunkCandidate)
            else None
        )
        candidate_best_match_card_id = (
            candidate.best_match_card_id
            if isinstance(candidate, SnkrdunkCandidate)
            else None
        )
        resulting_mapping_card_id = None
        resulting_mapping_payload = None
        if group.resulting_source_card_mapping_id is not None:
            mapping = db.get(SourceCardMapping, group.resulting_source_card_mapping_id)
            if mapping is not None:
                resulting_mapping_card_id = mapping.card_id
                resulting_mapping_payload = {
                    "id": mapping.id,
                    "source_id": mapping.source_id,
                    "source_card_id": mapping.source_card_id,
                    "source_url": mapping.source_url,
                    "card_print_id": mapping.card_print_id,
                    "review_status": mapping.review_status,
                    "is_active": mapping.is_active,
                    "authoritative_identity": "card_print_id",
                }
        legacy_ids = {
            value
            for value in (
                candidate_matched_card_id,
                candidate_best_match_card_id,
                resulting_mapping_card_id,
            )
            if value is not None
        }
        legacy_cards = (
            db.scalars(select(Card).where(Card.id.in_(legacy_ids))).all()
            if legacy_ids
            else []
        )
        compatibility = {
            "role": (
                "Legacy Card/card_id metadata is compatibility-only and is never the "
                "authoritative exact-print identity."
            ),
            "candidate_matched_card_id": candidate_matched_card_id,
            "candidate_best_match_card_id": candidate_best_match_card_id,
            "resulting_mapping_card_id": resulting_mapping_card_id,
            "legacy_cards": [
                {
                    "id": row.id,
                    "card_code": row.card_code,
                    "name_en": row.name_en,
                    "name_jp": row.name_jp,
                    "set_code": row.set_code,
                    "rarity": row.rarity,
                    "variant": row.variant,
                    "language": row.language,
                }
                for row in legacy_cards
            ],
        }
        return {
            **item,
            "evidence_digest": group.evidence_digest,
            "reviewed_at": group.reviewed_at,
            "reviewed_by": group.reviewed_by,
            "review_notes": group.review_notes,
            "selected_alternative_id": group.selected_alternative_id,
            "decision_basis_updated_at": group.decision_basis_updated_at,
            "evidence_summary": group.evidence_summary_json,
            "resolution_reasons": group.resolution_reasons_json,
            "resulting_mapping": resulting_mapping_payload,
            "candidate": candidate_detail,
            "alternatives": enriched,
            "compatibility": compatibility,
            "historical_state": {
                "is_current": group.superseded_at is None,
                "superseded_at": group.superseded_at,
                "resolver_version": group.resolver_version,
                "evidence_digest": group.evidence_digest,
            },
        }


def get_persisted_review_summary(db: Session) -> dict[str, Any]:
    with db.no_autoflush:
        return persisted_review_summary(db)


def get_persisted_release_summary(db: Session) -> dict[str, Any]:
    with db.no_autoflush:
        return persisted_release_summary(db)


__all__ = [
    "ALLOWED_LIMITS",
    "ReviewFilters",
    "SORTS",
    "get_persisted_release_summary",
    "get_persisted_review_summary",
    "list_review_groups",
    "review_group_detail",
]
