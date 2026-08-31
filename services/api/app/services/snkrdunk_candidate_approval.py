"""The one operation that turns a reviewed SNKRDUNK candidate into a mapping.

WHY THIS MODULE EXISTS. Approving a candidate used to live entirely inside
`POST /admin/snkrdunk-candidates/{id}/approve-match`. That was fine while a
human clicking a button was the only way it could happen. It stops being fine
the moment a second caller wants to approve - a batch job over a reviewed
plan, in this case - because the two callers would then each have their own
copy of what "approved" writes, and the copies would drift. `manual_verified`
is exactly the field that must not drift: the collector's eligibility filter
reads it, so a second writer that sets it under weaker conditions silently
widens what gets priced.

So the write is here, once, and BOTH callers run it. There is no "batch
approval semantics" - there is the approval, invoked twice.

WHAT IT DELIBERATELY DOES NOT DO:

  * It does not commit. The endpoint commits its single row; the batch job
    commits the whole plan in one transaction. Neither behaviour belongs to
    the operation itself.
  * It does not decide whether the print is right. `resolve_exact_print` does
    that, and this function calls it and lets the refusal out untouched.
  * It does not fetch anything, and it does not write a price.

WHAT `manual_verified = True` MEANS HERE, since this module is now the only
place that sets it. It records that a person decided this listing prices this
printing - not that the resolver was confident. Both callers satisfy that: the
endpoint is a click on a reviewed screen, and the batch job requires the
operator to have read the printed plan and to type the confirmation phrase
back. What neither caller may do is reach this function without a human
having seen the specific candidate/print pair, which is why the batch job
refuses an unscoped run.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from sqlalchemy import select

from app.models import Card, Source, SourceCardMapping
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.services.card_matching import CandidateMatchResult, calculate_candidate_match
from app.services.exact_print_approval import (
    REFUSAL_MAPPING_WAS_REJECTED,
    REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
    ApprovalDecision,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
)
from app.services.snkrdunk_urls import canonical_listing_url, listing_id

APPROVED = "approved"
MATCHED = "matched"


class SnkrdunkSourceMissing(RuntimeError):
    """The `snkrdunk` row is absent from `sources`.

    A deployment fault, not a judgement about the candidate, so it is a
    distinct exception rather than an ExactPrintApprovalError - callers must
    not be able to mistake it for a refusal that a human could resolve by
    looking at the listing.
    """


@dataclass
class CandidateApprovalResult:
    """What one approval did, for the caller to report on.

    `mapping_created` is the difference between a new priced listing and a
    re-approval of one that already existed, and the batch job reports the two
    separately - a run that "approved 30" but created 4 mappings has not done
    what the operator thought it did.
    """

    candidate: SnkrdunkCandidate
    mapping: SourceCardMapping
    decision: ApprovalDecision
    mapping_created: bool
    card: Card | None
    match_result: CandidateMatchResult | None
    canonical_url: str


def get_snkrdunk_source(db: Session) -> Source:
    source = db.query(Source).filter_by(name="snkrdunk").one_or_none()
    if source is None:
        raise SnkrdunkSourceMissing("snkrdunk source is not configured")
    return source


REJECTED = "rejected"


def find_mapping_for_listing(
    db: Session, *, source: Source, url: str | None
) -> SourceCardMapping | None:
    """The one mapping that already holds this listing, or None.

    KEYED ON LISTING IDENTITY, NOT ON URL EQUALITY, and that distinction is
    the whole reason this function exists rather than a `source_url IN (...)`
    filter inline at each call site.

    SNKRDUNK publishes one listing under two paths, and discovery stores
    whatever it saw - including the query string. Staging mapping 8 is

        https://snkrdunk.com/en/trading-cards/94915?slide=right&query_id=9d4a...

    which a person set to `rejected` on 2026-08-09. Matching on the two
    canonical spellings does not find that row, so an approval of the same
    listing found nothing, created a SECOND mapping at the canonical URL - no
    `uq_source_card_mappings_source_url` collision, because the stored strings
    genuinely differ - and the human's refusal was overturned by a row nobody
    looked at. One listing then had two mappings, and the collector would have
    priced the new one.

    So the question asked here is the one the operator means: is any mapping
    already about this listing? `listing_id` parses the id out of either path
    and tolerates the query string; the SQL `LIKE` is only a cheap pre-filter
    and the parsed id is what decides, so no row is matched loosely.

    RAISES rather than choosing when more than one mapping claims the listing.
    Picking one would leave the other pointing at a print nobody re-examined.

    Returns None for a URL that is not a recognised listing at all. That is
    not a silent pass: every caller goes on to `canonical_listing_url`, which
    refuses the same URL with `source_url_not_canonical`.
    """
    parsed = listing_id(url)
    if parsed is None:
        return None
    rows = db.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.source_url.like(f"%{parsed}%"),
        )
    ).all()
    matches = [m for m in rows if listing_id(m.source_url) == parsed]
    if len(matches) > 1:
        raise ExactPrintApprovalError(
            REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
            f"SNKRDUNK listing {parsed} is already held by {len(matches)} mappings "
            f"({sorted(m.id for m in matches)}). Approving would have to choose one and "
            "leave the others pointing at printings nobody re-examined. Resolve the "
            "duplicates first.",
            alternatives=sorted(m.id for m in matches),
        )
    return matches[0] if matches else None


def assert_mapping_may_be_approved(mapping: SourceCardMapping | None) -> None:
    """Refuse to reuse a mapping a person has already refused.

    Deliberately narrow: it blocks ONE transition, `rejected` -> approved, and
    says nothing about any other state. A `needs_review` row is still a row
    the approval path is meant to advance, and an already-`approved` one is
    the ordinary re-approval case.
    """
    if mapping is not None and mapping.review_status == REJECTED:
        raise ExactPrintApprovalError(
            REFUSAL_MAPPING_WAS_REJECTED,
            f"Source mapping {mapping.id} for this listing was REJECTED by a person "
            f"({(mapping.review_notes or '')[:160]!r}). Approving it here would overturn "
            "that decision without anyone reading why it was made. Clear the rejection "
            "explicitly first.",
        )


def approve_candidate_onto_print(
    db: Session,
    *,
    candidate: SnkrdunkCandidate,
    card_print_id: int | None,
    card: Card | None = None,
    review_notes: str | None = None,
    source: Source | None = None,
) -> CandidateApprovalResult:
    """Approve one candidate onto one printing. Flushes; never commits.

    Raises `ExactPrintApprovalError` on every path that cannot prove the
    print, before anything is written, so a refused candidate leaves the
    session exactly as it was.

    THE LEGACY CARD IS OPTIONAL, AND THAT IS THE POINT. What this writes is a
    claim about which *printing* was priced, and `card_print_id` carries that
    claim on its own. `cards` holds 25 rows against 4,281 active verified
    prints, so for almost every listing there is no legacy row to name -
    demanding one would mean either refusing to price 98.6% of the catalogue
    or manufacturing a `cards` row whose identity columns the 2026-08-27 audit
    showed to be unreliable. `card_id` is simply left NULL (allowed since
    c9f31e2a7d04).
    """
    source = source or get_snkrdunk_source(db)

    # THE EXACT-PRINT GATE. Nothing is written until the source's own stored
    # evidence corroborates the printing named - see
    # app.services.exact_print_approval.
    decision = resolve_exact_print(
        db,
        card_print_id=card_print_id,
        evidence=SourceEvidence.from_snkrdunk_candidate(candidate),
    )

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
    mapping_url = canonical_listing_url(
        candidate.source_url, card_print_language=decision.card_print.language
    )

    # Looked up by LISTING IDENTITY - see find_mapping_for_listing for why URL
    # equality was not enough and what it cost. Re-approving a listing first
    # approved under the other path (or stored with discovery's query string)
    # updates that row instead of creating a second mapping for one listing.
    mapping = find_mapping_for_listing(db, source=source, url=candidate.source_url)
    assert_mapping_may_be_approved(mapping)
    mapping_created = mapping is None

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
    # loss this operation has no business causing.
    if card is not None:
        mapping.card_id = card.id
    # THE AUTHORITATIVE IDENTITY of the mapping. Unlike card_id above this is
    # never optional: an approval that cannot name the exact print never
    # reaches this line - resolve_exact_print raised instead.
    mapping.card_print_id = decision.card_print.id
    mapping.source_card_id = candidate.detected_card_code or candidate.source_url
    mapping.source_url = mapping_url
    mapping.manual_verified = True
    mapping.review_status = APPROVED
    mapping.is_active = True
    mapping.review_notes = review_notes
    if match_result is not None:
        mapping.match_confidence = match_result.score

    candidate.match_status = MATCHED
    # A print-authoritative approval neither sets nor clears the candidate's
    # legacy card pointer or its card-level scores. They describe a legacy
    # match that was not made here.
    if match_result is not None:
        candidate.matched_card_id = card.id
        candidate.match_confidence = match_result.score / 100.0
        candidate.best_match_card_id = card.id
        candidate.best_match_score = match_result.score
        candidate.best_match_confidence_label = match_result.confidence_label
        candidate.match_explanation_json = match_result.explanation.to_dict()
    candidate.ambiguous_matches_json = None

    # So the caller can report the mapping id without committing.
    db.flush()

    return CandidateApprovalResult(
        candidate=candidate,
        mapping=mapping,
        decision=decision,
        mapping_created=mapping_created,
        card=card,
        match_result=match_result,
        canonical_url=mapping_url,
    )


__all__ = [
    "APPROVED",
    "REJECTED",
    "assert_mapping_may_be_approved",
    "find_mapping_for_listing",
    "MATCHED",
    "CandidateApprovalResult",
    "ExactPrintApprovalError",
    "SnkrdunkSourceMissing",
    "approve_candidate_onto_print",
    "get_snkrdunk_source",
]
