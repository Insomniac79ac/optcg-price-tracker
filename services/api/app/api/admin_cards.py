from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import Card
from app.schemas import (
    AdminCardListResponseOut,
    AdminCardListSummaryOut,
    AdminCardOut,
    CardCatalogImportResponseOut,
    CardImageImportResponseOut,
)
from app.services.app_logging import record_app_log
from app.services.cache import delete_cache_prefix
from app.services.card_catalog_import import export_filename, import_cards_csv, iter_cards_csv_rows
from app.services.card_image_import import image_import_template_csv, import_card_images_csv

router = APIRouter(prefix="/admin/cards", tags=["admin"], dependencies=[Depends(require_admin_token)])

# The canonical cards table backs nearly every other cached read surface -
# collection/wishlist/market analytics all resolve card_code/name/rarity/
# set_code through it - so a real (non-dry-run) catalog import invalidates
# broadly, the same way a price refresh or market workflow does. See 'Cache
# invalidation' in docs/operations.md.
_CARD_CATALOG_CACHE_INVALIDATES = (
    "dashboard",
    "collection_valuation",
    "collection_history",
    "collection_analytics",
    "wishlist_analytics",
    "market_signals",
    "market_signal_events",
    "market_opportunities",
    "market_report",
    "market_reports",
    "wishlist",
    "wishlist_summary",
    "grading_summary",
    "sell_decisions",
    "buy_decisions",
    "grading_analytics",
    "portfolio_risk",
    "analytics_digest",
    "admin/catalog_coverage",
    "admin/price_source_health",
)

# Metadata fields considered when deciding whether a card is "missing
# metadata" for GET /admin/cards' summary/missing_metadata filter - the
# catalog-enrichment columns added alongside the CSV importer, not the
# original identity columns (card_code/set_code/rarity/variant/language)
# which are never blank on a valid row.
_METADATA_FIELDS = (
    "artist",
    "character",
    "color",
    "card_type",
    "cost",
    "power",
    "counter",
    "attribute",
    "effect_text",
    "trigger_text",
)


def _is_missing_metadata(card: Card) -> bool:
    return all(getattr(card, field) is None for field in _METADATA_FIELDS)


@router.get("", response_model=AdminCardListResponseOut)
def list_cards(
    q: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    language: str | None = Query(default=None),
    missing_metadata: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    all_cards = list(db.scalars(select(Card).order_by(Card.card_code, Card.set_code, Card.id)).all())

    by_set: dict[str, int] = {}
    by_rarity: dict[str, int] = {}
    missing_metadata_count = 0
    for card in all_cards:
        by_set[card.set_code] = by_set.get(card.set_code, 0) + 1
        by_rarity[card.rarity] = by_rarity.get(card.rarity, 0) + 1
        if _is_missing_metadata(card):
            missing_metadata_count += 1

    filtered = all_cards
    if q:
        needle = q.strip().lower()
        filtered = [
            c
            for c in filtered
            if needle in c.card_code.lower()
            or needle in (c.name_en or "").lower()
            or needle in (c.name_jp or "").lower()
        ]
    if set_code:
        filtered = [c for c in filtered if c.set_code == set_code]
    if rarity:
        filtered = [c for c in filtered if c.rarity == rarity]
    if variant:
        filtered = [c for c in filtered if c.variant == variant]
    if language:
        filtered = [c for c in filtered if c.language == language]
    if missing_metadata is not None:
        filtered = [c for c in filtered if _is_missing_metadata(c) == missing_metadata]

    total = len(filtered)
    page = filtered[offset : offset + limit]

    return AdminCardListResponseOut(
        summary=AdminCardListSummaryOut(
            total_cards=len(all_cards),
            missing_metadata_count=missing_metadata_count,
            by_set=by_set,
            by_rarity=by_rarity,
        ),
        cards=[AdminCardOut.model_validate(c) for c in page],
        pagination=pagination_response(page, total, limit, offset),
    )


@router.post("/import.csv", response_model=CardCatalogImportResponseOut)
async def import_cards_csv_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    overwrite: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"File is not valid UTF-8: {exc}") from exc

    try:
        result = import_cards_csv(db, csv_text, dry_run=dry_run, overwrite=overwrite)
    except ValueError as exc:
        record_app_log(
            "error",
            "api",
            "card_catalog_import",
            f"Card catalog CSV import failed: {exc}",
            context={"dry_run": dry_run, "overwrite": overwrite},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not dry_run:
        for prefix in _CARD_CATALOG_CACHE_INVALIDATES:
            delete_cache_prefix(prefix)
        if result.error_rows > 0:
            record_app_log(
                "warning",
                "api",
                "card_catalog_import",
                f"Card catalog CSV import completed with {result.error_rows} row error(s).",
                context={
                    "created": result.created,
                    "updated": result.updated,
                    "skipped": result.skipped,
                    "error_rows": result.error_rows,
                },
            )

    return CardCatalogImportResponseOut.model_validate(result.to_dict())


@router.get("/import-images-template.csv")
def get_card_image_import_template():
    """The CSV template for POST /import-images.csv - see
    app.services.card_image_import module docstring for why this is a
    separate, narrower workflow from /import.csv."""
    return PlainTextResponse(
        image_import_template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=card_image_import_template.csv"},
    )


@router.post("/import-images.csv", response_model=CardImageImportResponseOut)
async def import_card_images_csv_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"File is not valid UTF-8: {exc}") from exc

    try:
        result = import_card_images_csv(db, csv_text, dry_run=dry_run)
    except ValueError as exc:
        record_app_log(
            "error",
            "api",
            "card_image_import",
            f"Card image CSV import failed: {exc}",
            context={"dry_run": dry_run},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not dry_run:
        for prefix in _CARD_CATALOG_CACHE_INVALIDATES:
            delete_cache_prefix(prefix)
        if result.error_rows > 0:
            record_app_log(
                "warning",
                "api",
                "card_image_import",
                f"Card image CSV import completed with {result.error_rows} row error(s).",
                context={"applied": result.applied, "error_rows": result.error_rows},
            )

    return CardImageImportResponseOut.model_validate(result.to_dict())


@router.get("/export.csv")
def export_cards_csv_endpoint(db: Session = Depends(get_db)):
    """Streams the CSV row-by-row (see iter_cards_csv_rows) rather than
    building the whole file in memory first - see 'Large import/export
    jobs' in docs/operations.md."""
    filename = export_filename()
    return StreamingResponse(
        iter_cards_csv_rows(db),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
