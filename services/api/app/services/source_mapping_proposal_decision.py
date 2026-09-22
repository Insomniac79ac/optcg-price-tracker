"""Transaction-scoped decision logic for one exact mapping proposal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_actor import AdminActor
from app.models import (
    CardPrint,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
)
from app.services.snkrdunk_candidate_approval import approve_candidate_onto_print
from app.services.source_mapping_proposals import (
    ProposalPlan,
    resolve_current_candidate_proposal,
)
from app.services.yuyutei_candidate_approval import (
    ExactProposalApprovalProof,
    approve_candidate,
    approve_candidate_from_exact_proposal,
)
from app.source_mapping_proposal_schemas import ApproveExactProposalIn


@dataclass(frozen=True)
class ProposalDecisionResult:
    proposal_group_id: int
    review_status: str
    selected_alternative_id: int
    resulting_source_card_mapping_id: int
    card_print_id: int
    source: str
    source_candidate_id: int
    reviewed_at: datetime
    reviewed_by: str
    review_notes: str | None
    decision_basis_updated_at: datetime
    mapping_created: bool
    mapping_reused: bool
    candidate_status: str
    idempotent_replay: bool
    collection_triggered: bool = False
    price_observation_written: bool = False
    eligible_for_future_scheduled_collection: bool = True


class ProposalDecisionError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _fail(code: str, message: str, *, status_code: int = 409) -> None:
    raise ProposalDecisionError(code, message, status_code=status_code)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_instant(left: datetime | None, right: datetime) -> bool:
    return left is not None and _utc(left) == _utc(right)


def _normalized_note(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _candidate_status(candidate: YuyuteiCandidate | SnkrdunkCandidate) -> str:
    return candidate.match_status


def _result(
    *,
    group: SourceMappingProposalGroup,
    alternative: SourceMappingProposalAlternative,
    source: Source,
    mapping: SourceCardMapping,
    candidate: YuyuteiCandidate | SnkrdunkCandidate,
    mapping_created: bool,
    replay: bool,
) -> ProposalDecisionResult:
    assert group.reviewed_at is not None
    assert group.reviewed_by is not None
    assert group.decision_basis_updated_at is not None
    return ProposalDecisionResult(
        proposal_group_id=group.id,
        review_status=group.review_status,
        selected_alternative_id=alternative.id,
        resulting_source_card_mapping_id=mapping.id,
        card_print_id=alternative.card_print_id,
        source=source.name,
        source_candidate_id=group.source_candidate_id,
        reviewed_at=_utc(group.reviewed_at),
        reviewed_by=group.reviewed_by,
        review_notes=group.review_notes,
        decision_basis_updated_at=_utc(group.decision_basis_updated_at),
        mapping_created=mapping_created,
        mapping_reused=not mapping_created,
        candidate_status=_candidate_status(candidate),
        idempotent_replay=replay,
    )


def _load_candidate_for_update(
    db: Session, group: SourceMappingProposalGroup
) -> YuyuteiCandidate | SnkrdunkCandidate:
    model: type[YuyuteiCandidate] | type[SnkrdunkCandidate]
    if group.source_candidate_type == "yuyutei_candidate":
        model = YuyuteiCandidate
    elif group.source_candidate_type == "snkrdunk_candidate":
        model = SnkrdunkCandidate
    else:  # protected by the database CHECK, retained as a readable refusal
        _fail("candidate_missing", "Proposal has an unsupported candidate type.")
    candidate = db.scalar(
        select(model).where(model.id == group.source_candidate_id).with_for_update()
    )
    if candidate is None:
        _fail("candidate_missing", "The proposal source candidate no longer exists.")
    return candidate


def _assert_candidate_state(
    group: SourceMappingProposalGroup,
    candidate: YuyuteiCandidate | SnkrdunkCandidate,
) -> None:
    evidence = group.evidence_summary_json or {}
    if isinstance(candidate, YuyuteiCandidate):
        if candidate.match_status != evidence.get("candidate_match_status"):
            _fail("candidate_state_changed", "Yuyu-Tei candidate match status changed.")
        if candidate.matched_card_print_id != evidence.get("candidate_matched_card_print_id"):
            _fail("candidate_state_changed", "Yuyu-Tei candidate print state changed.")
        if candidate.match_status not in ("print_matched", "family_matched"):
            _fail("candidate_state_changed", "Yuyu-Tei candidate is no longer approvable.")
    else:
        if candidate.match_status != evidence.get("legacy_match_status"):
            _fail("candidate_state_changed", "SNKRDUNK candidate match status changed.")
        if candidate.match_status != "unmatched":
            _fail("candidate_state_changed", "SNKRDUNK candidate is no longer unmatched.")


def _assert_plan_matches(
    group: SourceMappingProposalGroup,
    alternative: SourceMappingProposalAlternative,
    source: Source,
    plan: ProposalPlan | None,
) -> ProposalPlan:
    if plan is None:
        _fail("proposal_result_changed", "The current resolver no longer emits this proposal.")
    if plan.source_name != source.name or plan.source_id != group.source_id:
        _fail("source_identity_changed", "The proposal source identity changed.")
    if (
        plan.source_candidate_id != group.source_candidate_id
        or plan.source_candidate_type != group.source_candidate_type
        or plan.canonical_source_listing_identity != group.canonical_source_listing_identity
        or plan.source_url != group.source_url
    ):
        _fail("source_identity_changed", "The source listing identity changed.")
    if plan.canonical_card_id != group.canonical_card_id:
        _fail("proposal_result_changed", "The resolved canonical card changed.")
    if plan.release_product_id != group.release_product_id:
        _fail("release_changed", "The authoritative release changed.")
    if plan.resolution_status != "exact":
        _fail("proposal_result_changed", "The proposal no longer resolves exactly.")
    if plan.evidence_digest != group.evidence_digest:
        _fail("evidence_digest_changed", "Current evidence digest differs from the proposal.")
    if plan.resolver_version != group.resolver_version:
        _fail("resolver_version_changed", "Current resolver version differs from the proposal.")
    recommended = [item for item in plan.alternatives if item.recommended]
    if len(plan.alternatives) != 1 or len(recommended) != 1:
        _fail(
            "proposal_has_no_single_recommended_alternative",
            "The current exact result does not have one sole recommended alternative.",
        )
    if recommended[0].card_print_id != alternative.card_print_id:
        _fail("proposal_result_changed", "The resolver now recommends another print.")
    return plan


def approve_exact_proposal(
    db: Session,
    proposal_group_id: int,
    request: ApproveExactProposalIn,
    actor: AdminActor,
) -> ProposalDecisionResult:
    """Approve exactly one current exact proposal.  Flushes; never commits."""
    group = db.scalar(
        select(SourceMappingProposalGroup)
        .where(SourceMappingProposalGroup.id == proposal_group_id)
        .with_for_update()
    )
    if group is None:
        _fail("proposal_not_found", "Proposal group not found.", status_code=404)

    alternatives = db.scalars(
        select(SourceMappingProposalAlternative)
        .where(SourceMappingProposalAlternative.proposal_group_id == group.id)
        .order_by(SourceMappingProposalAlternative.id)
        .with_for_update()
    ).all()
    source = db.get(Source, group.source_id)
    if source is None:
        _fail("source_identity_changed", "Proposal source no longer exists.")

    requested_alternative = next(
        (row for row in alternatives if row.id == request.selected_alternative_id), None
    )

    # Exact replay is checked before the ordinary pending-state refusal.
    if group.review_status == "approved":
        if requested_alternative is None:
            _fail(
                "selected_alternative_not_in_group",
                "Selected alternative does not belong to this proposal.",
                status_code=400,
            )
        mapping = (
            db.get(SourceCardMapping, group.resulting_source_card_mapping_id)
            if group.resulting_source_card_mapping_id is not None
            else None
        )
        replay_matches = (
            group.selected_alternative_id == request.selected_alternative_id
            and group.evidence_digest.lower() == request.expected_evidence_digest.lower()
            and group.resolver_version == request.expected_resolver_version
            and _same_instant(group.decision_basis_updated_at, request.expected_updated_at)
            and _normalized_note(group.review_notes) == _normalized_note(request.review_note)
            and group.reviewed_by == actor.email.strip().lower()
            and mapping is not None
            and mapping.card_print_id == requested_alternative.card_print_id
        )
        if not replay_matches:
            _fail("proposal_not_pending", "Approved proposal does not match this retry.")
        candidate = _load_candidate_for_update(db, group)
        return _result(
            group=group,
            alternative=requested_alternative,
            source=source,
            mapping=mapping,
            candidate=candidate,
            mapping_created=False,
            replay=True,
        )

    if group.superseded_at is not None:
        _fail("proposal_superseded", "Proposal has been superseded.")
    if group.review_status != "pending":
        _fail("proposal_not_pending", "Proposal is not pending.")
    if group.resolution_status != "exact":
        _fail("proposal_not_exact", "Only exact proposals may be approved.")
    if group.resulting_source_card_mapping_id is not None:
        _fail("proposal_not_pending", "Pending proposal already names a result mapping.")
    if group.evidence_digest.lower() != request.expected_evidence_digest.lower():
        _fail("evidence_digest_changed", "Proposal evidence digest changed.")
    if group.resolver_version != request.expected_resolver_version:
        _fail("resolver_version_changed", "Proposal resolver version changed.")
    if not _same_instant(group.updated_at, request.expected_updated_at):
        _fail("proposal_updated", "Proposal was updated after the reviewer loaded it.")

    if requested_alternative is None:
        _fail(
            "selected_alternative_not_in_group",
            "Selected alternative does not belong to this proposal.",
            status_code=400,
        )
    recommended = [row for row in alternatives if row.recommended]
    if (
        len(alternatives) != 1
        or len(recommended) != 1
        or requested_alternative.review_disposition != "pending"
        or not requested_alternative.recommended
    ):
        _fail(
            "proposal_has_no_single_recommended_alternative",
            "Exact proposal must contain one pending recommended alternative and no others.",
        )

    candidate = _load_candidate_for_update(db, group)
    _assert_candidate_state(group, candidate)
    plan = resolve_current_candidate_proposal(
        db, source_name=source.name, candidate_id=group.source_candidate_id
    )
    print_row = db.get(CardPrint, requested_alternative.card_print_id)
    if print_row is None:
        _fail("print_not_found", "Selected CardPrint no longer exists.", status_code=404)
    if not print_row.is_active:
        _fail("print_inactive", "Selected CardPrint is inactive.")
    if print_row.verification_status != "verified":
        _fail("print_unverified", "Selected CardPrint is unverified.")
    if print_row.canonical_card_id != group.canonical_card_id:
        _fail("proposal_result_changed", "Selected CardPrint canonical card changed.")
    if print_row.release_product_id != group.release_product_id:
        _fail("release_changed", "Selected CardPrint release changed.")
    plan = _assert_plan_matches(group, requested_alternative, source, plan)

    review_note = _normalized_note(request.review_note)
    if isinstance(candidate, YuyuteiCandidate):
        if candidate.match_status == "print_matched":
            if candidate.matched_card_print_id != requested_alternative.card_print_id:
                _fail("candidate_state_changed", "Yuyu-Tei matched print changed.")
            approval = approve_candidate(db, candidate=candidate, review_notes=review_note, source=source)
        else:
            proof = ExactProposalApprovalProof(
                proposal_group_id=group.id,
                candidate_id=candidate.id,
                canonical_source_listing_identity=plan.canonical_source_listing_identity,
                canonical_card_id=plan.canonical_card_id,
                release_product_id=plan.release_product_id,
                card_print_id=requested_alternative.card_print_id,
                evidence_digest=plan.evidence_digest,
                resolver_version=plan.resolver_version,
            )
            approval = approve_candidate_from_exact_proposal(
                db,
                candidate=candidate,
                proof=proof,
                review_notes=review_note,
                source=source,
            )
    else:
        approval = approve_candidate_onto_print(
            db,
            candidate=candidate,
            card_print_id=requested_alternative.card_print_id,
            card=None,
            review_notes=review_note,
            source=source,
        )

    decision_basis = group.updated_at
    decision_time = datetime.now(timezone.utc)
    group.review_status = "approved"
    group.reviewed_at = decision_time
    group.reviewed_by = actor.email.strip().lower()
    group.review_notes = review_note
    group.selected_alternative_id = requested_alternative.id
    group.decision_basis_updated_at = decision_basis
    group.resulting_source_card_mapping_id = approval.mapping.id
    requested_alternative.review_disposition = "approved"
    requested_alternative.reviewed_at = decision_time
    requested_alternative.review_notes = review_note
    db.flush()

    return _result(
        group=group,
        alternative=requested_alternative,
        source=source,
        mapping=approval.mapping,
        candidate=candidate,
        mapping_created=approval.mapping_created,
        replay=False,
    )


__all__ = [
    "ProposalDecisionError",
    "ProposalDecisionResult",
    "approve_exact_proposal",
]
