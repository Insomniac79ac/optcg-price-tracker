from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.collection import _to_out as _collection_item_to_out
from app.auth import require_current_user
from app.db import get_db
from app.models import Card, CollectionItem, User, WishlistItem
from app.models.wishlist_item import WISHLIST_PRIORITIES, WISHLIST_STATUSES
from app.schemas import (
    WishlistConvertToCollectionIn,
    WishlistConvertToCollectionOut,
    WishlistImportPreviewRowOut,
    WishlistImportResponseOut,
    WishlistImportRowErrorOut,
    WishlistImportSummaryOut,
    WishlistItemCreateIn,
    WishlistItemListOut,
    WishlistItemOut,
    WishlistItemUpdateIn,
    WishlistMarkPurchasedIn,
    WishlistSummaryOut,
)
from app.services.activity_timeline import record_activity_event
from app.services.app_logging import record_app_log
from app.services.collector import get_tags_for_cards
from app.services.wishlist import (
    build_wishlist_item_out,
    find_conflicting_wishlist_item,
    get_latest_prices_by_card,
    get_owned_quantities_by_card,
    get_wishlist_items,
    get_wishlist_summary,
)
from app.services.wishlist_csv import (
    IMPORT_MODES,
    export_wishlist_csv,
    export_filename,
    import_wishlist_csv,
)

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


