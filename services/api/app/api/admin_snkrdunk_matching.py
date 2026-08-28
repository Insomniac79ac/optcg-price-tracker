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
    ApprovalContextOut,
    ApprovalPrintOptionOut,
    ApprovalSourceCandidateOut,
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
from app.api._mapping_approval import approval_http_error
from app.services.display_image import get_display_images_for_prints
from app.services.exact_print_approval import (
    ExactPrintApprovalError,
    SourceEvidence,
    sibling_prints_for_card_code,
    printing_label,
    resolve_exact_print,
    special_print_label,
)

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


@router.get("/{candidate_id}/print-options", response_model=ApprovalContextOut)
def get_print_options(candidate_id: int, db: Session = Depends(get_db)):
    """What the operator needs to see before approving a mapping.

    The listing on one side, and on the other every active verified printing
    that shares its card code - each with its artwork, names, product and
    printing type, and a straight yes/no on whether the stored evidence can
    justify approving it.

    The siblings that CANNOT be approved are returned too, and that is the
    point of the screen: when a card code covers five printings and the source
    named only the code, the operator should see the five and understand that
    nothing here distinguishes them, rather than be handed one row and asked
    to trust it.
    """
    candidate = _get_candidate_or_404(db, candidate_id)
    evidence = SourceEvidence.from_snkrdunk_candidate(candidate)

    siblings = (
        sibling_prints_for_card_code(db, evidence.card_code) if evidence.card_code else []
    )
    prints = [p for p, _ in siblings]
    display_images = get_display_images_for_prints(db, prints) if prints else {}

    # An ordinal is a disambiguator of last resort, so it is only assigned
    # where two options would otherwise be indistinguishable on screen.
    label_counts: dict[tuple, int] = {}
    for print_row, canonical in siblings:
        key = (canonical.card_code, print_row.release_product_code, print_row.language)
        label_counts[key] = label_counts.get(key, 0) + 1
    ordinals: dict[int, int] = {}
    seen: dict[tuple, int] = {}
    for print_row, canonical in sorted(siblings, key=lambda r: r[0].id):
        key = (canonical.card_code, print_row.release_product_code, print_row.language)
        if label_counts[key] > 1:
            seen[key] = seen.get(key, 0) + 1
            ordinals[print_row.id] = seen[key]

    options: list[ApprovalPrintOptionOut] = []
    approvable_ids: list[int] = []
    for print_row, canonical in sorted(siblings, key=lambda r: r[0].id):
        try:
            resolve_exact_print(db, card_print_id=print_row.id, evidence=evidence)
        except ExactPrintApprovalError as exc:
            approvable, code, detail = False, exc.code, exc.detail
        else:
            approvable, code, detail = True, None, None
            approvable_ids.append(print_row.id)
        options.append(
            ApprovalPrintOptionOut(
                card_print_id=print_row.id,
                card_code=canonical.card_code,
                name_en=canonical.name_en,
                name_jp=canonical.name_jp,
                display_image=display_images.get(print_row.id),
                image_url=print_row.image_url,
                found_in_product=print_row.release_product_code,
                rarity=canonical.rarity,
                special_print=special_print_label(print_row, canonical),
                printing=printing_label(print_row),
                art_ordinal=ordinals.get(print_row.id),
                language=print_row.language,
                approvable=approvable,
                refusal_code=code,
                refusal_detail=detail,
            )
        )

    ambiguity_reason = None
    if not options:
        ambiguity_reason = (
            "No active verified print shares this listing's card code."
            if evidence.card_code
            else "The listing has no detected card code, so no printing can be proposed."
        )
    elif evidence.has_unresolved_product:
        # Saying "approval needs evidence that names the product" would be
        # wrong here and would send the operator looking for something the
        # listing already supplied. The listing DID name a product; Atlas
        # cannot map it, and that is a gap in the catalogue or the alias
        # table, not in the source.
        ambiguity_reason = (
            f"The listing names product {evidence.product_label!r}, which does not resolve "
            f"to an Atlas release product, so none of the {len(options)} printing(s) below "
            "can be corroborated - not even if only one is shown. Add a verified product "
            "alias for that label, or import the product, before approving."
        )
    elif len(approvable_ids) != 1:
        ambiguity_reason = (
            f"{len(approvable_ids)} of {len(options)} printings can be justified from the "
            "stored evidence. Approval needs evidence that names the product or the artwork."
        )

    return ApprovalContextOut(
        candidate=ApprovalSourceCandidateOut(
            candidate_id=candidate.id,
            source="snkrdunk",
            title=candidate.title,
            source_url=candidate.source_url,
            source_image_url=candidate.image_url,
            detected_card_code=candidate.detected_card_code,
            detected_set_code=candidate.detected_set_code,
            detected_variant=candidate.detected_variant,
            detected_rarity=candidate.detected_rarity,
            price_jpy=candidate.price_jpy,
        ),
        options=options,
        resolvable_card_print_id=approvable_ids[0] if len(approvable_ids) == 1 else None,
        ambiguity_reason=ambiguity_reason,
    )


@router.post("/{candidate_id}/approve-match", response_model=SnkrdunkCandidateOut)
def approve_match(candidate_id: int, body: ApproveMatchIn, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    card = db.get(Card, body.card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    source = _get_snkrdunk_source(db)

    # THE EXACT-PRINT GATE. Nothing is written until the source's own stored
    # evidence corroborates the printing the operator named - see
    # app.services.exact_print_approval. A refusal that needs a human is 409
    # (the request was well-formed, the evidence was not sufficient); a
    # malformed or dangling reference is 400/404.
    try:
        decision = resolve_exact_print(
            db,
            card_print_id=body.card_print_id,
            evidence=SourceEvidence.from_snkrdunk_candidate(candidate),
        )
    except ExactPrintApprovalError as exc:
        raise approval_http_error(exc) from exc

    match_result = calculate_candidate_match(candidate, card)

    mapping = (
        db.query(SourceCardMapping)
        .filter_by(source_id=source.id, source_url=candidate.source_url)
        .one_or_none()
    )
    review_notes = body.review_notes
    if review_notes is None:
        # The print, and what proved it, ahead of the card-level score: the
        # score says how well the title matched a legacy card, which is not
        # the fact this mapping is asserting.
        parts = [decision.as_review_note()]
        if match_result.explanation.positive:
            parts.append(
                f"Card match score={match_result.score} "
                f"({match_result.confidence_label}): "
                + "; ".join(match_result.explanation.positive[:3])
            )
        review_notes = " ".join(parts)
    if mapping is None:
        mapping = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=candidate.detected_card_code or candidate.source_url,
        )
        db.add(mapping)

    mapping.card_id = card.id
    # Authoritative for every new approval. card_id above stays written only
    # because the column is NOT NULL and the legacy read paths still use it.
    mapping.card_print_id = decision.card_print.id
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
        f"Candidate {candidate.id} approved -> card_print_id={decision.card_print.id} "
        f"(card_id={card.id}, score={match_result.score}).",
        context={
            "candidate_id": candidate.id,
            "card_id": card.id,
            "card_print_id": decision.card_print.id,
            "evidence_used": decision.evidence_used,
            "score": match_result.score,
        },
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
