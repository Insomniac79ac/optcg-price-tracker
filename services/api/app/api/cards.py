from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_current_user, require_current_user_optional
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import Card, CardTag, CollectorTag, PriceObservation, Source, User
from app.schemas import CardCatalogueListOut, CardOut, MarketIndexOut, PriceObservationOut
from app.services.card_catalogue import SORT_KEYS, SortKey, get_catalogue_facets, list_catalogue
from app.services.collector import get_tags_for_cards
from app.services.market_index import get_market_index_for_card

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_card_out(card: Card, tags: list[CollectorTag]) -> CardOut:
    return CardOut(
        id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        image_url=card.image_url,
        tags=tags,
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
    )


def _get_card_or_404(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _get_tag_or_404(db: Session, tag_id: int, user: User) -> CollectorTag:
    tag = db.get(CollectorTag, tag_id)
    if tag is None or tag.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.get("/catalogue", response_model=CardCatalogueListOut)
def get_cards_catalogue(
    q: str | None = Query(default=None, min_length=1, max_length=128),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    language: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    sort: str = Query(default="card_code"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """The public, paginated, image-catalogue-ready card list - each item
    carries its Market Index summary already attached (see
    app.services.card_catalogue), so the frontend grid renders in one
    request instead of one request per card. Declared before GET
    /cards/{card_id} - both are single path-segment routes under /cards, and
    FastAPI/Starlette resolves them in declaration order, so this one must
    come first or "/cards/catalogue" would be swallowed by {card_id} (and
    fail int conversion) instead of ever reaching this handler."""
    if sort not in SORT_KEYS:
        raise HTTPException(
            status_code=400, detail=f"Invalid sort. Must be one of {list(SORT_KEYS)}"
        )

    items, total = list_catalogue(
        db,
        q=q,
        set_code=set_code,
        rarity=rarity,
        language=language,
        variant=variant,
        sort=sort,  # type: ignore[arg-type]
        limit=limit,
        offset=offset,
    )
    return CardCatalogueListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(items, total, limit, offset),
        facets=get_catalogue_facets(db),
    )


@router.get("", response_model=list[CardOut])
def list_cards(
    db: Session = Depends(get_db),
    user: User | None = Depends(require_current_user_optional),
):
    cards = db.scalars(select(Card)).all()
    tags_by_card = (
        get_tags_for_cards(db, {c.id for c in cards}, user_id=user.id) if user else {}
    )
    return [_to_card_out(c, tags_by_card.get(c.id, [])) for c in cards]


@router.get("/{card_id}", response_model=CardOut)
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(require_current_user_optional),
):
    card = _get_card_or_404(db, card_id)
    tags_by_card = get_tags_for_cards(db, {card_id}, user_id=user.id) if user else {}
    return _to_card_out(card, tags_by_card.get(card_id, []))


@router.get("/{card_id}/market-index", response_model=MarketIndexOut)
def get_card_market_index(card_id: int, db: Session = Depends(get_db)):
    """LEGACY, card_id-keyed market semantics - kept for backward
    compatibility with existing frontend routes only. When two card_prints
    (e.g. a base and a parallel treatment of the same canonical card) bridge
    through this same legacy card_id, their observations are NOT kept
    separate here - see app.services.market_index's card_id-partitioned
    latest-price lookup. New callers that need a single collectible print's
    Market Index must use GET /prints/{print_id}/market-index instead (see
    app.api.prints), which is card_print_id-scoped and never calls through
    this card-keyed implementation."""
    _get_card_or_404(db, card_id)
    return get_market_index_for_card(db, card_id)


@router.get("/{card_id}/prices", response_model=list[PriceObservationOut])
def get_card_prices(card_id: int, db: Session = Depends(get_db)):
    """LEGACY, card_id-keyed price history - kept for backward compatibility
    only. Returns every observation for this legacy card_id merged together,
    including observations belonging to different card_prints that happen to
    bridge through the same legacy row. New callers must use
    GET /prints/{print_id}/prices instead (see app.api.prints)."""
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    stmt = (
        select(PriceObservation, Source.name)
        .join(Source, Source.id == PriceObservation.source_id)
        .where(PriceObservation.card_id == card_id)
        .order_by(PriceObservation.observed_at.asc())
    )
    rows = db.execute(stmt).all()
    return [
        PriceObservationOut(
            id=observation.id,
            card_id=observation.card_id,
            source_id=observation.source_id,
            source=source_name,
            observed_at=observation.observed_at,
            price_type=observation.price_type,
            price_jpy=observation.price_jpy,
            condition_label=observation.condition_label,
            stock_status=observation.stock_status,
            listing_count=observation.listing_count,
            raw_snapshot_id=observation.raw_snapshot_id,
        )
        for observation, source_name in rows
    ]


@router.post("/{card_id}/tags/{tag_id}", response_model=CardOut)
def assign_card_tag(
    card_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    card = _get_card_or_404(db, card_id)
    _get_tag_or_404(db, tag_id, user)

    existing = db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag_id)
    )
    if existing is None:
        db.add(CardTag(card_id=card_id, tag_id=tag_id))
        db.commit()

    tags_by_card = get_tags_for_cards(db, {card_id}, user_id=user.id)
    return _to_card_out(card, tags_by_card.get(card_id, []))


@router.delete("/{card_id}/tags/{tag_id}", response_model=CardOut)
def unassign_card_tag(
    card_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    card = _get_card_or_404(db, card_id)
    _get_tag_or_404(db, tag_id, user)

    assignment = db.scalar(
        select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag_id)
    )
    if assignment is not None:
        db.delete(assignment)
        db.commit()

    tags_by_card = get_tags_for_cards(db, {card_id}, user_id=user.id)
    return _to_card_out(card, tags_by_card.get(card_id, []))
