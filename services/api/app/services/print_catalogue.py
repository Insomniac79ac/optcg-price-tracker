"""Print-centric identity/catalogue shaping - the card_print/canonical_card
counterpart to app.services.card_catalogue. Builds CardPrintOut (single
print detail, including sibling prints) and the paginated print catalogue.

Display metadata (card_code/name/card_type/colors) always comes from a
print's CanonicalCard, never from the legacy Card table's rarity/variant
columns - see CardPrintOut/PrintCatalogueItemOut docstrings in app.schemas.

`rarity` is the one field that does not come from the canonical row alone, and
deliberately so. Rarity is a property of a *printing*, not of a card code:
Bandai publishes it per catalogue entry, and the same code is published at
different rarities in different products. That is why `canonical_cards.rarity`
is nullable - where the catalogue establishes no single card-level value it
stores none rather than inventing one. This module therefore serves the
*exact print's* rarity, resolving
`card_prints.official_rarity` first and falling back to the canonical
card-level value, via `effective_rarity` / `effective_rarity_sql` below. Where
neither is present the field is still NULL: no placeholder, no guess.

Display, filtering and faceting all go through that same resolution, so a tile
can never show a rarity the `?rarity=` filter would not match, or offer a
facet value that selects nothing.

One layer sits above that resolution and only above it: `app.services.
rarity_facets` folds tokens that name a single collector concept into one
catalogue-facing value, and expands that value back to every token it covers
when filtering. It is what makes `SPカード` and `SP P` a single `SP CARD`
option whose population is the sum of both. It is a query-time mapping only -
`rarity` on the wire is still the exact published token, and no stored value is
normalised or mutated - so the invariant above holds under it: every offered
facet value selects at least one print, and every print is reachable from the
facet its own rarity folds into.

The card-level summary value is served separately as `canonical_rarity`,
untouched by any of this. It is the only honest source of an *underlying*
rarity for a print whose own token names a special printing category instead
of a scarcity tier (`SPカード`, `TR`), and it is NULL wherever the catalogue
established none - which a client must render as no rarity at all rather than
fill in.
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
from app.services.market_index_change import get_index_change_7d_for_prints
from app.services.print_market_index import get_market_index_for_prints
from app.services.rarity_facets import facet_values, filter_tokens

SortKey = Literal["card_code", "name", "index_desc", "index_asc", "updated"]
SORT_KEYS: tuple[SortKey, ...] = ("card_code", "name", "index_desc", "index_asc", "updated")

_INDEX_SORTS = {"index_desc", "index_asc"}


def effective_rarity(print_row: CardPrint, canonical: CanonicalCard) -> str | None:
    """The rarity to serve for one exact printing.

    `card_prints.official_rarity` is Bandai's own value for *this* catalogue
    entry and is the authority. `canonical_cards.rarity` is a card-level
    summary that the catalogue may not establish at all, in which case it is
    NULL by design (migration c7e91a4d2b60 - see
    app.services.canonical_import_apply "THE RARITY PROBLEM, AS RESOLVED").

    Falling back to the canonical value rather than replacing it keeps every
    pre-import print serving exactly what it served before: those rows carry
    the same token in both columns, so the resolution is a no-op for them.

    Returns None when neither column holds a value. Nothing is derived,
    inferred from a sibling print, or defaulted - an unknown rarity stays
    unknown, and the caller renders nothing for it.
    """
    official = (print_row.official_rarity or "").strip()
    if official:
        return official
    return canonical.rarity


def effective_rarity_sql():
    """`effective_rarity` as a SQL expression, for filtering and faceting.

    Kept beside the Python version on purpose: the two must agree, or the
    catalogue would offer a facet value that matches nothing, or hide a print
    whose own tile displays the very rarity being filtered on. `nullif(trim(
    ...), '')` reproduces the Python `.strip()` emptiness test, and both
    `trim` and `nullif` mean the same thing on PostgreSQL and on the SQLite
    the test suite runs against.
    """
    return func.coalesce(
        func.nullif(func.trim(CardPrint.official_rarity), ""),
        CanonicalCard.rarity,
    )


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
        rarity=effective_rarity(print_row, canonical),
        canonical_rarity=canonical.rarity,
        card_type=canonical.card_type,
        colors=canonical.colors,
        language=print_row.language,
        treatment=print_row.treatment,
        release_product_code=print_row.release_product_code,
        original_set_code=canonical.original_set_code,
        official_asset_variant=print_row.official_asset_variant,
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
    market_index_change_7d_pct: float | None = None,
) -> PrintCatalogueItemOut:
    return PrintCatalogueItemOut(
        card_print_id=print_row.id,
        canonical_card_id=canonical.id,
        card_code=canonical.card_code,
        name_en=canonical.name_en,
        name_jp=canonical.name_jp,
        rarity=effective_rarity(print_row, canonical),
        canonical_rarity=canonical.rarity,
        card_type=canonical.card_type,
        treatment=print_row.treatment,
        language=print_row.language,
        release_product_code=print_row.release_product_code,
        original_set_code=canonical.original_set_code,
        official_asset_variant=print_row.official_asset_variant,
        image_url=print_row.image_url,
        display_image=display_image,
        verification_status=print_row.verification_status,
        market_index=market_index,
        source_coverage=_source_coverage(market_index),
        latest_observation_at=market_index.freshest_observation_at,
        market_index_change_7d_pct=market_index_change_7d_pct,
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
        # Matched against the same value the tile displays (see
        # effective_rarity), never against the card-level column alone - a
        # print whose rarity comes from its own catalogue entry must be
        # reachable by filtering on the rarity it shows.
        #
        # IN, not =, because one collector-facing value can cover more than one
        # published token: `SP CARD` reaches both `SPカード` and `SP P`, so the
        # single SP Card option selects the whole category rather than the
        # larger half of it. Every other value expands to itself, so this stays
        # an equality match for them - see app.services.rarity_facets.
        stmt = stmt.where(effective_rarity_sql().in_(filter_tokens(rarity)))
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
    # One more page-wide query, in the same batched style as the three above:
    # the seven-day baselines for this page, keyed off the already-computed
    # current indices so the comparison's two sides can never be derived from
    # different values. Never per item.
    change_by_print = get_index_change_7d_for_prints(db, page_index_by_print)
    items = [
        _to_catalogue_item(
            p,
            canonical_by_id[p.canonical_card_id],
            page_index_by_print[p.id],
            display_by_print.get(p.id),
            change_by_print.get(p.id),
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
    # Same rule as treatments above, for the same reason: a print whose rarity
    # the catalogue does not establish at all contributes no facet value.
    # Without the IS NOT NULL filter, DISTINCT would return NULL as if it were
    # a selectable rarity - and no synthetic "Unknown" bucket is invented for
    # it either.
    #
    # Faceted on effective_rarity_sql(), the very expression `?rarity=` filters
    # on and the tiles display, so every offered value selects at least one
    # print and every displayed value is offered.
    rarity_expr = effective_rarity_sql()
    stored_rarities = db.scalars(
        select(rarity_expr)
        .select_from(CardPrint)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(active, rarity_expr.is_not(None))
        .distinct()
        .order_by(rarity_expr)
    ).all()
    # Folded through the alias map so tokens that name one collector concept
    # are offered once - `SPカード` and `SP P` become a single `SP CARD`
    # option, whose population is the sum of both because `?rarity=` expands
    # the same way in _apply_filters. Deduplication happens after folding, so
    # the option count drops but no print becomes unreachable. Everything else
    # folds to itself.
    rarities = facet_values(list(stored_rarities))
    return PrintCatalogueFacetsOut(
        treatments=list(treatments),
        rarities=list(rarities),
        languages=list(languages),
        verification_statuses=list(verification_statuses),
    )
