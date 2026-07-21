"""Admin duplicate-card review and identity-merge tools, built on top of
app.services.card_identity_merge. Distinct from app.api.admin_cards (the
canonical-catalog list/import/export router at /admin/cards) - this module
only adds the duplicate-detection and merge workflow (GET .../duplicates,
POST .../duplicates/bulk-preview, GET .../{id}/merge-preview, POST .../merge)
without changing that router's existing behavior.

Never hard-deletes a card, a source mapping, a price observation, or any
collection/wishlist/grading/tag/note row - see the service module's
docstring for what a merge actually does. Every merge is manual: there is no
bulk-execute endpoint, only bulk-preview (read-only).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.schemas import (
    BulkDuplicatePreviewIn,
    BulkDuplicatePreviewOut,
    CardMergeIn,
    CardMergePreviewOut,
    CardMergeResultOut,
    DuplicateListOut,
    DuplicateSummaryOut,
)
from app.services.app_logging import record_app_log
from app.services.cache import delete_cache_prefix
from app.services.card_identity_merge import (
    CONFIDENCE_LABELS,
    FIELD_STRATEGIES,
    DuplicateDetectionFilters,
    MergeOptions,
    MergeValidationError,
    bulk_duplicate_merge_previews,
    detect_duplicate_cards,
    execute_card_merge,
    preview_card_merge,
)

router = APIRouter(prefix="/admin/cards", tags=["admin"], dependencies=[Depends(require_admin_token)])

# Same cache-invalidation set app.api.admin_cards uses for a real catalog
# import - a merge changes the same cards table every other cached read
# surface resolves card_code/name/rarity/set_code through, so it invalidates
# just as broadly. Kept in sync manually rather than imported (that module's
# constant is underscore-private); see 'Cache invalidation' in
# docs/operations.md.
_CARD_MERGE_CACHE_INVALIDATES = (
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
    "source_mappings",
    "admin/catalog_coverage",
)


def _validate_duplicate_filters(confidence_label: str | None, min_score: int) -> None:
    if confidence_label is not None and confidence_label not in CONFIDENCE_LABELS:
        raise HTTPException(
            status_code=400, detail=f"Invalid confidence_label. Must be one of {list(CONFIDENCE_LABELS)}"
        )
    if min_score < 0 or min_score > 100:
        raise HTTPException(status_code=400, detail="min_score must be between 0 and 100")


def _validate_field_strategy(field_strategy: str) -> None:
    if field_strategy not in FIELD_STRATEGIES:
        raise HTTPException(
            status_code=400, detail=f"Invalid field_strategy. Must be one of {list(FIELD_STRATEGIES)}"
        )


@router.get("/duplicates", response_model=DuplicateListOut)
def get_duplicate_cards(
    q: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    language: str | None = Query(default=None),
    confidence_label: str | None = Query(default=None),
    min_score: int = Query(default=55),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _validate_duplicate_filters(confidence_label, min_score)

    filters = DuplicateDetectionFilters(
        q=q,
        set_code=set_code,
        rarity=rarity,
        variant=variant,
        language=language,
        confidence_label=confidence_label,
        min_score=min_score,
        include_inactive=include_inactive,
    )
    pairs, total, summary = detect_duplicate_cards(db, filters, limit=limit, offset=offset)
    pairs_out = [p.to_dict() for p in pairs]

    return DuplicateListOut(
        summary=DuplicateSummaryOut(**summary),
        pairs=pairs_out,
        pagination=pagination_response(pairs_out, total, limit, offset),
    )


@router.post("/duplicates/bulk-preview", response_model=BulkDuplicatePreviewOut)
def bulk_preview_duplicate_merges(body: BulkDuplicatePreviewIn, db: Session = Depends(get_db)):
    _validate_duplicate_filters(body.confidence_label, body.min_score)
    if body.limit < 1 or body.limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")

    previews = bulk_duplicate_merge_previews(
        db, min_score=body.min_score, confidence_label=body.confidence_label, limit=body.limit
    )
    return BulkDuplicatePreviewOut(previews=[p.to_dict() for p in previews])


@router.get("/{source_card_id}/merge-preview", response_model=CardMergePreviewOut)
def get_merge_preview(
    source_card_id: int,
    target_card_id: int = Query(...),
    field_strategy: str = Query(default="keep_target"),
    db: Session = Depends(get_db),
):
    _validate_field_strategy(field_strategy)
    try:
        preview = preview_card_merge(db, source_card_id, target_card_id, field_strategy=field_strategy)
    except MergeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CardMergePreviewOut(**preview.to_dict())


@router.post("/merge", response_model=CardMergeResultOut)
def merge_cards(body: CardMergeIn, db: Session = Depends(get_db)):
    _validate_field_strategy(body.field_strategy)

    options = MergeOptions(
        dry_run=body.dry_run,
        merge_notes=body.merge_notes,
        field_strategy=body.field_strategy,
        approve_low_confidence=body.approve_low_confidence,
    )
    try:
        result = execute_card_merge(db, body.source_card_id, body.target_card_id, options)
    except MergeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.dry_run and result.merged:
        for prefix in _CARD_MERGE_CACHE_INVALIDATES:
            delete_cache_prefix(prefix)
        record_app_log(
            "info",
            "api",
            "card_identity_merge",
            f"Merged card {result.source_card_id} into card {result.target_card_id} "
            f"(score={result.duplicate_score}, {result.confidence_label}).",
            context={
                "source_card_id": result.source_card_id,
                "target_card_id": result.target_card_id,
                "affected_records": result.affected_records,
            },
        )

    return CardMergeResultOut(**result.to_dict())
