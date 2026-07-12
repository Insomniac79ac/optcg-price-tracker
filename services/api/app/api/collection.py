from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, CollectionItem, PortfolioValuationSnapshot
from app.models.collection_item import COLLECTION_ITEM_STATUSES
from app.schemas import (
    CollectionImportPreviewRowOut,
    CollectionImportResponseOut,
    CollectionImportRowErrorOut,
    CollectionImportSummaryOut,
    CollectionItemCreateIn,
    CollectionItemListOut,
    CollectionItemOut,
    CollectionItemUpdateIn,
    CollectionSummaryOut,
    PortfolioValuationOut,
    PortfolioValuationSnapshotOut,
)
from app.services.collection_csv import (
    IMPORT_MODES,
    export_collection_csv,
    export_filename,
    import_collection_csv,
)
from app.services.portfolio_valuation import get_portfolio_valuation

router = APIRouter(prefix="/collection", tags=["collection"])


def _to_out(item: CollectionItem, card: Card) -> CollectionItemOut:
    return CollectionItemOut(
        id=item.id,
        card_id=item.card_id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        quantity=item.quantity,
        condition_label=item.condition_label,
        purchase_price_jpy=item.purchase_price_jpy,
        purchase_date=item.purchase_date,
        purchase_source=item.purchase_source,
        target_sell_price_jpy=item.target_sell_price_jpy,
        notes=item.notes,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _get_item_or_404(db: Session, item_id: int) -> CollectionItem:
    item = db.get(CollectionItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Collection item not found")
    return item


def _get_card_or_404(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("", response_model=CollectionItemListOut)
def list_collection_items(
    status: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    card_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in COLLECTION_ITEM_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(COLLECTION_ITEM_STATUSES)}",
        )

    filters = []
    if status is not None:
        filters.append(CollectionItem.status == status)
    if card_code is not None:
        filters.append(Card.card_code == card_code)
    if card_id is not None:
        filters.append(CollectionItem.card_id == card_id)

    base = select(CollectionItem).join(Card, CollectionItem.card_id == Card.id).where(*filters)
    count_base = (
        select(func.count())
        .select_from(CollectionItem)
        .join(Card, CollectionItem.card_id == Card.id)
        .where(*filters)
    )

    total = db.scalar(count_base) or 0
    items = db.scalars(
        base.order_by(CollectionItem.id).limit(limit).offset(offset)
    ).all()

    card_ids = {item.card_id for item in items}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }

    out_items = [_to_out(item, cards_by_id[item.card_id]) for item in items]
    return CollectionItemListOut(items=out_items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=CollectionSummaryOut)
def get_collection_summary(db: Session = Depends(get_db)):
    items = db.scalars(select(CollectionItem)).all()

    total_items = len(items)
    total_quantity = sum(item.quantity for item in items)
    total_cost_basis_jpy = sum(
        item.purchase_price_jpy * item.quantity
        for item in items
        if item.purchase_price_jpy is not None
    )
    items_with_purchase_price = sum(1 for item in items if item.purchase_price_jpy is not None)
    items_missing_purchase_price = total_items - items_with_purchase_price

    items_by_status = {status: 0 for status in COLLECTION_ITEM_STATUSES}
    for item in items:
        items_by_status[item.status] = items_by_status.get(item.status, 0) + 1

    return CollectionSummaryOut(
        total_items=total_items,
        total_quantity=total_quantity,
        total_cost_basis_jpy=total_cost_basis_jpy,
        items_with_purchase_price=items_with_purchase_price,
        items_missing_purchase_price=items_missing_purchase_price,
        items_by_status=items_by_status,
    )


@router.get("/valuation", response_model=PortfolioValuationOut)
def get_collection_valuation(db: Session = Depends(get_db)):
    return get_portfolio_valuation(db)


@router.get("/valuation/history", response_model=list[PortfolioValuationSnapshotOut])
def get_collection_valuation_history(
    days: str = Query(default="30"),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    filters = []
    if days != "all":
        try:
            days_int = int(days)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="days must be a positive integer or 'all'"
            )
        if days_int <= 0:
            raise HTTPException(
                status_code=400, detail="days must be a positive integer or 'all'"
            )
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_int)
        filters.append(PortfolioValuationSnapshot.created_at >= cutoff)

    snapshots = db.scalars(
        select(PortfolioValuationSnapshot)
        .where(*filters)
        .order_by(PortfolioValuationSnapshot.created_at.asc())
        .limit(limit)
    ).all()

    return [PortfolioValuationSnapshotOut.model_validate(s) for s in snapshots]


@router.get("/export.csv")
def export_collection_items_csv(db: Session = Depends(get_db)):
    csv_text = export_collection_csv(db)
    filename = export_filename()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import.csv", response_model=CollectionImportResponseOut)
async def import_collection_items_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    mode: str = Query(default="upsert"),
    db: Session = Depends(get_db),
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
        result = import_collection_csv(db, csv_text, dry_run=dry_run, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CollectionImportResponseOut(
        dry_run=result.dry_run,
        mode=result.mode,
        summary=CollectionImportSummaryOut(
            total_rows=result.total_rows,
            valid_rows=result.valid_rows,
            error_rows=result.error_rows,
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
        ),
        errors=[
            CollectionImportRowErrorOut(
                row_number=e.row_number, card_code=e.card_code, error=e.error
            )
            for e in result.errors
        ],
        preview=[
            CollectionImportPreviewRowOut(
                row_number=p.row_number,
                card_code=p.card_code,
                matched_card_id=p.matched_card_id,
                action=p.action,
                quantity=p.quantity,
                status=p.status,
            )
            for p in result.preview
        ],
    )


@router.post("", response_model=CollectionItemOut, status_code=201)
def create_collection_item(body: CollectionItemCreateIn, db: Session = Depends(get_db)):
    card = _get_card_or_404(db, body.card_id)

    item = CollectionItem(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_out(item, card)


@router.get("/{item_id}", response_model=CollectionItemOut)
def get_collection_item(item_id: int, db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    card = db.get(Card, item.card_id)
    return _to_out(item, card)


@router.patch("/{item_id}", response_model=CollectionItemOut)
def update_collection_item(
    item_id: int, body: CollectionItemUpdateIn, db: Session = Depends(get_db)
):
    item = _get_item_or_404(db, item_id)

    updates = body.model_dump(exclude_unset=True)
    if "card_id" in updates:
        _get_card_or_404(db, updates["card_id"])

    for field, value in updates.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    card = db.get(Card, item.card_id)
    return _to_out(item, card)


@router.delete("/{item_id}", status_code=204)
def delete_collection_item(item_id: int, db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    db.delete(item)
    db.commit()
    return None
