from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.pagination import PaginationMeta


class ProposalAlternativeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proposal_group_id: int
    card_print_id: int
    recommended: bool
    supporting_evidence_json: list
    missing_evidence_json: list
    conflict_reasons_json: list
    review_disposition: str
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProposalGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    canonical_source_listing_identity: str
    source_url: str
    source_candidate_type: str
    source_candidate_id: int
    canonical_card_id: int | None
    release_product_id: int | None
    resolution_status: str
    review_status: str
    resolver_version: str
    evidence_digest: str
    evidence_summary_json: dict[str, Any]
    resolution_reasons_json: list
    resulting_source_card_mapping_id: int | None
    created_at: datetime
    updated_at: datetime
    superseded_at: datetime | None


class ProposalGroupDetailOut(ProposalGroupOut):
    alternatives: list[ProposalAlternativeOut]


class ProposalGroupListOut(BaseModel):
    items: list[ProposalGroupOut]
    pagination: PaginationMeta


class ProposalSummaryOut(BaseModel):
    contract: dict[str, Any]
    overall: dict[str, Any]
    prioritisation: dict[str, Any]


class ProposalReleaseListOut(BaseModel):
    items: list[dict[str, Any]]