def _get_card_or_404(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _get_wishlist_item_or_404(db: Session, item_id: int, user: User) -> WishlistItem:
    item = db.get(WishlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return item


def _get_collection_item_or_404(db: Session, item_id: int, user: User) -> CollectionItem:
    item = db.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Collection item not found")
    return item


def _to_single_out(db: Session, item: WishlistItem, user: User) -> WishlistItemOut:
    card = db.get(Card, item.card_id)
    latest_by_card = get_latest_prices_by_card(db, {item.card_id})
    owned_by_card = get_owned_quantities_by_card(db, user.id, {item.card_id})
    tags_by_card = get_tags_for_cards(db, {item.card_id}, user_id=user.id)
    return build_wishlist_item_out(
        item,
        card,
        latest_by_card.get(item.card_id, {}),
        owned_by_card.get(item.card_id, 0),
        tags_by_card.get(item.card_id, []),
    )


@router.get("", response_model=WishlistItemListOut)
def list_wishlist_items(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    target_hit: bool | None = Query(default=None),
    owned: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    if status is not None and status not in WISHLIST_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of {list(WISHLIST_STATUSES)}"
        )
    if priority is not None and priority not in WISHLIST_PRIORITIES:
        raise HTTPException(
            status_code=400, detail=f"Invalid priority. Must be one of {list(WISHLIST_PRIORITIES)}"
        )

    return get_wishlist_items(
        db,
        user.id,
        status=status,
        priority=priority,
        card_code=card_code,
        set_code=set_code,
        rarity=rarity,
        target_hit=target_hit,
        owned=owned,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=WishlistSummaryOut)
def get_wishlist_summary_endpoint(
    db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    return get_wishlist_summary(db, user.id)


@router.get("/export.csv")
def export_wishlist_items_csv(
    db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    csv_text = export_wishlist_csv(db, user_id=user.id)
    filename = export_filename()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import.csv", response_model=WishlistImportResponseOut)
async def import_wishlist_items_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    mode: str = Query(default="upsert"),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    if mode not in IMPORT_MODES:
        raise HTTPException(
            status_code=400, detail=f"Invalid mode. Must be one of {list(IMPORT_MODES)}"
        )

    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"File is not valid UTF-8: {exc}") from exc

    try:
        result = import_wishlist_csv(db, csv_text, dry_run=dry_run, mode=mode, user_id=user.id)
    except ValueError as exc:
        record_app_log(
            "error",
            "api",
            "import",
            f"Wishlist CSV import failed: {exc}",
            context={"dry_run": dry_run, "mode": mode},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not dry_run and result.error_rows > 0:
        record_app_log(
            "warning",
            "api",
            "import",
            f"Wishlist CSV import completed with {result.error_rows} row error(s).",
            context={"mode": mode, "total_rows": result.total_rows, "error_rows": result.error_rows},
        )

    return WishlistImportResponseOut(
        dry_run=result.dry_run,
        mode=result.mode,
        summary=WishlistImportSummaryOut(
            total_rows=result.total_rows,
            valid_rows=result.valid_rows,
            error_rows=result.error_rows,
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
        ),
        errors=[
            WishlistImportRowErrorOut(row_number=e.row_number, card_code=e.card_code, error=e.error)
            for e in result.errors
        ],
        preview=[
            WishlistImportPreviewRowOut(
                row_number=p.row_number,
                card_code=p.card_code,
                matched_card_id=p.matched_card_id,
                action=p.action,
                priority=p.priority,
                status=p.status,
            )
            for p in result.preview
        ],
    )


@router.post("", response_model=WishlistItemOut, status_code=201)
def create_wishlist_item(
    body: WishlistItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    _get_card_or_404(db, body.card_id)

    conflict = find_conflicting_wishlist_item(
        db, user.id, body.card_id, body.preferred_condition, body.preferred_source
    )
    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "An active wishlist item already exists for this card with the same "
                "preferred condition/source"
            ),
        )

    item = WishlistItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)

    card = db.get(Card, item.card_id)
    record_activity_event(
        db,
        event_type="wishlist_item_added",
        event_source="wishlist",
        title=f"Added {card.name_en or card.card_code} to wishlist",
        card_id=item.card_id,
        wishlist_item_id=item.id,
    )

    return _to_single_out(db, item, user)


@router.get("/{wishlist_item_id}", response_model=WishlistItemOut)
def get_wishlist_item(
    wishlist_item_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    item = _get_wishlist_item_or_404(db, wishlist_item_id, user)
    return _to_single_out(db, item, user)


@router.patch("/{wishlist_item_id}", response_model=WishlistItemOut)
def update_wishlist_item(
    wishlist_item_id: int,
    body: WishlistItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_wishlist_item_or_404(db, wishlist_item_id, user)
    updates = body.model_dump(exclude_unset=True)

    next_status = updates.get("status", item.status)
    next_condition = updates.get("preferred_condition", item.preferred_condition)
    next_source = updates.get("preferred_source", item.preferred_source)
    if next_status != "removed":
        conflict = find_conflicting_wishlist_item(
            db, user.id, item.card_id, next_condition, next_source, exclude_id=item.id
        )
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "An active wishlist item already exists for this card with the same "
                    "preferred condition/source"
                ),
            )

    for field, value in updates.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return _to_single_out(db, item, user)


@router.delete("/{wishlist_item_id}", response_model=WishlistItemOut)
def delete_wishlist_item(
    wishlist_item_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    """Soft delete - sets status=removed rather than physically deleting the
    row, so acquired_collection_item_id linkage and history survive."""
    item = _get_wishlist_item_or_404(db, wishlist_item_id, user)
    item.status = "removed"
    db.commit()
    db.refresh(item)

    card = db.get(Card, item.card_id)
    record_activity_event(
        db,
        event_type="wishlist_item_removed",
        event_source="wishlist",
        title=f"Removed {card.name_en or card.card_code} from wishlist",
        card_id=item.card_id,
        wishlist_item_id=item.id,
    )

    return _to_single_out(db, item, user)


@router.post("/{wishlist_item_id}/mark-purchased", response_model=WishlistItemOut)
def mark_wishlist_item_purchased(
    wishlist_item_id: int,
    body: WishlistMarkPurchasedIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_wishlist_item_or_404(db, wishlist_item_id, user)
    _get_collection_item_or_404(db, body.collection_item_id, user)

    item.status = "purchased"
    item.acquired_collection_item_id = body.collection_item_id
    item.acquired_quantity = body.acquired_quantity

    db.commit()
    db.refresh(item)

    card = db.get(Card, item.card_id)
    record_activity_event(
        db,
        event_type="wishlist_item_purchased",
        event_source="wishlist",
        title=f"Marked {card.name_en or card.card_code} as purchased",
        message=f"Quantity: {item.acquired_quantity}",
        card_id=item.card_id,
        wishlist_item_id=item.id,
        collection_item_id=item.acquired_collection_item_id,
    )

    return _to_single_out(db, item, user)


@router.post("/{wishlist_item_id}/convert-to-collection", response_model=WishlistConvertToCollectionOut)
def convert_wishlist_item_to_collection(
    wishlist_item_id: int,
    body: WishlistConvertToCollectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_wishlist_item_or_404(db, wishlist_item_id, user)
    card = db.get(Card, item.card_id)

    collection_item = CollectionItem(
        user_id=user.id,
        card_id=item.card_id,
        quantity=body.quantity,
        condition_label=body.condition_label,
        purchase_price_jpy=body.purchase_price_jpy,
        purchase_date=body.purchase_date,
        purchase_source=body.purchase_source,
        target_sell_price_jpy=body.target_sell_price_jpy,
        status=body.status,
        notes=body.notes,
    )
    db.add(collection_item)
    db.flush()

    item.status = "purchased"
    item.acquired_collection_item_id = collection_item.id
    item.acquired_quantity = body.quantity

    db.commit()
    db.refresh(collection_item)
    db.refresh(item)

    record_activity_event(
        db,
        event_type="wishlist_item_converted",
        event_source="wishlist",
        title=f"Converted {card.name_en or card.card_code} from wishlist to collection",
        message=f"Quantity: {body.quantity}",
        card_id=item.card_id,
        wishlist_item_id=item.id,
        collection_item_id=collection_item.id,
    )

    return WishlistConvertToCollectionOut(
        wishlist_item=_to_single_out(db, item, user),
        collection_item=_collection_item_to_out(collection_item, card),
    )
