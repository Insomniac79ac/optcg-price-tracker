from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.pagination import PaginationMeta
from app.schemas import DisplayImageOut


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
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_notes: str | None
    selected_alternative_id: int | None
    decision_basis_updated_at: datetime | None
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


# Persisted proposal-review read model.  These schemas deliberately do not
# reuse the resolver-analysis report above: review reads durable proposal rows
# and never runs the resolver as a side effect of browsing the queue.


class ProposalReviewResolutionCountsOut(BaseModel):
    exact: int = 0
    ambiguous: int = 0
    unresolved_identity: int = 0
    release_unresolved: int = 0
    conflict: int = 0
    stale: int = 0
    superseded: int = 0


class ProposalReviewSourceSummaryOut(BaseModel):
    total_current_groups: int
    total_current_alternatives: int
    resolutions: ProposalReviewResolutionCountsOut


class ProposalReviewSummaryOut(BaseModel):
    contract: dict[str, Any]
    total_current_groups: int
    total_current_alternatives: int
    pending_groups: int
    approved_groups: int
    rejected_groups: int
    resulting_mappings_populated: int
    superseded_historical_groups: int
    by_resolution: ProposalReviewResolutionCountsOut
    by_source: dict[str, ProposalReviewSourceSummaryOut]
    by_source_and_resolution: dict[str, ProposalReviewResolutionCountsOut]
    groups_with_one_alternative: int
    groups_with_multiple_alternatives: int
    maximum_alternatives_on_one_listing: int
    release_resolved_groups: int
    null_release_groups: int
    groups_with_candidate_images: int
    groups_with_no_candidate_image: int
    groups_with_recommended_alternatives: int
    groups_with_no_recommended_alternative: int


class ProposalReviewReleaseSourceOut(BaseModel):
    pending_proposal_groups: int = 0
    exact_pending_groups: int = 0
    ambiguous_pending_groups: int = 0
    unresolved_identity_pending_groups: int = 0
    release_unresolved_pending_groups: int = 0
    alternatives: int = 0


class ProposalReviewReleaseOut(BaseModel):
    release_product_id: int | None
    official_code: str | None
    display_name: str
    source_catalogue: str | None
    authoritative_release_order: str | None
    chronology_available: bool
    total_active_verified_japanese_card_prints: int
    existing_exact_source_card_mappings: int
    pending_proposal_groups: int
    exact_pending_groups: int
    ambiguous_pending_groups: int
    unresolved_identity_pending_groups: int
    release_unresolved_pending_groups: int
    alternatives: int
    remaining_prints_with_no_approved_mapping_after_exact_proposals: int
    sources: dict[str, ProposalReviewReleaseSourceOut]


class ProposalReviewReleaseListOut(BaseModel):
    contract: dict[str, Any]
    items: list[ProposalReviewReleaseOut]


class ProposalReviewSourceOut(BaseModel):
    id: int
    name: str


class ProposalReviewCanonicalCardOut(BaseModel):
    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    card_type: str | None = None
    canonical_rarity: str | None = None


class ProposalReviewReleaseContextOut(BaseModel):
    id: int
    official_code: str | None
    display_name: str
    source_catalogue: str
    source_series_id: str
    source_url: str
    verification_status: str
    authoritative_release_order: str | None
    chronology_available: bool
    membership_explanation: str


class ProposalReviewYuyuteiCandidateOut(BaseModel):
    set_slug: str
    product_id: str
    name_jp: str | None
    availability: str | None
    price_jpy: int | None
    image_url: str | None


class ProposalReviewSnkrdunkCandidateOut(BaseModel):
    title: str | None
    listing_count: int | None
    condition_label: str | None
    price_jpy: int | None
    detected_set_code: str | None
    detected_variant: str | None
    image_url: str | None


class ProposalReviewCandidateSummaryOut(BaseModel):
    candidate_type: str
    candidate_id: int
    source_url: str
    source_native_identity: str
    detected_card_code: str | None
    detected_rarity: str | None
    image_url: str | None
    image_missing: bool
    price_jpy: int | None
    candidate_missing: bool = False
    yuyutei: ProposalReviewYuyuteiCandidateOut | None = None
    snkrdunk: ProposalReviewSnkrdunkCandidateOut | None = None


class ProposalReviewPrintOut(BaseModel):
    alternative_id: int
    card_print_id: int
    recommended: bool
    canonical_card: ProposalReviewCanonicalCardOut
    release: ProposalReviewReleaseContextOut | None
    language: str
    official_asset_variant: str | None
    release_product_code: str | None
    treatment: str | None
    official_rarity: str | None
    official_block_icon: str | None
    official_name: str | None
    official_effect_text: str | None
    artwork_key: str | None
    artist: str | None
    printing_label: str | None
    special_print_label: str | None
    canonical_image_url: str | None
    display_image: DisplayImageOut | None
    image_missing: bool
    is_active: bool
    verification_status: str


class ProposalReviewGroupOut(BaseModel):
    id: int
    source_id: int
    source_name: str
    source: ProposalReviewSourceOut
    canonical_source_listing_identity: str
    source_url: str
    source_candidate_type: str
    source_candidate_id: int
    resolution_status: str
    review_status: str
    resolver_version: str
    created_at: datetime
    updated_at: datetime
    superseded_at: datetime | None
    resulting_source_card_mapping_id: int | None
    alternative_count: int
    recommended_alternative_count: int
    canonical_card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    canonical_card: ProposalReviewCanonicalCardOut | None
    release_product_id: int | None
    release: ProposalReviewReleaseContextOut | None
    candidate: ProposalReviewCandidateSummaryOut
    recommended_print: ProposalReviewPrintOut | None


class ProposalReviewGroupListOut(BaseModel):
    contract: dict[str, Any]
    items: list[ProposalReviewGroupOut]
    pagination: PaginationMeta


class ProposalReviewDiscoveryRunOut(BaseModel):
    id: int
    source: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    provenance: dict[str, Any]


class ProposalReviewCandidateDetailOut(ProposalReviewCandidateSummaryOut):
    raw_listing_text: str | None
    normalized_title: str | None
    match_status: str | None
    match_explanation: dict[str, Any] | None
    ambiguous_matches: list[Any] | None
    stored_evidence: dict[str, Any]
    discovery_run: ProposalReviewDiscoveryRunOut | None


class ProposalReviewAlternativeOut(ProposalReviewPrintOut):
    proposal_group_id: int
    review_disposition: str
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    supporting_evidence: list[Any]
    missing_evidence: list[Any]
    conflict_reasons: list[Any]


class ProposalReviewLegacyCardOut(BaseModel):
    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str


class ProposalReviewCompatibilityOut(BaseModel):
    role: str
    candidate_matched_card_id: int | None
    candidate_best_match_card_id: int | None
    resulting_mapping_card_id: int | None
    legacy_cards: list[ProposalReviewLegacyCardOut]


class ProposalReviewGroupDetailOut(ProposalReviewGroupOut):
    evidence_digest: str
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_notes: str | None
    selected_alternative_id: int | None
    decision_basis_updated_at: datetime | None
    evidence_summary: dict[str, Any]
    resolution_reasons: list[Any]
    resulting_mapping: dict[str, Any] | None
    candidate: ProposalReviewCandidateDetailOut
    alternatives: list[ProposalReviewAlternativeOut]
    compatibility: ProposalReviewCompatibilityOut
    historical_state: dict[str, Any]
