"""Read-only admin view over source_collection_attempts.

This surface exists because collector failures used to leave nothing behind: on
2026-09-02 the first full 214-mapping run left three failures, and one of them
(mapping 391, EB01-030) is permanently unexplainable because Railway did not
retain its log lines and no row was written anywhere. The attempts table fixed
the recording; this endpoint is how it gets read.

READ-ONLY BY CONSTRUCTION. There is one GET and nothing else - no retry, no
manual-run trigger, no mutation of telemetry. Attempt rows are written solely
by the collector services, and an admin surface that could edit them would
destroy the only property that makes them worth keeping.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.schemas import (
    CollectionAttemptListOut,
    CollectionAttemptOut,
    CollectionAttemptSummaryOut,
)
from app.services.collection_attempts import (
    FAILURE_STAGES,
    STATUSES,
    AttemptRow,
    list_collection_attempts,
)

router = APIRouter(
    prefix="/admin/collection-attempts",
    tags=["admin", "observability"],
    dependencies=[Depends(require_admin_token)],
)


def attempt_to_out(row: AttemptRow) -> CollectionAttemptOut:
    attempt = row.attempt
    return CollectionAttemptOut(
        id=attempt.id,
        batch_run_id=attempt.batch_run_id,
        selection_ordinal=attempt.selection_ordinal,
        source_id=attempt.source_id,
        source_name=row.source_name,
        source_card_mapping_id=attempt.source_card_mapping_id,
        mapping_resolved=row.mapping_resolved,
        card_print_id=row.card_print_id,
        card_code=row.card_code,
        selected_at=attempt.selected_at,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        duration_seconds=row.duration_seconds,
        status=attempt.status,
        failure_stage=attempt.failure_stage,
        failure_reason=attempt.failure_reason,
        source_denied=attempt.source_denied,
        price_observation_id=attempt.price_observation_id,
    )


@router.get("", response_model=CollectionAttemptListOut)
def list_collection_attempts_endpoint(
    batch_run_id: str | None = Query(default=None),
    source_id: int | None = Query(default=None, ge=1),
    source_card_mapping_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    failure_stage: str | None = Query(default=None),
    source_denied: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    # An unknown status or stage is a client error, not an empty result: a
    # silent [] would read as "no such attempts" when the truth is "that value
    # cannot exist".
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of {list(STATUSES)}"
        )
    if failure_stage is not None and failure_stage not in FAILURE_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid failure_stage. Must be one of {list(FAILURE_STAGES)}",
        )

    result = list_collection_attempts(
        db,
        batch_run_id=batch_run_id,
        source_id=source_id,
        source_card_mapping_id=source_card_mapping_id,
        status=status,
        failure_stage=failure_stage,
        source_denied=source_denied,
        limit=limit,
        offset=offset,
    )

    attempts_out = [attempt_to_out(row) for row in result.rows]
    summary = result.summary
    return CollectionAttemptListOut(
        summary=CollectionAttemptSummaryOut(
            total_attempts=summary.total_attempts,
            started=summary.started,
            written=summary.written,
            skipped=summary.skipped,
            source_denied=summary.source_denied,
            still_selected=summary.still_selected,
            by_status=summary.by_status,
            by_failure_stage=summary.by_failure_stage,
            earliest_selected_at=summary.earliest_selected_at,
            latest_finished_at=summary.latest_finished_at,
        ),
        attempts=attempts_out,
        limit=limit,
        offset=offset,
        pagination=pagination_response(attempts_out, result.total, limit, offset),
    )
