"""GET-only admin API for exact-print proposal analysis and persisted evidence."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import (
    CanonicalCard,
    ReleaseProduct,
    Source,
    SourceMappingProposalGroup,
)
from app.services.source_mapping_proposals import ProposalFilters, analyse_source_mapping_proposals
from app.source_mapping_proposal_schemas import (
    ProposalGroupDetailOut,
    ProposalGroupListOut,
    ProposalGroupOut,
    ProposalReleaseListOut,
    ProposalSummaryOut,
)


router = APIRouter(
    prefix="/admin/source-mapping-proposals",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


def _filters(
    source: str,
    release_product_id: int | None,
    release_code: str | None,
    resolution_status: str | None,
    candidate_id: int | None,
) -> ProposalFilters:
    try:
        return ProposalFilters(
            source=source,
            release_product_id=release_product_id,
            release_code=release_code,
            resolution_status=resolution_status,
            candidate_id=candidate_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/summary", response_model=ProposalSummaryOut)
def proposal_summary(
    source: str = Query(default="all", pattern="^(all|yuyutei|snkrdunk)$"),
    release_product_id: int | None = Query(default=None),
    release_code: str | None = Query(default=None),
    resolution_status: str | None = Query(default=None),
    candidate_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    analysis = analyse_source_mapping_proposals(
        db, _filters(source, release_product_id, release_code, resolution_status, candidate_id)
    )
    payload = analysis.to_dict(include_groups=False)
    return {key: payload[key] for key in ("contract", "overall", "prioritisation")}


@router.get("/releases", response_model=ProposalReleaseListOut)
def proposal_releases(
    source: str = Query(default="all", pattern="^(all|yuyutei|snkrdunk)$"),
    release_product_id: int | None = Query(default=None),
    release_code: str | None = Query(default=None),
    resolution_status: str | None = Query(default=None),
    candidate_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    analysis = analyse_source_mapping_proposals(
        db, _filters(source, release_product_id, release_code, resolution_status, candidate_id)
    )
    return {"items": analysis.report["releases"]}


@router.get("/groups", response_model=ProposalGroupListOut)
def proposal_groups(
    source: str | None = Query(default=None),
    release_product_id: int | None = Query(default=None),
    release_code: str | None = Query(default=None),
    resolution_status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    candidate_id: int | None = Query(default=None),
    include_superseded: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(SourceMappingProposalGroup)
    count_stmt = select(func.count(SourceMappingProposalGroup.id))
    conditions = []
    if not include_superseded:
        conditions.append(SourceMappingProposalGroup.superseded_at.is_(None))
    if source:
        source_id = db.scalar(select(Source.id).where(Source.name == source))
        if source_id is None:
            raise HTTPException(status_code=400, detail=f"Unknown source {source!r}")
        conditions.append(SourceMappingProposalGroup.source_id == source_id)
    if release_product_id is not None:
        conditions.append(SourceMappingProposalGroup.release_product_id == release_product_id)
    if release_code:
        product_ids = select(ReleaseProduct.id).where(ReleaseProduct.official_code == release_code)
        conditions.append(SourceMappingProposalGroup.release_product_id.in_(product_ids))
    if resolution_status:
        conditions.append(SourceMappingProposalGroup.resolution_status == resolution_status)
    if review_status:
        conditions.append(SourceMappingProposalGroup.review_status == review_status)
    if candidate_id is not None:
        conditions.append(SourceMappingProposalGroup.source_candidate_id == candidate_id)
    if card_code:
        card_ids = select(CanonicalCard.id).where(CanonicalCard.card_code == card_code)
        conditions.append(SourceMappingProposalGroup.canonical_card_id.in_(card_ids))
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(SourceMappingProposalGroup.id).offset(offset).limit(limit)
    ).all()
    items = [ProposalGroupOut.model_validate(row) for row in rows]
    return ProposalGroupListOut(
        items=items,
        pagination=pagination_response(items, total, limit, offset),
    )


@router.get("/groups/{proposal_group_id}", response_model=ProposalGroupDetailOut)
def proposal_group_detail(proposal_group_id: int, db: Session = Depends(get_db)):
    row = db.scalar(
        select(SourceMappingProposalGroup)
        .options(selectinload(SourceMappingProposalGroup.alternatives))
        .where(SourceMappingProposalGroup.id == proposal_group_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal group not found")
    return ProposalGroupDetailOut.model_validate(row)
