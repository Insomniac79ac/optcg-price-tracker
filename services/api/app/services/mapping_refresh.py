"""Every approved exact-print mapping gets its raw refresh work at approval time.

Approval and price collection are separate steps: a collector only revisits a mapping that has
a `refresh` row in freshness_work. Before this module nothing on staging planned that row, so a
mapping approved after the one-off raw seeding (an unmerged rollout branch, 2026-10-04) was
approved and then never priced (F1 batch 1, 2026-10-19: 97 mappings, class c_no_refresh_work).

`ensure_refresh_work` is the one call every approval path makes right after it writes an
approved mapping (yuyutei_candidate_approval, snkrdunk_candidate_approval, the SNKRDUNK candidate
endpoint, the admin source-mapping and mapping-quality endpoints).
`scripts/tests/test_mapping_refresh_guard.py` fails when a new path approves a mapping without
calling it. The ops-write runbook `plan-refresh-backfill` plans the same rows for mappings
approved before this existed.

Raw only, as the original seeding: Yuyu-Tei `sell` and SNKRDUNK `floor`. PSA10 demand is never
planned here (PSA10 is off). Existing work is left exactly as it is, so re-approval neither
duplicates a row nor resets progress, a retry or a claim. A mapping that is not yet eligible
(SNKRDUNK without manual verification, an inactive print, an unestablished listing identity) or
whose listing already has work under another mapping (lineage reconciliation is explicit) gets
no row and the approval still stands; the backfill dry run lists it.

This module is deliberately outside the collector import graph: collectors never approve.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FreshnessWork, Source, SourceCardMapping
from app.services.freshness_queue import PriceCategory, plan_refresh

RAW_CATEGORIES = {
    "yuyutei": {"raw": PriceCategory("sell")},
    "snkrdunk": {"raw": PriceCategory("floor")},
}
# Request bound for a source with no refresh work yet; the 2026-10-04 seeding used 30 for both.
DEFAULT_REQUEST_BOUND = 30


def existing_refresh_work(db: Session, mapping_id: int) -> FreshnessWork | None:
    return db.scalar(
        select(FreshnessWork).where(
            FreshnessWork.kind == "refresh",
            FreshnessWork.source_card_mapping_id == mapping_id,
        )
    )


def request_bound(db: Session, source_id: int) -> int:
    """The source's current conservative bound, so new work is admitted like existing work."""
    bound = db.scalar(
        select(func.max(FreshnessWork.estimated_request_cost)).where(
            FreshnessWork.kind == "refresh", FreshnessWork.source_id == source_id
        )
    )
    return int(bound) if bound else DEFAULT_REQUEST_BOUND


def ensure_refresh_work(db: Session, mapping: SourceCardMapping) -> FreshnessWork | None:
    """The mapping's raw refresh work: existing, newly planned, or None when not plannable.

    Runs in the caller's transaction and never commits. Not plannable is not an error for the
    approval: the planning attempt is rolled back to a savepoint and nothing is written.
    """
    if mapping.id is None:
        db.flush()
    existing = existing_refresh_work(db, mapping.id)
    if existing is not None:
        return existing
    source = db.scalar(select(Source.name).where(Source.id == mapping.source_id))
    categories = RAW_CATEGORIES.get(source)
    if categories is None:
        return None
    savepoint = db.begin_nested()
    try:
        work = plan_refresh(
            db,
            mapping.id,
            categories,
            high_interest=False,
            estimated_request_cost=request_bound(db, mapping.source_id),
        )
    except ValueError:
        savepoint.rollback()
        return None
    savepoint.commit()
    return work


__all__ = [
    "DEFAULT_REQUEST_BOUND",
    "RAW_CATEGORIES",
    "ensure_refresh_work",
    "existing_refresh_work",
    "request_bound",
]
