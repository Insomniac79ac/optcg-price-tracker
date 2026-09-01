"""The one operation that turns a reviewed Yuyu-Tei candidate into a mapping.

THIS IS THE SNKRDUNK APPROVAL, WITH A DIFFERENT FRONT DOOR. It reuses
`resolve_exact_print` unchanged, raises the same `ExactPrintApprovalError`,
writes the same `source_card_mappings` columns with the same meanings, and is
mapped to HTTP by the same `approval_http_error`. There is no second notion of
"approved" here - see app.services.snkrdunk_candidate_approval, which this
mirrors deliberately rather than abstracting: two sources with genuinely
different provenance evidence are clearer as two thin callers of one gate than
as one function with a source switch inside it.

WHAT IS ACTUALLY NEW: FOUR PROVENANCE GUARDS. SNKRDUNK candidates come from a
sitemap walk where each listing stands alone, so a candidate is as good today
as the day it was discovered. A Yuyu-Tei `print_matched` classification is not
like that. It is a statement about CARDINALITY - one own-series product with
this card code, one active print in the family - and both halves can be
falsified after the fact:

  * the enumeration that measured "one product" may have been truncated by
    the product or page cap, in which case one is a floor and the parallel
    may be on the page that was never fetched;
  * the run may have died part-way, so its measurements are partial;
  * a LATER complete enumeration of the same slug may since have found the
    sibling, which demotes the code to family_matched - and the older
    candidate row still says print_matched because it is a different row for
    a different product.

So the guards below ask what SNKRDUNK never has to: is this candidate still
the current reading of a complete, finished enumeration of its set?

WHAT IT DELIBERATELY DOES NOT DO:
  * it does not commit - the endpoint owns the transaction;
  * it does not fetch anything, from Yuyu-Tei or anywhere else;
  * it writes no price observation, and never turns the candidate's listing
    price into one. `price_jpy` is what the shelf said at discovery time; an
    observation is a measurement the collector makes, and conflating them
    would invent a price nobody collected;
  * it does not invoke the collector, the batch, or Market Index;
  * it does not touch artwork. `resolve_exact_print` is called with no
    artwork verdict, so `_narrow_by_artwork` fails open and no image is
    consulted.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source, SourceCardMapping
from app.models.yuyutei_candidate import YuyuteiCandidate
from app.models.yuyutei_discovery_run import YuyuteiDiscoveryRun
from app.services.exact_print_approval import (
    REFUSAL_CANDIDATE_NOT_PRINT_MATCHED,
    REFUSAL_CANDIDATE_SUPERSEDED,
    REFUSAL_DISCOVERY_RUN_INCOMPLETE,
    REFUSAL_MAPPING_NAMES_ANOTHER_PRINT,
    REFUSAL_MAPPING_WAS_REJECTED,
    REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
    REFUSAL_SOURCE_LISTING_TRUNCATED,
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
    ApprovalDecision,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
)
from app.services.yuyutei_urls import canonical_listing_url, listing_identity

APPROVED = "approved"
REJECTED = "rejected"
PRINT_MATCHED = "print_matched"
RUN_COMPLETED = "completed"

YUYUTEI_SOURCE_NAME = "yuyutei"


class YuyuteiSourceMissing(RuntimeError):
    """The `yuyutei` row is absent from `sources`.

    A deployment fault, not a judgement about the candidate, so it is a
    distinct exception rather than an ExactPrintApprovalError - callers must
    not be able to mistake it for a refusal a human could resolve by looking
    at the listing. Mirrors SnkrdunkSourceMissing.
    """


@dataclass
class YuyuteiApprovalResult:
    """What one approval did, for the caller to report on.

    `mapping_created` separates a genuinely new priced listing from the
    re-approval of one that already existed. A run that "approved 194" but
    created 4 mappings has not done what the operator thought it did.
    """

    candidate: YuyuteiCandidate
    mapping: SourceCardMapping
    decision: ApprovalDecision
    mapping_created: bool
    canonical_url: str


def get_yuyutei_source(db: Session) -> Source:
    source = db.query(Source).filter_by(name=YUYUTEI_SOURCE_NAME).one_or_none()
    if source is None:
        raise YuyuteiSourceMissing("yuyutei source is not configured")
    return source


def assert_candidate_is_print_matched(candidate: YuyuteiCandidate) -> None:
    """Only a `print_matched` candidate names a printing at all.

    `ck_yuyutei_candidates_print_requires_print_matched` already makes a print
    id unrepresentable outside that status, so this check and the NULL check
    below cannot both be silently wrong - but it is stated explicitly anyway,
    because a refusal an operator can read beats a constraint violation.
    """
    if candidate.match_status != PRINT_MATCHED:
        raise ExactPrintApprovalError(
            REFUSAL_CANDIDATE_NOT_PRINT_MATCHED,
            f"Candidate {candidate.id} is {candidate.match_status!r}, not "
            f"{PRINT_MATCHED!r}. That status is the classification's own statement "
            "that the card code did not resolve to exactly one printing, and "
            "approving it would assert the identity discovery declined to assert.",
        )


def assert_enumeration_is_trustworthy(db: Session, candidate: YuyuteiCandidate) -> None:
    """The candidate must be the current reading of a complete, finished
    enumeration of its own set slug.

    Three separate facts, refused separately so the operator is told which one
    failed:

      1. its run finished with status 'completed';
      2. its slug's enumeration in that run was not truncated;
      3. no LATER completed run has re-enumerated the same slug.

    (3) is the one that is easy to miss. Candidates are keyed on
    (set_slug, product_id) and refreshed in place, so a re-discovered product
    carries the newest run id - but a product that has since DISAPPEARED from
    the listing keeps its old run id and its old, now-unverifiable
    classification. Approving that row would price a listing that the most
    recent look at the source did not find.
    """
    run = (
        db.get(YuyuteiDiscoveryRun, candidate.discovery_run_id)
        if candidate.discovery_run_id
        else None
    )
    if run is None or run.status != RUN_COMPLETED:
        raise ExactPrintApprovalError(
            REFUSAL_DISCOVERY_RUN_INCOMPLETE,
            f"Candidate {candidate.id} came from discovery run "
            f"{candidate.discovery_run_id!r}, which is "
            f"{(run.status if run else 'missing')!r} rather than {RUN_COMPLETED!r}. "
            "A run that did not finish measured only part of the source, so nothing "
            "counted in it is a complete statement about how many products carry "
            "this card code.",
        )

    metrics = (run.per_slug_metrics_json or {}).get(candidate.set_slug)
    if metrics is None or not metrics.get("enumeration_complete"):
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_LISTING_TRUNCATED,
            f"Run {run.id} did not enumerate {candidate.set_slug!r} to the end "
            f"({'no metrics recorded' if metrics is None else 'enumeration_complete=false'}). "
            "The observed count of products sharing this card code is a floor, not a "
            "total, so source-side uniqueness is unproven and print_matched cannot be "
            "acted on. Re-run discovery for this set with a budget that completes it.",
        )

    newer = db.scalars(
        select(YuyuteiDiscoveryRun)
        .where(
            YuyuteiDiscoveryRun.status == RUN_COMPLETED,
            YuyuteiDiscoveryRun.id > run.id,
        )
        .order_by(YuyuteiDiscoveryRun.id.asc())
    ).all()
    superseding = [
        r for r in newer if candidate.set_slug in (r.requested_set_slugs or [])
    ]
    if superseding:
        raise ExactPrintApprovalError(
            REFUSAL_CANDIDATE_SUPERSEDED,
            f"Candidate {candidate.id} is from run {run.id}, but "
            f"{candidate.set_slug!r} has been enumerated again since by run(s) "
            f"{[r.id for r in superseding]} and this row was not refreshed - so the "
            "most recent look at the source did not find this product. Its "
            "classification cannot be confirmed against the current listing.",
            alternatives=[r.id for r in superseding],
        )


def assert_source_identity_is_intact(candidate: YuyuteiCandidate) -> tuple[str, str]:
    """The stored URL must still spell the candidate's own natural key.

    Returns the parsed `(set_slug, product_id)`. Identity on Yuyu-Tei is the
    PAIR - product ids repeat across category slugs (10152-10154 exist in both
    op01 and op13) - so a URL whose slug or id has drifted from the columns is
    not a cosmetic mismatch: it means the row and the page it points at are
    about different products, and whichever one the mapping recorded would be
    a coin toss.
    """
    identity = listing_identity(candidate.source_url)
    if identity is None:
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_URL_NOT_CANONICAL,
            f"Candidate {candidate.id} has source_url {candidate.source_url!r}, which "
            "is not a recognised Yuyu-Tei product URL, so the collector could not be "
            "pointed at the page this approval is about.",
        )
    if identity != (candidate.set_slug, candidate.product_id):
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_URL_NOT_CANONICAL,
            f"Candidate {candidate.id} is keyed on "
            f"{(candidate.set_slug, candidate.product_id)} but its source_url names "
            f"{identity}. The row and the page it points at are about different "
            "products; neither can be approved until they agree.",
        )
    return identity


def find_mapping_for_listing(
    db: Session, *, source: Source, url: str | None
) -> SourceCardMapping | None:
    """The one mapping that already holds this listing, or None.

    KEYED ON LISTING IDENTITY, NOT ON URL EQUALITY - the same lesson as
    snkrdunk_candidate_approval.find_mapping_for_listing, and for the same
    reason. A stored URL may carry a query string or a trailing slash, and a
    plain `source_url ==` filter would miss it, find nothing, and create a
    SECOND mapping for one listing without tripping
    `uq_source_card_mappings_source_url` - because the stored strings really
    do differ. The parsed `(set_slug, product_id)` is what decides; the SQL
    LIKE is only a cheap pre-filter.

    The LIKE pattern uses `/slug/product_id` rather than the bare product id
    on purpose. Product ids repeat across slugs, so `%10152%` would pre-select
    op01's product when approving op13's - and would also match any id merely
    CONTAINING those digits.

    RAISES rather than choosing when more than one mapping claims the
    listing: picking one would leave the other pointing at a print nobody
    re-examined.

    Returns None for a URL that is not a recognised listing - including the
    two legacy card-code rows on staging, which are not listings. That is not
    a silent pass: `assert_source_identity_is_intact` has already refused any
    candidate whose URL cannot be parsed.
    """
    identity = listing_identity(url)
    if identity is None:
        return None
    set_slug, product_id = identity
    rows = db.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.source_url.like(f"%/{set_slug}/{product_id}%"),
        )
    ).all()
    matches = [m for m in rows if listing_identity(m.source_url) == identity]
    if len(matches) > 1:
        raise ExactPrintApprovalError(
            REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
            f"Yuyu-Tei listing {set_slug}/{product_id} is already held by "
            f"{len(matches)} mappings ({sorted(m.id for m in matches)}). Approving "
            "would have to choose one and leave the others pointing at printings "
            "nobody re-examined. Resolve the duplicates first.",
            alternatives=sorted(m.id for m in matches),
        )
    return matches[0] if matches else None


def assert_mapping_may_be_approved(
    mapping: SourceCardMapping | None, card_print_id: int
) -> None:
    """Refuse to overwrite a decision somebody else already made.

    Two narrow transitions are blocked and nothing else:

      * `rejected` -> approved, which would overturn a human refusal without
        anyone reading why it was made;
      * an existing mapping that names a DIFFERENT print. One listing prices
        one printing, so the two claims cannot both be true, and silently
        repointing the row would discard the older one without review. An
        existing mapping naming the SAME print is the ordinary idempotent
        re-approval and passes.
    """
    if mapping is None:
        return
    if mapping.review_status == REJECTED:
        raise ExactPrintApprovalError(
            REFUSAL_MAPPING_WAS_REJECTED,
            f"Source mapping {mapping.id} for this listing was REJECTED by a person "
            f"({(mapping.review_notes or '')[:160]!r}). Approving it here would "
            "overturn that decision without anyone reading why it was made. Clear the "
            "rejection explicitly first.",
        )
    if mapping.card_print_id is not None and mapping.card_print_id != card_print_id:
        raise ExactPrintApprovalError(
            REFUSAL_MAPPING_NAMES_ANOTHER_PRINT,
            f"Source mapping {mapping.id} already prices this listing against "
            f"card_print {mapping.card_print_id}, not {card_print_id}. One listing "
            "sells one printing, so one of the two claims is wrong; repointing the "
            "row here would discard the existing one without review.",
            alternatives=[mapping.card_print_id],
        )


def approve_candidate(
    db: Session,
    *,
    candidate: YuyuteiCandidate,
    review_notes: str | None = None,
    source: Source | None = None,
) -> YuyuteiApprovalResult:
    """Approve one Yuyu-Tei candidate onto the printing it already names.

    Flushes; never commits. Raises `ExactPrintApprovalError` on every path
    that cannot prove the approval, BEFORE anything is written, so a refused
    candidate leaves the session exactly as it was.

    NO PRINT ARGUMENT IS TAKEN, and that is the substantive difference from
    the SNKRDUNK path. There, an operator chooses a print from the siblings
    and the resolver checks the choice. Here the print is not the operator's
    to choose: `matched_card_print_id` was written by discovery only when the
    card code resolved to exactly one active print, and the DB check
    constraint makes any other value unrepresentable. Accepting a print id
    from the request would create a way to approve a printing the
    classification never established - the exact hole this whole design
    exists to close. The operator's decision is *whether* to approve, not
    *what* to approve onto.

    THE LEGACY CARD IS NOT WRITTEN AT ALL. `card_prints` carries no link to
    the legacy `cards` table - only `canonical_card_id` - so there is nothing
    to derive a `card_id` from that would not be a guess, and `cards` holds 25
    rows against 4,316 prints. `card_id` is left NULL, exactly as a
    print-authoritative SNKRDUNK approval leaves it.
    """
    source = source or get_yuyutei_source(db)

    # --- provenance: may this candidate be approved at all? -------------
    # Ordered cheapest-and-most-specific first, so the refusal an operator
    # reads is the most actionable one rather than whichever check happened
    # to run first.
    assert_candidate_is_print_matched(candidate)
    assert_enumeration_is_trustworthy(db, candidate)
    assert_source_identity_is_intact(candidate)

    # --- the shared exact-print gate ------------------------------------
    # Unchanged, and called with no artwork verdict: `_narrow_by_artwork`
    # fails open on None, so no image is consulted anywhere on this path.
    # It re-checks the print exists, is active and is verified
    # (assert_print_is_priceable) and that the code the source displayed
    # matches the print's canonical card.
    decision = resolve_exact_print(
        db,
        card_print_id=candidate.matched_card_print_id,
        evidence=SourceEvidence.from_yuyutei_candidate(candidate),
    )

    # The URL the collector will fetch. Yuyu-Tei publishes one path per
    # product, so this normalises rather than chooses - but it still refuses
    # a shape it cannot parse rather than storing an unfetchable mapping.
    mapping_url = canonical_listing_url(candidate.source_url)

    mapping = find_mapping_for_listing(db, source=source, url=candidate.source_url)
    assert_mapping_may_be_approved(mapping, decision.card_print.id)
    mapping_created = mapping is None

    if review_notes is None:
        review_notes = (
            f"{decision.as_review_note()} Yuyu-Tei product "
            f"{candidate.set_slug}/{candidate.product_id}, discovery run "
            f"{candidate.discovery_run_id}."
        )

    if mapping is None:
        mapping = SourceCardMapping(
            source_id=source.id,
            source_card_id=candidate.detected_card_code,
        )
        db.add(mapping)

    # THE COLLECTOR READS source_card_id AS THE DISPLAYED CARD CODE and
    # compares it with `!=`, no normalisation, as both a page-presence marker
    # and a fail-closed identity check (yuyutei_collector/writer.py:
    # `card_code_mismatch_vs_mapping`). So it is the parsed code verbatim -
    # never the URL, which is what the SNKRDUNK path falls back to when its
    # code is missing. A Yuyu candidate with no code cannot get here at all:
    # it would be `unmatched`, and refused above.
    mapping.source_card_id = candidate.detected_card_code
    mapping.card_print_id = decision.card_print.id
    mapping.source_url = mapping_url
    mapping.manual_verified = True
    mapping.review_status = APPROVED
    mapping.is_active = True
    mapping.review_notes = review_notes

    # NOTHING IS WRITTEN TO THE CANDIDATE. Its `match_status` vocabulary is
    # catalogue cardinality - unmatched/family_matched/print_matched/
    # identity_conflict - and has no approval member; the DB check constraint
    # would reject one. Approval state is therefore DERIVED from the existence
    # of a mapping for the listing (see the review endpoint's `approved`
    # filter), which keeps one fact in one place instead of a status column
    # that can drift out of sync with the mappings table.

    # So the caller can report the mapping id without committing.
    db.flush()

    return YuyuteiApprovalResult(
        candidate=candidate,
        mapping=mapping,
        decision=decision,
        mapping_created=mapping_created,
        canonical_url=mapping_url,
    )


__all__ = [
    "APPROVED",
    "PRINT_MATCHED",
    "REJECTED",
    "YUYUTEI_SOURCE_NAME",
    "YuyuteiApprovalResult",
    "YuyuteiSourceMissing",
    "approve_candidate",
    "assert_candidate_is_print_matched",
    "assert_enumeration_is_trustworthy",
    "assert_mapping_may_be_approved",
    "assert_source_identity_is_intact",
    "find_mapping_for_listing",
    "get_yuyutei_source",
]
