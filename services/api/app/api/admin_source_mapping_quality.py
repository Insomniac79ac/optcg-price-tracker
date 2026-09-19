"""Admin review/bulk-fix tools for source_card_mappings confidence and data
quality, built on top of app.services.source_mapping_confidence. Distinct
from app.api.source_mappings (the pre-existing generic CRUD router at
/admin/source-mappings) - this router adds the confidence-scored review
workflow (GET .../quality, POST .../recheck-quality, POST .../bulk-update,
PATCH .../{id}/compatibility-card, the deprecated POST .../{id}/replace-card
alias, and GET .../{id}/suggested-cards) without changing the generic CRUD
router's existing behavior.

Never deletes mappings or price observations, never auto-approves an
ambiguous match, and never scrapes anything - every signal here comes from
data already in the DB (see app.services.source_mapping_confidence's module
docstring).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import SourceCardMapping
from app.models.source_card_mapping import REVIEW_STATUSES
from app.schemas import (
    BulkMappingUpdateIn,
    BulkMappingUpdateOut,
    BulkMappingUpdateResultOut,
    BulkMappingUpdateSummaryOut,
    CompatibilityCardUpdateIn,
    CompatibilityCardUpdateOut,
    LegacyReplaceCardAliasIn,
    MappingQualityItemOut,
    MappingQualityListOut,
    MappingQualitySummaryOut,
    RecheckQualityIn,
    RecheckQualityOut,
    RecheckQualitySummaryOut,
    SuggestedCardsOut,
)
from app.services.app_logging import record_app_log
from app.api._mapping_approval import (
    REFUSAL_MAPPING_IDENTITY_BROKEN,
    approval_http_error,
    guard_mapping_can_activate,
    guard_mapping_has_exact_priceable_identity,
    guard_transition_to_approved,
)
from app.services.cache import delete_cache_prefix
from app.services.compatibility_card_admin import (
    ERROR_COMPATIBILITY_CARD_NOT_FOUND,
    CompatibilityCardEditError,
    update_mapping_compatibility_card,
)
from app.services.exact_print_approval import (
    REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT,
    ExactPrintApprovalError,
)
from app.services.source_mapping_confidence import (
    CONFIDENCE_LABELS,
    ISSUE_TYPES,
    RISK_LEVELS,
    MappingQualityFilters,
    bulk_recheck_source_mappings,
    evaluate_source_mapping,
    evaluate_source_mappings,
    suggested_cards_for_mapping,
)

router = APIRouter(
    prefix="/admin/source-mappings", tags=["admin"], dependencies=[Depends(require_admin_token)]
)

SUPPORTED_SOURCES = ("yuyutei", "snkrdunk")

# The bulk-update "pending" concept maps onto the existing review_status
# vocabulary's "needs_review". This codebase has never had a literal
# "pending" review_status (see REVIEW_STATUSES), so a fourth value is not
# added to the existing CHECK CONSTRAINT for a synonym.
PENDING_REVIEW_STATUS = "needs_review"
SKIPPED_LEGACY_COMPATIBILITY = "skipped_legacy_compatibility"
SKIPPED_BROKEN = "skipped_broken"
SKIPPED_NON_PRICEABLE_EXACT = "skipped_non_priceable_exact"


def _item_to_out(item) -> MappingQualityItemOut:
    return MappingQualityItemOut(**item.to_dict())


def _get_mapping_or_404(db: Session, mapping_id: int) -> SourceCardMapping:
    mapping = db.get(SourceCardMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Source mapping not found")
    return mapping


@router.get("/quality", response_model=MappingQualityListOut)
def get_mapping_quality(
    source: str | None = None,
    review_status: str | None = None,
    is_active: bool | None = None,
    manual_verified: bool | None = None,
    confidence_label: str | None = None,
    risk_level: str | None = None,
    issue_type: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if source is not None and source not in SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(SUPPORTED_SOURCES)}"
        )
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_status. Must be one of {list(REVIEW_STATUSES)}",
        )
    if confidence_label is not None and confidence_label not in CONFIDENCE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid confidence_label. Must be one of {list(CONFIDENCE_LABELS)}",
        )
    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise HTTPException(
            status_code=400, detail=f"Invalid risk_level. Must be one of {list(RISK_LEVELS)}"
        )
    if issue_type is not None and issue_type not in ISSUE_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Invalid issue_type. Must be one of {list(ISSUE_TYPES)}"
        )
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    filters = MappingQualityFilters(
        source=source,
        review_status=review_status,
        is_active=is_active,
        manual_verified=manual_verified,
        confidence_label=confidence_label,
        risk_level=risk_level,
        issue_type=issue_type,
        q=q,
    )
    items, total, summary = evaluate_source_mappings(db, filters, limit=limit, offset=offset)
    out_items = [_item_to_out(i) for i in items]

    return MappingQualityListOut(
        summary=MappingQualitySummaryOut(**summary),
        items=out_items,
        pagination=pagination_response(out_items, total, limit, offset),
    )


@router.post("/recheck-quality", response_model=RecheckQualityOut)
def recheck_mapping_quality(body: RecheckQualityIn, db: Session = Depends(get_db)):
    if body.source is not None and body.source not in SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(SUPPORTED_SOURCES)}"
        )
    if body.review_status is not None and body.review_status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_status. Must be one of {list(REVIEW_STATUSES)}",
        )
    if body.limit < 1 or body.limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    filters = MappingQualityFilters(
        source=body.source,
        review_status=body.review_status,
        is_active=body.is_active,
        manual_verified=body.manual_verified,
    )
    summary, preview = bulk_recheck_source_mappings(
        db, filters, limit=body.limit, dry_run=body.dry_run
    )

    if not body.dry_run and summary.updated > 0:
        delete_cache_prefix("source_mappings")
        delete_cache_prefix("admin/catalog_coverage")
        delete_cache_prefix("admin/price_source_health")
        record_app_log(
            "info",
            "api",
            "source_mapping_confidence",
            f"Rechecked {summary.updated} source mapping(s): "
            f"critical={summary.critical} warning={summary.warning} "
            f"review={summary.review} ok={summary.ok}.",
            context={"selected": summary.selected, "updated": summary.updated},
        )

    return RecheckQualityOut(
        dry_run=body.dry_run,
        summary=RecheckQualitySummaryOut(
            selected=summary.selected,
            would_update=summary.would_update,
            updated=summary.updated,
            ok=summary.ok,
            review=summary.review,
            warning=summary.warning,
            critical=summary.critical,
        ),
        preview=[_item_to_out(i) for i in preview],
    )


def _apply_bulk_action(mapping: SourceCardMapping, action: str, review_notes: str | None) -> None:
    now = datetime.now(timezone.utc)

    if action == "approve":
        mapping.review_status = "approved"
        mapping.is_active = True
        mapping.manual_verified = True
        mapping.last_verified_at = now
    elif action == "reject":
        mapping.review_status = "rejected"
        mapping.is_active = False
    elif action == "deactivate":
        mapping.is_active = False
    elif action == "activate":
        mapping.is_active = True
    elif action == "mark_verified":
        mapping.manual_verified = True
        mapping.last_verified_at = now
    elif action == "mark_pending":
        mapping.review_status = PENDING_REVIEW_STATUS
    else:  # pragma: no cover - BulkMappingAction Literal already restricts this
        raise ValueError(f"Unknown bulk action: {action}")

    if review_notes is not None:
        mapping.review_notes = review_notes


def _bulk_operational_skip_code(exc: ExactPrintApprovalError) -> str:
    if exc.code == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT:
        return SKIPPED_LEGACY_COMPATIBILITY
    if exc.code == REFUSAL_MAPPING_IDENTITY_BROKEN:
        return SKIPPED_BROKEN
    return SKIPPED_NON_PRICEABLE_EXACT


def _guard_bulk_operational_action(
    db: Session, mapping: SourceCardMapping, action: str
) -> None:
    if action == "approve":
        guard_transition_to_approved(db, mapping)
        guard_mapping_has_exact_priceable_identity(db, mapping)
    elif action == "activate":
        guard_mapping_can_activate(db, mapping)
    elif action == "mark_verified":
        guard_mapping_has_exact_priceable_identity(db, mapping)


@router.post("/bulk-update", response_model=BulkMappingUpdateOut)
def bulk_update_mappings(body: BulkMappingUpdateIn, db: Session = Depends(get_db)):
    results: list[BulkMappingUpdateResultOut] = []
    any_applied = False

    for mapping_id in body.mapping_ids:
        mapping = db.get(SourceCardMapping, mapping_id)
        if mapping is None:
            results.append(
                BulkMappingUpdateResultOut(mapping_id=mapping_id, ok=False, error="not found")
            )
            continue

        # These actions can make or prime a mapping for collection. Every row
        # is checked independently so legacy/broken/non-priceable identities
        # are explicit skips rather than false successes.
        if body.action in ("approve", "activate", "mark_verified"):
            try:
                _guard_bulk_operational_action(db, mapping, body.action)
            except ExactPrintApprovalError as exc:
                results.append(
                    BulkMappingUpdateResultOut(
                        mapping_id=mapping_id,
                        ok=False,
                        error=_bulk_operational_skip_code(exc),
                    )
                )
                continue

        _apply_bulk_action(mapping, body.action, body.review_notes)
        any_applied = True
        results.append(BulkMappingUpdateResultOut(mapping_id=mapping_id, ok=True))

    if any_applied:
        db.commit()
        delete_cache_prefix("source_mappings")
        delete_cache_prefix("admin/catalog_coverage")
        delete_cache_prefix("admin/price_source_health")
        record_app_log(
            "info",
            "api",
            "source_mapping_confidence",
            f"Bulk {body.action} applied to {sum(1 for r in results if r.ok)} source mapping(s).",
            context={"action": body.action, "mapping_ids": body.mapping_ids},
        )

    return BulkMappingUpdateOut(
        action=body.action,
        results=results,
        summary=BulkMappingUpdateSummaryOut(
            applied=sum(result.ok for result in results),
            skipped_legacy_compatibility=sum(
                result.error == SKIPPED_LEGACY_COMPATIBILITY for result in results
            ),
            skipped_broken=sum(
                result.error == SKIPPED_BROKEN for result in results
            ),
            skipped_non_priceable_exact=sum(
                result.error == SKIPPED_NON_PRICEABLE_EXACT for result in results
            ),
            not_found=sum(result.error == "not found" for result in results),
        ),
    )


def _edit_compatibility_card(
    db: Session,
    mapping_id: int,
    *,
    compatibility_card_id: int | None,
    review_notes: str | None,
    deprecated_route: bool,
    deprecated_approve_requested: bool = False,
) -> CompatibilityCardUpdateOut:
    mapping = _get_mapping_or_404(db, mapping_id)
    try:
        result = update_mapping_compatibility_card(
            db,
            mapping,
            compatibility_card_id=compatibility_card_id,
            review_notes=review_notes,
        )
    except CompatibilityCardEditError as exc:
        if deprecated_route and exc.code == ERROR_COMPATIBILITY_CARD_NOT_FOUND:
            # Preserve the legacy route's existing error contract while the
            # frontend still consumes it.
            raise HTTPException(status_code=404, detail="Card not found") from exc
        status_code = 404 if exc.code == ERROR_COMPATIBILITY_CARD_NOT_FOUND else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc

    db.commit()
    delete_cache_prefix("source_mappings")
    delete_cache_prefix("admin/catalog_coverage")
    delete_cache_prefix("admin/price_source_health")
    record_app_log(
        "info",
        "api",
        "source_mapping_compatibility_card",
        f"Mapping {mapping.id} compatibility card updated; pricing identity unchanged.",
        context={
            "mapping_id": mapping.id,
            "authoritative_card_print_id": result.authoritative_card_print_id,
            "previous_compatibility_card_id": result.previous_compatibility_card_id,
            "new_compatibility_card_id": result.new_compatibility_card_id,
            "pricing_identity_changed": False,
            "deprecated_route": deprecated_route,
            "deprecated_approve_requested": deprecated_approve_requested,
        },
    )

    refreshed = evaluate_source_mapping(db, mapping)
    return CompatibilityCardUpdateOut(
        **refreshed.to_dict(),
        operation="compatibility_card_updated",
        authoritative_card_print_id=result.authoritative_card_print_id,
        previous_compatibility_card_id=result.previous_compatibility_card_id,
        new_compatibility_card_id=result.new_compatibility_card_id,
        pricing_identity_changed=False,
        deprecated_route=deprecated_route,
        deprecated_approve_requested=deprecated_approve_requested,
    )


@router.patch(
    "/{mapping_id}/compatibility-card",
    response_model=CompatibilityCardUpdateOut,
    summary="Edit legacy compatibility-card metadata",
)
def edit_mapping_compatibility_card(
    mapping_id: int,
    body: CompatibilityCardUpdateIn,
    db: Session = Depends(get_db),
):
    return _edit_compatibility_card(
        db,
        mapping_id,
        compatibility_card_id=body.compatibility_card_id,
        review_notes=body.review_notes,
        deprecated_route=False,
    )


@router.post(
    "/{mapping_id}/replace-card",
    response_model=CompatibilityCardUpdateOut,
    deprecated=True,
    summary="Deprecated alias: edit legacy compatibility-card metadata",
    description=(
        "Compatibility alias retained for the current admin client. card_id is "
        "legacy compatibility metadata; approve is ignored and this action never "
        "changes authoritative CardPrint pricing identity or operational state."
    ),
)
def replace_mapping_card_compatibility_alias(
    mapping_id: int, body: LegacyReplaceCardAliasIn, db: Session = Depends(get_db)
):
    return _edit_compatibility_card(
        db,
        mapping_id,
        compatibility_card_id=body.card_id,
        review_notes=body.review_notes,
        deprecated_route=True,
        deprecated_approve_requested=body.approve,
    )


@router.get("/{mapping_id}/suggested-cards", response_model=SuggestedCardsOut)
def get_suggested_cards(mapping_id: int, db: Session = Depends(get_db)):
    mapping = _get_mapping_or_404(db, mapping_id)
    suggestions = suggested_cards_for_mapping(db, mapping)
    return SuggestedCardsOut(
        mapping_id=mapping.id,
        identity_classification=suggestions.identity_classification,
        authoritative_card_print_id=suggestions.authoritative_card_print_id,
        suggestion_scope=suggestions.suggestion_scope,
        message=suggestions.message,
        matches=[
            {
                "card_id": r.card_id,
                "card_code": r.card_code,
                "name_en": r.name_en,
                "name_jp": r.name_jp,
                "set_code": r.set_code,
                "rarity": r.rarity,
                "variant": r.variant,
                "score": r.score,
                "confidence_label": r.confidence_label,
                "ambiguous": r.ambiguous,
                "explanation": r.explanation.to_dict(),
            }
            for r in suggestions.matches
        ],
    )
