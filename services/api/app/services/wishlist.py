"""Wishlist / acquisition tracker: cards a user wants to buy, at what price,
and whether the current market has hit that price. Reuses the same
latest-price-observation lookup as portfolio_valuation.py (Yuyu-Tei sell/buy,
SNKRDUNK floor) - no new price collection, this only reads what
refresh_prices has already recorded.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models import Card, CollectionItem, PriceObservation, WishlistItem
from app.models.wishlist_item import WISHLIST_STATUSES
from app.schemas import WishlistItemListOut, WishlistItemOut, WishlistLatestPricesOut, WishlistSummaryOut
from app.services.collector import get_tags_for_cards
from app.services.latest_prices import get_latest_price_map

# Same (source name, price_type) pairs backing each valuation perspective
# used across portfolio_valuation.py/market_signals.py.
YUYUTEI_SELL = ("yuyutei", "sell")
YUYUTEI_BUY = ("yuyutei", "buy")
SNKRDUNK_FLOOR = ("snkrdunk", "floor")

# A wishlist item is still being actively pursued in these two statuses -
# "purchased"/"passed"/"removed" are resolved/historical, so budget totals
# and the live target-hit count only look at this set.
ACTIVE_STATUSES = ("watching", "target_hit")


def resolve_preferred_current_price(
    preferred_source: str | None,
    yuyutei_sell: int | None,
    yuyutei_buy: int | None,
    snkrdunk_floor: int | None,
) -> tuple[int | None, str | None]:
    """preferred_source is free text (yuyutei, snkrdunk, local_shop, card_show,
    other, ...), not an enum - only "yuyutei"/"snkrdunk" map to a specific
    live price series. Anything else (blank, or a non-market source with no
    price observations of its own) falls back to the same default order:
    SNKRDUNK floor, then Yuyu-Tei sell."""
    normalized = (preferred_source or "").strip().lower()
    if normalized == "snkrdunk":
        return (snkrdunk_floor, "snkrdunk_floor") if snkrdunk_floor is not None else (None, None)
    if normalized == "yuyutei":
        return (yuyutei_sell, "yuyutei_sell") if yuyutei_sell is not None else (None, None)
    if snkrdunk_floor is not None:
        return snkrdunk_floor, "snkrdunk_floor"
    if yuyutei_sell is not None:
        return yuyutei_sell, "yuyutei_sell"
    return None, None


def compute_target_hit(target_buy_price_jpy: int | None, current_price_jpy: int | None) -> bool:
    if target_buy_price_jpy is None or current_price_jpy is None:
        return False
    return current_price_jpy <= target_buy_price_jpy


def compute_gap_to_target(
    current_price_jpy: int | None, target_buy_price_jpy: int | None
) -> tuple[int | None, float | None]:
    """Positive gap = current price is still above target (target not hit);
    zero/negative = at or below target."""
    if current_price_jpy is None or target_buy_price_jpy is None:
        return None, None
    gap_jpy = current_price_jpy - target_buy_price_jpy
    gap_pct = round(gap_jpy / target_buy_price_jpy * 100, 2) if target_buy_price_jpy else None
    return gap_jpy, gap_pct


def find_conflicting_wishlist_item(
    db: Session,
    user_id: int,
    card_id: int,
    preferred_condition: str | None,
    preferred_source: str | None,
    *,
    exclude_id: int | None = None,
) -> WishlistItem | None:
    """Service-layer enforcement of "one non-removed wishlist entry per
    (card, preferred_condition, preferred_source)". Not a DB-level partial
    unique index - preferred_condition/preferred_source are nullable, and a
    standard SQL unique index treats NULL as distinct from any other NULL, so
    it would silently fail to catch the common case where both are blank.
    This check uses IS NULL, so it catches that case correctly."""
    filters = [
        WishlistItem.user_id == user_id,
        WishlistItem.card_id == card_id,
        WishlistItem.status != "removed",
    ]
    filters.append(
        WishlistItem.preferred_condition.is_(None)
        if preferred_condition is None
        else WishlistItem.preferred_condition == preferred_condition
    )
    filters.append(
        WishlistItem.preferred_source.is_(None)
        if preferred_source is None
        else WishlistItem.preferred_source == preferred_source
    )
    if exclude_id is not None:
        filters.append(WishlistItem.id != exclude_id)
    return db.scalar(select(WishlistItem).where(*filters))


def get_latest_prices_by_card(
    db: Session, card_ids: set[int]
) -> dict[int, dict[tuple[str, str], PriceObservation]]:
    """Thin wrapper over app.services.latest_prices.get_latest_price_map,
    kept as its own name here since api/wishlist.py and this module's own
    get_wishlist_items already call it by this name."""
    return get_latest_price_map(db, card_ids)


def get_owned_quantities_by_card(db: Session, user_id: int, card_ids: set[int]) -> dict[int, int]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(CollectionItem.card_id, func.sum(CollectionItem.quantity))
        .where(CollectionItem.card_id.in_(card_ids), CollectionItem.user_id == user_id)
        .group_by(CollectionItem.card_id)
    ).all()
    return {card_id: int(qty or 0) for card_id, qty in rows}


def build_wishlist_item_out(
    item: WishlistItem,
    card: Card,
    card_latest: dict[tuple[str, str], PriceObservation],
    owned_quantity: int,
    tags: list,
) -> WishlistItemOut:
    yuyutei_sell_obs = card_latest.get(YUYUTEI_SELL)
    yuyutei_buy_obs = card_latest.get(YUYUTEI_BUY)
    snkrdunk_floor_obs = card_latest.get(SNKRDUNK_FLOOR)

    yuyutei_sell = yuyutei_sell_obs.price_jpy if yuyutei_sell_obs is not None else None
    yuyutei_buy = yuyutei_buy_obs.price_jpy if yuyutei_buy_obs is not None else None
    snkrdunk_floor = snkrdunk_floor_obs.price_jpy if snkrdunk_floor_obs is not None else None

    current_price_jpy, current_price_source = resolve_preferred_current_price(
        item.preferred_source, yuyutei_sell, yuyutei_buy, snkrdunk_floor
    )
    target_hit = compute_target_hit(item.target_buy_price_jpy, current_price_jpy)
    gap_jpy, gap_pct = compute_gap_to_target(current_price_jpy, item.target_buy_price_jpy)

    return WishlistItemOut(
        id=item.id,
        card_id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        priority=item.priority,
        status=item.status,
        target_buy_price_jpy=item.target_buy_price_jpy,
        max_buy_price_jpy=item.max_buy_price_jpy,
        preferred_condition=item.preferred_condition,
        preferred_source=item.preferred_source,
        desired_quantity=item.desired_quantity,
        acquired_quantity=item.acquired_quantity,
        acquired_collection_item_id=item.acquired_collection_item_id,
        notes=item.notes,
        owned_quantity=owned_quantity,
        latest_prices=WishlistLatestPricesOut(
            yuyutei_sell=yuyutei_sell, yuyutei_buy=yuyutei_buy, snkrdunk_floor=snkrdunk_floor
        ),
        preferred_current_price_jpy=current_price_jpy,
        preferred_current_price_source=current_price_source,
        target_hit=target_hit,
        gap_to_target_jpy=gap_jpy,
        gap_to_target_pct=gap_pct,
        tags=tags,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def get_wishlist_items(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    priority: str | None = None,
    card_code: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    target_hit: bool | None = None,
    owned: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> WishlistItemListOut:
    filters = [WishlistItem.user_id == user_id]
    if status is not None:
        filters.append(WishlistItem.status == status)
    if priority is not None:
        filters.append(WishlistItem.priority == priority)

    query = select(WishlistItem).join(Card, WishlistItem.card_id == Card.id).where(*filters)
    if card_code is not None:
        query = query.where(Card.card_code == card_code)
    if set_code is not None:
        query = query.where(Card.set_code == set_code)
    if rarity is not None:
        query = query.where(Card.rarity == rarity)

    items = db.scalars(query.order_by(WishlistItem.id)).all()
    if not items:
        return WishlistItemListOut(
            items=[], total=0, limit=limit, offset=offset,
            pagination=pagination_response([], 0, limit, offset),
        )

    card_ids = {i.card_id for i in items}
    cards_by_id = {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}
    latest_by_card = get_latest_prices_by_card(db, card_ids)
    owned_by_card = get_owned_quantities_by_card(db, user_id, card_ids)
    tags_by_card = get_tags_for_cards(db, card_ids, user_id=user_id)

    built = [
        build_wishlist_item_out(
            item,
            cards_by_id[item.card_id],
            latest_by_card.get(item.card_id, {}),
            owned_by_card.get(item.card_id, 0),
            tags_by_card.get(item.card_id, []),
        )
        for item in items
    ]

    if target_hit is not None:
        built = [b for b in built if b.target_hit == target_hit]
    if owned is not None:
        built = [b for b in built if (b.owned_quantity > 0) == owned]

    total = len(built)
    page = built[offset : offset + limit]
    return WishlistItemListOut(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(page, total, limit, offset),
    )


def get_wishlist_summary(db: Session, user_id: int) -> WishlistSummaryOut:
    all_items = get_wishlist_items(db, user_id, limit=1_000_000, offset=0).items

    by_status = {s: 0 for s in WISHLIST_STATUSES}
    for it in all_items:
        by_status[it.status] = by_status.get(it.status, 0) + 1

    non_removed = [it for it in all_items if it.status != "removed"]
    active = [it for it in all_items if it.status in ACTIVE_STATUSES]

    grail_count = sum(1 for it in non_removed if it.priority == "grail")
    high_priority_count = sum(1 for it in non_removed if it.priority == "high")
    total_target_budget_jpy = sum(it.target_buy_price_jpy or 0 for it in active)
    total_max_budget_jpy = sum(it.max_buy_price_jpy or 0 for it in active)
    items_owned_already = sum(1 for it in non_removed if it.owned_quantity > 0)
    items_with_target_hit = sum(1 for it in active if it.target_hit)

    return WishlistSummaryOut(
        total_wishlist_items=len(all_items),
        watching=by_status["watching"],
        target_hit=by_status["target_hit"],
        purchased=by_status["purchased"],
        passed=by_status["passed"],
        removed=by_status["removed"],
        grail_count=grail_count,
        high_priority_count=high_priority_count,
        total_target_budget_jpy=total_target_budget_jpy,
        total_max_budget_jpy=total_max_budget_jpy,
        items_owned_already=items_owned_already,
        items_with_target_hit=items_with_target_hit,
    )
