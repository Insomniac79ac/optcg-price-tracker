from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import (
    Card,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorGroup,
    CollectorTag,
    PortfolioValuationSnapshot,
    User,
)
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
    ValuationMode,
)
from app.services.collection_csv import (
    IMPORT_MODES,
    export_collection_csv,
    export_filename,
    import_collection_csv,
)
from app.services.activity_timeline import record_activity_event
from app.services.app_logging import record_app_log
from app.services.collector import get_groups_for_collection_items, get_tags_for_collection_items
from app.services.grading import build_grading_submission_out, get_submissions_for_items
from app.services.portfolio_valuation import get_portfolio_valuation

router = APIRouter(prefix="/collection", tags=["collection"])


def _to_out(
    item: CollectionItem,
    card: Card,
    tags: list[CollectorTag] | None = None,
    groups: list[CollectorGroup] | None = None,
    grading_submissions: list | None = None,
) -> CollectionItemOut:
    submissions_out = [
        build_grading_submission_out(s, item, card) for s in (grading_submissions or [])
    ]
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
        tags=tags or [],
        groups=groups or [],
        grading_submissions=submissions_out,
        latest_grading_status=submissions_out[0].submission_status if submissions_out else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _to_out_single(db: Session, item: CollectionItem, card: Card) -> CollectionItemOut:
    tags = get_tags_for_collection_items(db, {item.id}).get(item.id, [])
    groups = get_groups_for_collection_items(db, {item.id}).get(item.id, [])
    submissions = get_submissions_for_items(db, {item.id}).get(item.id, [])
    return _to_out(item, card, tags, groups, submissions)


def _get_item_or_404(db: Session, item_id: int, user: User) -> CollectionItem:
    item = db.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Collection item not found")
    return item


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


def _get_group_or_404(db: Session, group_id: int, user: User) -> CollectorGroup:
    group = db.get(CollectorGroup, group_id)
    if group is None or group.user_id != user.id:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.get("", response_model=CollectionItemListOut)
def list_collection_items(
    status: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    card_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    if status is not None and status not in COLLECTION_ITEM_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(COLLECTION_ITEM_STATUSES)}",
        )

    filters = [CollectionItem.user_id == user.id]
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

    item_ids = {item.id for item in items}
    tags_by_item = get_tags_for_collection_items(db, item_ids)
    groups_by_item = get_groups_for_collection_items(db, item_ids)
    submissions_by_item = get_submissions_for_items(db, item_ids)

    out_items = [
        _to_out(
            item,
            cards_by_id[item.card_id],
            tags_by_item.get(item.id, []),
            groups_by_item.get(item.id, []),
            submissions_by_item.get(item.id, []),
        )
        for item in items
    ]
    return CollectionItemListOut(items=out_items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=CollectionSummaryOut)
