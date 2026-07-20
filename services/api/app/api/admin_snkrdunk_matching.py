"""Admin-triggered candidate-to-card matching review tools, built on top of
app.services.card_matching's deterministic scorer. Distinct from the
pre-existing /snkrdunk/candidates/{id}/match|reject endpoints (app.api.
snkrdunk_candidates), which remain the "I already know the card" manual
match path; this router is the "help me find the right card, then let me
confirm it" review workflow (GET .../matches, POST .../rematch, POST
.../rematch-all, POST .../approve-match, POST .../reject-match).

Never auto-creates a source_card_mappings row and never sets
match_status="matched" on its own - only approve-match (an explicit human
action) does either of those. See app.services.card_matching's module
docstring for the full rationale.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models import Card, Source, SourceCardMapping
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.schemas import (
    ApproveMatchIn,
    CandidateMatchesOut,
    CandidateMatchOut,
    CardOut,
    RejectMatchIn,
    RematchAllIn,
    RematchAllOut,
    SnkrdunkCandidateOut,
)
from app.services.app_logging import record_app_log
from app.services.card_matching import (
    SUGGESTED_SCORE_THRESHOLD,
    CandidateMatchResult,
    calculate_candidate_match,
    rank_candidate_matches,
)
from app.services.cache import delete_cache_prefix

router = APIRouter(
    prefix="/admin/snkrdunk-candidates", tags=["admin"], dependencies=[Depends(require_admin_token)]
)

# match_status values rank_candidate_matches' caller is allowed to set
# automatically (rematch / rematch-all) - "matched"/"rejected" are reserved
# for an explicit human decision (approve-match / reject-match /
# the pre-existing manual match endpoint) and are never overwritten here.
_AUTO_SETTABLE_STATUSES = ("unmatched", "suggested", "ambiguous")
_REMATCH_ALL_STATUS_CHOICES = ("unmatched", "suggested", "ambiguous", "all")


def _get_candidate_or_404(db: Session, candidate_id: int) -> SnkrdunkCandidate:
    candidate = db.get(SnkrdunkCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _get_snkrdunk_source(db: Session) -> Source:
    source = db.query(Source).filter_by(name="snkrdunk").one_or_none()
    if source is None:
        raise HTTPException(status_code=500, detail="snkrdunk source is not configured")
    return source


def _to_match_out(result: CandidateMatchResult) -> CandidateMatchOut:
    return CandidateMatchOut(**result.to_dict())


def _to_candidate_out(db: Session, candidate: SnkrdunkCandidate) -> SnkrdunkCandidateOut:
    card = db.get(Card, candidate.matched_card_id) if candidate.matched_card_id else None
    out = SnkrdunkCandidateOut.model_validate(candidate)
    out.matched_card = None
    if card is not None:
        out.matched_card = CardOut.model_validate(card)
    return out


def _resolve_new_status(results: list[CandidateMatchResult]) -> tuple[str, CandidateMatchResult | None]:
    """Determines the match_status rank_candidate_matches' outcome implies,
    per the spec thresholds: no scored candidate -> unmatched; ambiguous top
    two -> ambiguous; top score >= SUGGESTED_SCORE_THRESHOLD -> suggested;
    anything else (below suggested, including the 55-74 "medium confidence
    but not surfaced" band) -> unmatched, since nothing weaker than
    "suggested" is safe to surface as an actionable suggestion."""
    if not results:
        return "unmatched", None
    top = results[0]
    if top.ambiguous:
        return "ambiguous", top
    if top.score >= SUGGESTED_SCORE_THRESHOLD:
        return "suggested", top
    return "unmatched", None


def _apply_rematch(candidate: SnkrdunkCandidate, results: list[CandidateMatchResult]) -> str:
    """Updates the candidate's best_match_*/ambiguous_matches_json fields in
    place from a fresh rank_candidate_matches() call, and returns the
    match_status this ranking implies. Only mutates match_status itself when
    the candidate isn't already in a human-decided terminal state (matched/
    rejected) - see _AUTO_SETTABLE_STATUSES."""
    new_status, top = _resolve_new_status(results)

    candidate.match_explanation_json = top.explanation.to_dict() if top else None
    candidate.ambiguous_matches_json = (
        [r.to_dict() for r in results if r.ambiguous] if new_status == "ambiguous" else None
    )

    if top is not None and new_status != "unmatched":
        candidate.best_match_card_id = top.card_id
        candidate.best_match_score = top.score
        candidate.best_match_confidence_label = top.confidence_label
    else:
        candidate.best_match_card_id = None
        candidate.best_match_score = results[0].score if results else None
        candidate.best_match_confidence_label = results[0].confidence_label if results else None

    if candidate.match_status in _AUTO_SETTABLE_STATUSES:
        candidate.match_status = new_status

    return new_status


@router.get("/{candidate_id}/matches", response_model=CandidateMatchesOut)
def get_candidate_matches(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    results = rank_candidate_matches(db, candidate)
    return CandidateMatchesOut(
        candidate=_to_candidate_out(db, candidate),
        matches=[_to_match_out(r) for r in results],
    )


@router.post("/{candidate_id}/rematch", response_model=CandidateMatchesOut)
def rematch_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    results = rank_candidate_matches(db, candidate)
    _apply_rematch(candidate, results)
    db.commit()
    db.refresh(candidate)
    delete_cache_prefix("snkrdunk_candidates")
    return CandidateMatchesOut(
        candidate=_to_candidate_out(db, candidate),
        matches=[_to_match_out(r) for r in results],
    )


@router.post("/rematch-all", response_model=RematchAllOut)
def rematch_all_candidates(body: RematchAllIn, db: Session = Depends(get_db)):
    status = body.status or "all"
    if status not in _REMATCH_ALL_STATUS_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(_REMATCH_ALL_STATUS_CHOICES)}",
        )

    query = select(SnkrdunkCandidate)
    if status == "all":
        query = query.where(SnkrdunkCandidate.match_status.in_(_AUTO_SETTABLE_STATUSES))
    else:
        query = query.where(SnkrdunkCandidate.match_status == status)
    query = query.order_by(SnkrdunkCandidate.id).limit(body.limit)

    candidates = db.scalars(query).all()

    counts = {"would_update": 0, "updated": 0, "suggested": 0, "ambiguous": 0, "unmatched": 0}
    for candidate in candidates:
        results = rank_candidate_matches(db, candidate)
        new_status = _apply_rematch(candidate, results)
        counts["would_update"] += 1
        counts[new_status] += 1
        if not body.dry_run:
            counts["updated"] += 1

    if body.dry_run:
        db.rollback()
    else:
        db.commit()
        delete_cache_prefix("snkrdunk_candidates")

    return RematchAllOut(dry_run=body.dry_run, **counts)


@router.post("/{candidate_id}/approve-match", response_model=SnkrdunkCandidateOut)
def approve_match(candidate_id: int, body: ApproveMatchIn, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    card = db.get(Card, body.card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    source = _get_snkrdunk_source(db)

    match_result = calculate_candidate_match(candidate, card)

    mapping = (
        db.query(SourceCardMapping)
        .filter_by(source_id=source.id, source_url=candidate.source_url)
        .one_or_none()
    )
    review_notes = body.review_notes
    if review_notes is None and match_result.explanation.positive:
        review_notes = (
            f"Approved via matching review (score={match_result.score}, "
            f"confidence={match_result.confidence_label}): "
            + "; ".join(match_result.explanation.positive[:3])
        )
    if mapping is None:
        mapping = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=candidate.detected_card_code or candidate.source_url,
        )
        db.add(mapping)

    mapping.card_id = card.id
    mapping.source_card_id = candidate.detected_card_code or candidate.source_url
    mapping.source_url = candidate.source_url
    mapping.manual_verified = True
    mapping.review_status = "approved"
    mapping.is_active = True
    mapping.match_confidence = match_result.score
    mapping.review_notes = review_notes

    candidate.match_status = "matched"
    candidate.matched_card_id = card.id
    candidate.match_confidence = match_result.score / 100.0
    candidate.best_match_card_id = card.id
    candidate.best_match_score = match_result.score
    candidate.best_match_confidence_label = match_result.confidence_label
    candidate.match_explanation_json = match_result.explanation.to_dict()
    candidate.ambiguous_matches_json = None

    db.commit()
    db.refresh(candidate)
    delete_cache_prefix("snkrdunk_candidates")
    record_app_log(
        "info",
        "api",
        "snkrdunk_matching",
        f"Candidate {candidate.id} approved -> card_id={card.id} (score={match_result.score}).",
        context={"candidate_id": candidate.id, "card_id": card.id, "score": match_result.score},
        related_entity_type="snkrdunk_candidate",
        related_entity_id=candidate.id,
    )
    return _to_candidate_out(db, candidate)


@router.post("/{candidate_id}/reject-match", response_model=SnkrdunkCandidateOut)
def reject_match(candidate_id: int, body: RejectMatchIn, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    candidate.match_status = "rejected"
    db.commit()
    db.refresh(candidate)
    delete_cache_prefix("snkrdunk_candidates")
    record_app_log(
        "info",
        "api",
        "snkrdunk_matching",
        f"Candidate {candidate.id} match rejected." + (f" Notes: {body.review_notes}" if body.review_notes else ""),
        context={"candidate_id": candidate.id, "review_notes": body.review_notes},
        related_entity_type="snkrdunk_candidate",
        related_entity_id=candidate.id,
    )
    return _to_candidate_out(db, candidate)
