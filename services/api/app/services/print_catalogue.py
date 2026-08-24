"""Print-centric identity/catalogue shaping - the card_print/canonical_card
counterpart to app.services.card_catalogue. Builds CardPrintOut (single
print detail, including sibling prints) and the paginated print catalogue.

Display metadata (card_code/name/rarity/card_type/colors) always comes from
a print's CanonicalCard, never from the legacy Card table's rarity/variant
columns - see CardPrintOut/PrintCatalogueItemOut docstrings in app.schemas.

`rarity` is optional on that canonical row and may be NULL; it is served as
NULL, filtered on only when a caller names an explicit value, and contributes
no facet when absent. The rarity of one exact printing is
card_prints.official_rarity, which this module does not serve.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import CanonicalCard, CardPrint
from app.schemas import (
    CardPrintOut,
    CardPrintSiblingOut,
    DisplayImageOut,
    PrintCatalogueFacetsOut,
    PrintCatalogueItemOut,
    PrintMarketIndexOut,
)
from app.services.display_image import get_display_images_for_prints
from app.services.print_market_index import get_market_index_for_prints

SortKey = Literal["card_code", "name", "index_desc", "index_asc", "updated"]
SORT_KEYS: tuple[SortKey, ...] = ("card_code", "name", "index_desc", "index_asc", "updated")

_INDEX_SORTS = {"index_desc", "index_asc"}


def _sibling_out(sibling: CardPrint) -> CardPrintSiblingOut:
    return CardPrintSiblingOut(
        card_print_id=sibling.id,
        treatment=sibling.treatment,
        language=sibling.language,
        verification_status=sibling.verification_status,
        image_url=sibling.image_url,
    )


def get_siblings(
    db: Session, canonical_card_id: int, exclude_print_id: int
) -> list[CardPrintSiblingOut]:
    """Every other active print of the same canonical card - e.g. for OP01-
    013 Sanji's base print, this returns the parallel print (and vice
    versa), never the requested print itself."""
    rows = db.scalars(
        select(CardPrint)
        .where(
            CardPrint.canonical_card_id == canonical_card_id,
            CardPrint.id != exclude_print_id,
            CardPrint.is_active.is_(True),
        )
        .order_by(CardPrint.id.asc())
    ).all()
    return [_sibling_out(r) for r in rows]


def to_print_out(
    print_row: CardPrint,
    canonical: CanonicalCard,
    market_index: PrintMarketIndexOut,
    siblings: list[CardPrintSiblingOut],
    display_image: DisplayImageOut | None = None,
) -> CardPrintOut:
    return CardPrintOut(
        card_print_id=print_row.id,
        canonical_card_id=canonical.id,
        card_code=canonical.card_code,
        name_en=canonical.name_en,
        name_jp=canonical.name_jp,
        rarity=canonical.rarity,
        card_type=canonical.card_type,
        colors=canonical.colors,
        language=print_row.language,
        treatment=print_row.treatment,
        release_product_code=print_row.release_product_code,
        artwork_key=print_row.artwork_key,
        image_url=print_row.image_url,
        display_image=display_image,
        verification_status=print_row.verification_status,
        market_index=market_index,
        siblings=siblings,
    )


def _source_coverage(market_index: PrintMarketIndexOut) -> list[str]:
    sources = {
        sv.source
        for sv in (*market_index.source_values, *market_index.auxiliary_values)
        if sv.observed_at is not None
    }
    return sorted(sources)


def _to_catalogue_item(
    print_row: CardPrint,
    canonical: CanonicalCard,
    market_index: PrintMarketIndexOut,
    display_image: DisplayImageOut | None = None,
) -> PrintCatalogueItemOut:
    return PrintCatalogueItemOut(
        card_print_id=print_row.id,
        canonical_card_id=canonical.id,
        card_code=canonical.card_code,
        name_en=canonical.name_en,
        name_jp=canonical.name_jp,
        rarity=canonical.rarity,
        card_type=canonical.card_type,
        treatment=print_row.treatment,
        language=print_row.language,
        release_product_code=print_row.release_product_code,
        image_url=print_row.image_url,
        display_image=display_image,
        verification_status=print_row.verification_status,
        market_index=market_index,
        source_coverage=_source_coverage(market_index),
        latest_observation_at=market_index.freshest_observation_at,
    )


def _canonical_map(db: Session, canonical_ids: set[int]) -> dict[int, CanonicalCard]:
    if not canonical_ids:
        return {}
    return {
        c.id: c
        for c in db.scalars(select(CanonicalCard).where(CanonicalCard.id.in_(canonical_ids))).all()
    }


def _apply_filters(
    stmt,
    *,
    q: str | None,
    treatment: str | None,
    language: str | None,
    rarity: str | None,
    verification_status: str | None,
):
    stmt = stmt.where(CardPrint.is_active.is_(True))
    # Only ever an equality match on an explicit value - a NULL treatment can
    # therefore never be returned by a treatment filter, and no filter value
    # selects "unclassified".
    if treatment:
        stmt = stmt.where(CardPrint.treatment == treatment)
    if language:
        stmt = stmt.where(CardPrint.language == language)
    if verification_status:
        stmt = stmt.where(CardPrint.verification_status == verification_status)
    if rarity:
        stmt = stmt.where(CanonicalCard.rarity == rarity)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CanonicalCard.name_en.ilike(like),
                CanonicalCard.name_jp.ilike(like),
                CanonicalCard.card_code.ilike(like),
            )
        )
    return stmt


def list_print_catalogue(
    db: Session,
    *,
    q: str | None = None,
    treatment: str | None = None,
    language: str | None = None,
    rarity: str | None = None,
    verification_status: str | None = None,
    sort: SortKey = "card_code",
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[PrintCatalogueItemOut], int]:
    base = select(CardPrint).join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
    base = _apply_filters(
        base,
        q=q,
        treatment=treatment,
        language=language,
        rarity=rarity,
        verification_status=verification_status,
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    if total == 0:
        return [], 0

    if sort in _INDEX_SORTS:
        all_prints = db.scalars(base.order_by(CardPrint.id.asc())).all()
        index_by_print = get_market_index_for_prints(db, [p.id for p in all_prints])

        def sort_key(p: CardPrint):
            index = index_by_print[p.id]
            value = index.index_value_jpy
            missing = value is None
            magnitude = value if value is not None else 0
            if sort == "index_desc":
                return (missing, -magnitude, p.id)
            return (missing, magnitude, p.id)

        all_prints.sort(key=sort_key)
        page_prints = all_prints[offset : offset + limit]
        page_index_by_print = {p.id: index_by_print[p.id] for p in page_prints}
    else:
        ordered = base
        if sort == "name":
            ordered = ordered.order_by(
                func.coalesce(CanonicalCard.name_en, CanonicalCard.name_jp).asc(),
                CardPrint.id.asc(),
            )
        elif sort == "updated":
            ordered = ordered.order_by(CardPrint.updated_at.desc(), CardPrint.id.asc())
        else:  # "card_code"
            # NULLS LAST explicitly: an unclassified print sorts after the
            # classified siblings of the same card rather than wherever the
            # engine's default puts it (PostgreSQL puts NULLs last on ASC,
            # sqlite puts them first - the same query must not order two ways).
            # CardPrint.id.asc() still makes the whole order total.
            ordered = ordered.order_by(
                CanonicalCard.card_code.asc(),
                CardPrint.treatment.asc().nulls_last(),
                CardPrint.id.asc(),
            )

        page_prints = db.scalars(ordered.limit(limit).offset(offset)).all()
        page_index_by_print = get_market_index_for_prints(db, [p.id for p in page_prints])

    canonical_by_id = _canonical_map(db, {p.canonical_card_id for p in page_prints})
    # One extra mapping query for the whole page - never per item, and never
    # a raw_snapshots read (see app.services.display_image).
    display_by_print = get_display_images_for_prints(db, list(page_prints))
    items = [
        _to_catalogue_item(
            p,
            canonical_by_id[p.canonical_card_id],
            page_index_by_print[p.id],
            display_by_print.get(p.id),
        )
        for p in page_prints
    ]
    return items, total


def get_print_catalogue_facets(db: Session) -> PrintCatalogueFacetsOut:
    """Distinct filterable values actually present among active card_prints
    - ignores the request's own filters, same convention as
    app.services.card_catalogue.get_catalogue_facets."""
    active = CardPrint.is_active.is_(True)
    # NULL is excluded rather than surfaced: a facet value is a filter the
    # collector can select, and "unclassified" is not a treatment. No
    # synthetic bucket is invented for it either.
    treatments = db.scalars(
        select(CardPrint.treatment)
        .where(active, CardPrint.treatment.is_not(None))
        .distinct()
        .order_by(CardPrint.treatment)
    ).all()
    languages = db.scalars(
        select(CardPrint.language).where(active).distinct().order_by(CardPrint.language)
    ).all()
    verification_statuses = db.scalars(
        select(CardPrint.verification_status)
        .where(active)
        .distinct()
        .order_by(CardPrint.verification_status)
    ).all()
    # Same rule as treatments above, for the same reason: CanonicalCard.rarity
    # is optional, and a card whose card-level rarity the catalogue does not
    # establish contributes no facet value. Without the IS NOT NULL filter,
    # DISTINCT would return NULL as if it were a selectable rarity - and no
    # synthetic "Unknown" bucket is invented for it either.
    rarities = db.scalars(
        select(CanonicalCard.rarity)
        .join(CardPrint, CardPrint.canonical_card_id == CanonicalCard.id)
        .where(active, CanonicalCard.rarity.is_not(None))
        .distinct()
        .order_by(CanonicalCard.rarity)
    ).all()
    return PrintCatalogueFacetsOut(
        treatments=list(treatments),
        rarities=list(rarities),
        languages=list(languages),
        verification_statuses=list(verification_statuses),
    )
