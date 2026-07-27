"""Query/filter/sort/paginate composition for the public /cards catalogue
(GET /cards/catalogue) - the batch-compatible mechanism Market Index v1 uses
so the frontend catalogue grid never issues one Market Index request per
card (see app.services.market_index's module docstring "Batch-safe by
construction").

Card-code/name/updated_at sorts stay a single paginated SQL query (limit/
offset pushed to the database) - Market Index isn't computed until after
that page is chosen, so those sorts are as cheap as any other paginated list
endpoint in this app. index_desc/index_asc are the one case that can't be
pushed to SQL (index_value_jpy is computed on read, not a column - see
app.services.market_index's "Compute-on-read, not persisted"): those sorts
fetch every *filtered* card id (still one query, just not a page of it),
batch-compute their indices in the same fixed number of queries
get_market_index_for_cards always uses regardless of card count, sort in
Python, then slice the page. Never a per-card query loop either way.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Card
from app.schemas import CardCatalogueFacetsOut, CardCatalogueItemOut
from app.services.market_index import get_market_index_for_cards

SortKey = Literal["card_code", "name", "index_desc", "index_asc", "updated"]
SORT_KEYS: tuple[SortKey, ...] = ("card_code", "name", "index_desc", "index_asc", "updated")

_INDEX_SORTS = {"index_desc", "index_asc"}


def _display_name(card: Card) -> str:
    return card.name_en or card.name_jp or ""


def _apply_filters(
    stmt,
    *,
    q: str | None,
    set_code: str | None,
    rarity: str | None,
    language: str | None,
    variant: str | None,
):
    stmt = stmt.where(Card.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Card.name_en.ilike(like),
                Card.name_jp.ilike(like),
                Card.card_code.ilike(like),
            )
        )
    if set_code:
        stmt = stmt.where(Card.set_code == set_code)
    if rarity:
        stmt = stmt.where(Card.rarity == rarity)
    if language:
        stmt = stmt.where(Card.language == language)
    if variant:
        stmt = stmt.where(Card.variant == variant)
    return stmt


def _to_catalogue_item(card: Card, market_index) -> CardCatalogueItemOut:
    return CardCatalogueItemOut(
        id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        image_url=card.image_url,
        tags=[],
        release_date=card.release_date,
        artist=card.artist,
        character=card.character,
        color=card.color,
        card_type=card.card_type,
        cost=card.cost,
        power=card.power,
        counter=card.counter,
        attribute=card.attribute,
        effect_text=card.effect_text,
        trigger_text=card.trigger_text,
        created_at=card.created_at,
        updated_at=card.updated_at,
        market_index=market_index,
    )


def list_catalogue(
    db: Session,
    *,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    language: str | None = None,
    variant: str | None = None,
    sort: SortKey = "card_code",
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[CardCatalogueItemOut], int]:
    base = _apply_filters(
        select(Card), q=q, set_code=set_code, rarity=rarity, language=language, variant=variant
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    if total == 0:
        return [], 0

    if sort in _INDEX_SORTS:
        all_cards = db.scalars(base.order_by(Card.id.asc())).all()
        index_by_card = get_market_index_for_cards(db, [c.id for c in all_cards])

        def sort_key(card: Card):
            index = index_by_card[card.id]
            value = index.index_value_jpy
            # None (index unavailable) always sorts after every priced card,
            # in both directions - deterministic secondary order by id.
            missing = value is None
            magnitude = value if value is not None else 0
            if sort == "index_desc":
                return (missing, -magnitude, card.id)
            return (missing, magnitude, card.id)

        all_cards.sort(key=sort_key)
        page_cards = all_cards[offset : offset + limit]
        page_index_by_card = {c.id: index_by_card[c.id] for c in page_cards}
    else:
        ordered = base
        if sort == "name":
            ordered = ordered.order_by(
                func.coalesce(Card.name_en, Card.name_jp).asc(), Card.id.asc()
            )
        elif sort == "updated":
            ordered = ordered.order_by(Card.updated_at.desc(), Card.id.asc())
        else:  # "card_code"
            ordered = ordered.order_by(Card.card_code.asc(), Card.id.asc())

        page_cards = db.scalars(ordered.limit(limit).offset(offset)).all()
        page_index_by_card = get_market_index_for_cards(db, [c.id for c in page_cards])

    items = [_to_catalogue_item(c, page_index_by_card[c.id]) for c in page_cards]
    return items, total


def get_catalogue_facets(db: Session) -> CardCatalogueFacetsOut:
    """Distinct set_code/rarity/language/variant values actually present
    among active cards - four cheap indexed-column DISTINCT queries, run
    once per catalogue request regardless of result size, never per card.
    Deliberately ignores the request's own filters (see
    CardCatalogueFacetsOut's docstring) - a dropdown always lists every
    option that has at least one card somewhere in the catalog."""
    active = Card.is_active.is_(True)
    set_codes = db.scalars(
        select(Card.set_code).where(active).distinct().order_by(Card.set_code)
    ).all()
    rarities = db.scalars(
        select(Card.rarity).where(active).distinct().order_by(Card.rarity)
    ).all()
    languages = db.scalars(
        select(Card.language).where(active).distinct().order_by(Card.language)
    ).all()
    variants = db.scalars(
        select(Card.variant).where(active, Card.variant.is_not(None)).distinct().order_by(Card.variant)
    ).all()
    return CardCatalogueFacetsOut(
        set_codes=list(set_codes),
        rarities=list(rarities),
        languages=list(languages),
        variants=list(variants),
    )