def get_collection_summary(
    db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    items = db.scalars(select(CollectionItem).where(CollectionItem.user_id == user.id)).all()

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
def get_collection_valuation(
    valuation_mode: ValuationMode = Query(default="raw_market"),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    return get_portfolio_valuation(db, user_id=user.id, valuation_mode=valuation_mode)


@router.get("/valuation/history", response_model=list[PortfolioValuationSnapshotOut])
def get_collection_valuation_history(
    days: str = Query(default="30"),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    # Login-gated like the rest of /collection, but intentionally NOT
    # filtered by user - portfolio_valuation_snapshots is a single global
    # timeline produced by the admin-triggered snapshot job (see
    # snapshot_portfolio_valuation.py), not a per-user table. Every signed-in
    # user currently sees the same aggregate history; see the "explicit scope
    # boundary" note in the auth/deployment plan for why this stays global.
    _user: User = Depends(require_current_user),
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
def export_collection_items_csv(
    db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    csv_text = export_collection_csv(db, user_id=user.id)
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
        result = import_collection_csv(db, csv_text, dry_run=dry_run, mode=mode, user_id=user.id)
    except ValueError as exc:
        record_app_log(
            "error",
            "api",
            "import",
            f"Collection CSV import failed: {exc}",
            context={"dry_run": dry_run, "mode": mode},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not dry_run and result.error_rows > 0:
        record_app_log(
            "warning",
            "api",
            "import",
            f"Collection CSV import completed with {result.error_rows} row error(s).",
            context={"mode": mode, "total_rows": result.total_rows, "error_rows": result.error_rows},
        )

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
                tags=p.tags,
                groups=p.groups,
            )
            for p in result.preview
        ],
        tags_created=result.tags_created,
        groups_created=result.groups_created,
    )


@router.post("", response_model=CollectionItemOut, status_code=201)
def create_collection_item(
    body: CollectionItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    card = _get_card_or_404(db, body.card_id)

    item = CollectionItem(user_id=user.id, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)

    record_activity_event(
        db,
        event_type="collection_item_added",
        event_source="collection",
        title=f"Added {card.name_en or card.card_code} to collection",
        message=f"Quantity: {item.quantity}",
        card_id=item.card_id,
        collection_item_id=item.id,
    )

    return _to_out(item, card)


@router.get("/{item_id}", response_model=CollectionItemOut)
def get_collection_item(
    item_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    return _to_out_single(db, item, card)


@router.patch("/{item_id}", response_model=CollectionItemOut)
def update_collection_item(
    item_id: int,
    body: CollectionItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, item_id, user)

    updates = body.model_dump(exclude_unset=True)
    if "card_id" in updates:
        _get_card_or_404(db, updates["card_id"])

    previous_status = item.status
    for field, value in updates.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    card = db.get(Card, item.card_id)

    if "status" in updates and updates["status"] != previous_status:
        record_activity_event(
            db,
            event_type="collection_item_status_changed",
            event_source="collection",
            title=f"{card.name_en or card.card_code} marked as {item.status}",
            message=f"{previous_status} -> {item.status}",
            card_id=item.card_id,
            collection_item_id=item.id,
        )

    return _to_out_single(db, item, card)


@router.delete("/{item_id}", status_code=204)
def delete_collection_item(
    item_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    card_id = item.card_id
    card_label = (card.name_en or card.card_code) if card is not None else "item"

    db.delete(item)
    db.commit()

    record_activity_event(
        db,
        event_type="collection_item_removed",
        event_source="collection",
        title=f"Removed {card_label} from collection",
        card_id=card_id,
    )

    return None


@router.post("/{item_id}/tags/{tag_id}", response_model=CollectionItemOut)
def assign_collection_item_tag(
    item_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    _get_tag_or_404(db, tag_id, user)

    existing = db.scalar(
        select(CollectionItemTag).where(
            CollectionItemTag.collection_item_id == item_id, CollectionItemTag.tag_id == tag_id
        )
    )
    if existing is None:
        db.add(CollectionItemTag(collection_item_id=item_id, tag_id=tag_id))
        db.commit()

    return _to_out_single(db, item, card)


@router.delete("/{item_id}/tags/{tag_id}", response_model=CollectionItemOut)
def unassign_collection_item_tag(
    item_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    _get_tag_or_404(db, tag_id, user)

    assignment = db.scalar(
        select(CollectionItemTag).where(
            CollectionItemTag.collection_item_id == item_id, CollectionItemTag.tag_id == tag_id
        )
    )
    if assignment is not None:
        db.delete(assignment)
        db.commit()

    return _to_out_single(db, item, card)


@router.post("/{item_id}/groups/{group_id}", response_model=CollectionItemOut)
def assign_collection_item_group(
    item_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    _get_group_or_404(db, group_id, user)

    existing = db.scalar(
        select(CollectionItemGroup).where(
            CollectionItemGroup.collection_item_id == item_id,
            CollectionItemGroup.group_id == group_id,
        )
    )
    if existing is None:
        db.add(CollectionItemGroup(collection_item_id=item_id, group_id=group_id))
        db.commit()

    return _to_out_single(db, item, card)


@router.delete("/{item_id}/groups/{group_id}", response_model=CollectionItemOut)
def unassign_collection_item_group(
    item_id: int,
    group_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, item_id, user)
    card = db.get(Card, item.card_id)
    _get_group_or_404(db, group_id, user)

    assignment = db.scalar(
        select(CollectionItemGroup).where(
            CollectionItemGroup.collection_item_id == item_id,
            CollectionItemGroup.group_id == group_id,
        )
    )
    if assignment is not None:
        db.delete(assignment)
        db.commit()

    return _to_out_single(db, item, card)
