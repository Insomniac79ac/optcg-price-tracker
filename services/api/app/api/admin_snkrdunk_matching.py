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
    ArtworkPreviewOut,
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
from app.services.artwork_preview import preview_candidate_artwork, summary_line
from app.services.display_image import get_display_images_for_prints
from app.services.exact_print_approval import (
    ExactPrintApprovalError,
    SourceEvidence,
    sibling_prints_for_card_code,
    printing_label,
    resolve_exact_print,
    special_print_label,
)
from app.services.snkrdunk_urls import canonical_listing_url, equivalent_listing_urls

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


@router.post("/{candidate_id}/artwork-preview", response_model=ArtworkPreviewOut)
def preview_artwork(candidate_id: int, db: Session = Depends(get_db)):
    """Advisory artwork evidence for one candidate, on explicit request.

    POST rather than GET, and its own endpoint rather than a field on
    /print-options, because it reaches out to a marketplace CDN and the
    official card list. Putting that on the page load would make browsing the
    candidate queue depend on third-party latency and hammer those hosts for
    operators who only wanted the list.

    Read-only in the strongest sense: it opens no transaction of its own,
    writes nothing, stores no hash or verdict, and cannot change what
    resolve_exact_print allows. It is available whether or not
    ARTWORK_EVIDENCE_ENABLED is set - that flag governs whether artwork may
    NARROW a resolution, which is a different question from whether an
    operator may look at the evidence.
    """
    candidate = _get_candidate_or_404(db, candidate_id)
    preview = preview_candidate_artwork(db, candidate)
    verdict = preview.verdict
    return ArtworkPreviewOut(
        status=verdict.status,
        summary=summary_line(preview),
        method_version=verdict.method_version,
        listing_image_url=preview.listing_image_url,
        considered_card_print_ids=list(preview.considered_print_ids),
        winning_card_print_ids=list(verdict.winning_class),
        winning_class_is_shared=preview.winning_class_is_shared,
        corroborates_card_print_id=verdict.card_print_id,
        best_score=verdict.best_score,
        runner_up_score=verdict.runner_up_score,
        margin=verdict.margin,
        detail=verdict.detail,
        fetch_errors=list(preview.fetch_errors),
    )


@router.post("/{candidate_id}/approve-match", response_model=SnkrdunkCandidateOut)
def approve_match(candidate_id: int, body: ApproveMatchIn, db: Session = Depends(get_db)):
    """Approve a candidate onto an exact printing.

    THE LEGACY CARD IS OPTIONAL HERE, AND THAT IS THE POINT. What this
    endpoint writes is a claim about which *printing* was priced, and
    `card_print_id` carries that claim on its own. `cards` holds 25 rows
    against 4,281 active verified prints, so for almost every listing there
    is no legacy row to name - demanding one would mean either refusing to
    price 98.6% of the catalogue or manufacturing a `cards` row whose
    identity columns the 2026-08-27 audit showed to be unreliable. Neither is
    acceptable, so `card_id` is simply left NULL (allowed since
    c9f31e2a7d04).

    Supplying `card_id` still works exactly as before, and is what the
    existing legacy mappings continue to do.
    """
    candidate = _get_candidate_or_404(db, candidate_id)
    # A dangling card_id is still a 404 - only *omitting* it is permitted.
    card = None
    if body.card_id is not None:
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

    # Only meaningful against a legacy card: the scorer compares the listing
    # title to a `cards` row. With no card there is nothing to score, and a
    # fabricated score would misrepresent how well-evidenced the approval is
    # - the exact-print decision above is the evidence.
    match_result = calculate_candidate_match(candidate, card) if card is not None else None

    # THE URL THE COLLECTOR WILL FETCH, not the one discovery happened to see.
    # SNKRDUNK serves one listing under a Japanese and an English path, and
    # the collector rejects a page whose <html lang> disagrees with the
    # print's language - so a jp print approved against the English mirror is
    # correct about identity and unpriceable. Derived from the listing id
    # alone; an unrecognised URL is refused, never rewritten on a guess.
    # See app.services.snkrdunk_urls.
    try:
        mapping_url = canonical_listing_url(
            candidate.source_url, card_print_language=decision.card_print.language
        )
    except ExactPrintApprovalError as exc:
        raise approval_http_error(exc) from exc

    # Looked up by the canonical URL too, so re-approving a listing that was
    # first approved under the other path updates that row instead of
    # colliding with uq_source_card_mappings_source_url.
    mapping = (
        db.query(SourceCardMapping)
        .filter(
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.source_url.in_(equivalent_listing_urls(candidate.source_url)),
        )
        .one_or_none()
    )
    review_notes = body.review_notes
    if review_notes is None:
        # The print, and what proved it, ahead of the card-level score: the
        # score says how well the title matched a legacy card, which is not
        # the fact this mapping is asserting.
        parts = [decision.as_review_note()]
        if match_result is not None and match_result.explanation.positive:
            parts.append(
                f"Card match score={match_result.score} "
                f"({match_result.confidence_label}): "
                + "; ".join(match_result.explanation.positive[:3])
            )
        review_notes = " ".join(parts)
    if mapping is None:
        mapping = SourceCardMapping(
            source_id=source.id,
            source_card_id=candidate.detected_card_code or candidate.source_url,
        )
        db.add(mapping)

    # Written only when a legacy card was actually supplied. Assigning None
    # here instead would silently ERASE the legacy pointer on an existing
    # mapping being re-approved against a corrected print, which is a data
    # loss this endpoint has no business causing.
    if card is not None:
        mapping.card_id = card.id
    # THE AUTHORITATIVE IDENTITY of the mapping. Unlike card_id above this is
    # never optional: an approval that cannot name the exact print never
    # reaches this line - resolve_exact_print raised instead.
    mapping.card_print_id = decision.card_print.id
    mapping.source_card_id = candidate.detected_card_code or candidate.source_url
    mapping.source_url = mapping_url
    mapping.manual_verified = True
    mapping.review_status = "approved"
    mapping.is_active = True
    mapping.review_notes = review_notes
    if match_result is not None:
        mapping.match_confidence = match_result.score

    candidate.match_status = "matched"
    # Same reasoning as mapping.card_id above - a print-authoritative approval
    # neither sets nor clears the candidate's legacy card pointer and its
    # card-level scores. They describe a legacy match that was not made here.
    if match_result is not None:
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
        f"(card_id={card.id if card else None}, "
        f"score={match_result.score if match_result else None}).",
        context={
            "candidate_id": candidate.id,
            "card_id": card.id if card is not None else None,
            "card_print_id": decision.card_print.id,
            "evidence_used": decision.evidence_used,
            "score": match_result.score if match_result is not None else None,
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
