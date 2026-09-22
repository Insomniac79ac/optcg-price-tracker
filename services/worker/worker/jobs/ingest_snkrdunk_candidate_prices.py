"""Creates price_observations from SNKRDUNK candidates whose listing has an
approved source_card_mapping. This is a pure DB-to-DB job - it does not
scrape SNKRDUNK.

WHAT DRIVES THIS JOB, AND WHY IT CHANGED. It used to key off
`candidate.matched_card_id`: a candidate that named a legacy `cards` row got
an observation attached to that card. That is the card-code-shaped claim the
whole 4F series exists to end. One card code routinely spans many printings
(OP02-013 is five on staging), so an observation attached to a card says
nothing about which physical item was sold, and `cards` cannot even name most
of the catalogue - 25 rows against 4,281 active verified prints.

So the approved mapping is now the authority. A listing prices something only
if a human approved it through the exact-print gate
(app.services.exact_print_approval in the api), and that approval is what
recorded the exact `card_print_id`. This job copies that lineage; it never
derives it, and never falls back to the card code.

Concretely, per candidate: find the mapping for (snkrdunk, source_url) - the
database's own uniqueness contract for a listing - require it to be active
and `approved`, require its print to exist, be active, and be verified, and
stamp the observation with the mapping's own `card_print_id`,
`source_card_mapping_id` and `card_id`. `card_id` may be NULL on a
print-authoritative mapping and is passed through exactly as it is found; the composite FK
(source_card_mapping_id, card_print_id, source_id) is what keeps the row
honest, and it is enforced by the database, not here.

Legacy card-only mappings remain stored but cannot authorize a NEW price.
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from worker.db import SessionLocal
from worker.mapping_gate import (
    PRICEABLE_MAPPING_CONDITIONS,
    PRICEABLE_PRINT_CONDITIONS,
    PriceableMappingLineage,
    load_priceable_mapping_lineage,
)
from worker.matching.candidate_store import get_snkrdunk_source
from worker.snkrdunk_urls import equivalent_listing_urls
from worker.models import CardPrint, PriceObservation, SnkrdunkCandidate, SourceCardMapping

logger = logging.getLogger(__name__)

PRICE_TYPE = "floor"
ELIGIBLE_STATUSES_ONLY_MATCHED = ("matched",)
ELIGIBLE_STATUSES_ALL = ("matched", "suggested")

@dataclass
class IngestSummary:
    candidates_checked: int = 0
    observations_created: int = 0
    observations_skipped_duplicate: int = 0
    candidates_skipped_unmatched: int = 0
    candidates_skipped_missing_price: int = 0
    # The listing has no approved, active mapping naming something priceable,
    # so nothing here knows what it would be pricing. Counted separately from
    # `unmatched` because the two are different operator problems: one is a
    # candidate nobody has triaged, the other is a candidate whose approval
    # was refused, withdrawn, or never made.
    candidates_skipped_no_approved_mapping: int = 0

    def print_report(self) -> None:
        print(f"candidates_checked: {self.candidates_checked}")
        print(f"observations_created: {self.observations_created}")
        print(f"observations_skipped_duplicate: {self.observations_skipped_duplicate}")
        print(f"candidates_skipped_unmatched: {self.candidates_skipped_unmatched}")
        print(f"candidates_skipped_missing_price: {self.candidates_skipped_missing_price}")
        print(
            "candidates_skipped_no_approved_mapping: "
            f"{self.candidates_skipped_no_approved_mapping}"
        )


def _approved_mapping_for(
    db: Session, source_id: int, candidate: SnkrdunkCandidate
) -> SourceCardMapping | None:
    """The approved mapping for this listing, or None.

    Keyed on (source_id, LISTING) - never on the candidate's legacy card
    pointer, which cannot distinguish two printings of one card.

    Matching is by listing IDENTITY rather than URL equality, because since
    4F-9 the two deliberately differ: discovery stores the English mirror
    `/en/trading-cards/{id}` while an approved jp mapping stores the Japanese
    `/apparels/{id}` the collector must fetch. Both name the same listing, so
    both are tried - as exact strings derived from the id, not a pattern
    match. `uq_source_card_mappings_source_url` still guarantees at most one
    row per URL, and a listing cannot have an approved mapping under both
    paths at once because the approval endpoints look the row up the same way.

    Returns None rather than raising for every "not priceable" shape, so the
    caller can count it and move on:

      * no source_url to key on;
      * no mapping, or one that is inactive or not `approved`;
      * a card-only mapping; or
      * a mapping whose print is missing, inactive, or unverified.
    """
    if not candidate.source_url:
        return None

    from opcg_source_identity import canonical_source_listing_identity
    identity = canonical_source_listing_identity("snkrdunk", candidate.source_url)
    listing_condition = (
        SourceCardMapping.canonical_source_listing_identity == identity if identity is not None
        else SourceCardMapping.source_url == candidate.source_url
    )
    current = db.query(SourceCardMapping.id).filter(
        SourceCardMapping.source_id == source_id,
        SourceCardMapping.superseded_at.is_(None), listing_condition,
    ).all()
    if len(current) != 1:
        return None  # Never silently choose among duplicate current claims.

    mapping = (
        db.query(SourceCardMapping)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .filter(
            SourceCardMapping.source_id == source_id,
            listing_condition,
            # The same active+approved rule refresh_prices and both
            # production collectors apply - see worker.mapping_gate.
            *PRICEABLE_MAPPING_CONDITIONS,
            *PRICEABLE_PRINT_CONDITIONS,
        )
        .order_by(SourceCardMapping.id)
        .first()
    )
    return mapping


def _is_duplicate(
    db: Session,
    candidate: SnkrdunkCandidate,
    lineage: PriceableMappingLineage,
    observed_at: datetime,
) -> bool:
    """Candidate-based dedup first (cheap and exact once candidate_id is
    populated), falling back to a same-day composite match for observations
    that predate the candidate_id column or were created via another path.

    The fallback matches on the exact lineage pair, NOT card_id:
    `card_id` is NULL there, and `PriceObservation.card_id == None` renders as
    `card_id IS NULL`, which would match every other print-authoritative row
    in the same day at the same price and suppress a legitimate observation.
    """
    existing_by_candidate = (
        db.query(PriceObservation).filter_by(candidate_id=candidate.id).first()
    )
    if existing_by_candidate is not None:
        return True

    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    query = db.query(PriceObservation).filter(
        PriceObservation.source_id == lineage.source_id,
        PriceObservation.price_type == PRICE_TYPE,
        PriceObservation.price_jpy == candidate.price_jpy,
        PriceObservation.condition_label == candidate.condition_label,
        PriceObservation.observed_at >= day_start,
        PriceObservation.observed_at < day_end,
    )
    query = query.filter(
        PriceObservation.source_card_mapping_id == lineage.mapping_id,
        PriceObservation.card_print_id == lineage.card_print_id,
    )

    return query.first() is not None


def ingest_snkrdunk_candidate_prices(
    db: Session | None = None,
    limit: int = 100,
    dry_run: bool = False,
    only_matched: bool = True,
    since_run_id: int | None = None,
) -> IngestSummary:
    summary = IngestSummary()
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    eligible_statuses = (
        ELIGIBLE_STATUSES_ONLY_MATCHED if only_matched else ELIGIBLE_STATUSES_ALL
    )

    try:
        source = get_snkrdunk_source(db)

        query = db.query(SnkrdunkCandidate)
        if since_run_id is not None:
            query = query.filter(SnkrdunkCandidate.discovery_run_id >= since_run_id)
        candidates = query.order_by(SnkrdunkCandidate.id).limit(limit).all()

        for candidate in candidates:
            summary.candidates_checked += 1

            # A cheap pre-filter on the candidate's own triage state. It is
            # deliberately no longer joined by "and it names a legacy card":
            # the approved mapping below is what decides whether this listing
            # prices anything, and a print-authoritative approval has no
            # legacy card to name.
            if candidate.match_status not in eligible_statuses:
                summary.candidates_skipped_unmatched += 1
                continue

            if candidate.price_jpy is None:
                summary.candidates_skipped_missing_price += 1
                continue

            mapping = _approved_mapping_for(db, source.id, candidate)
            if mapping is None:
                summary.candidates_skipped_no_approved_mapping += 1
                logger.info(
                    "Candidate %s has no approved active mapping for %s; skipping.",
                    candidate.id,
                    candidate.source_url,
                )
                continue

            lineage = load_priceable_mapping_lineage(
                db,
                mapping.id,
                expected_source_name="snkrdunk",
            )
            if lineage is None:
                summary.candidates_skipped_no_approved_mapping += 1
                logger.info(
                    "Candidate %s mapping %s no longer has valid SNKRDUNK "
                    "exact-print lineage; skipping.",
                    candidate.id,
                    mapping.id,
                )
                continue

            observed_at = candidate.created_at or datetime.now(timezone.utc)

            if _is_duplicate(db, candidate, lineage, observed_at):
                summary.observations_skipped_duplicate += 1
                continue

            summary.observations_created += 1
            if dry_run:
                continue

            db.add(
                PriceObservation(
                    # Straight through from the mapping, NULL included. The
                    # observation must not claim a legacy card the mapping
                    # itself does not claim.
                    card_id=lineage.card_id,
                    source_id=lineage.source_id,
                    observed_at=observed_at,
                    price_type=PRICE_TYPE,
                    price_jpy=candidate.price_jpy,
                    condition_label=candidate.condition_label,
                    stock_status=None,
                    listing_count=candidate.listing_count,
                    raw_snapshot_id=None,
                    candidate_id=candidate.id,
                    source_card_mapping_id=lineage.mapping_id,
                    card_print_id=lineage.card_print_id,
                )
            )
            # Flush so later candidates in this same run see this row for
            # duplicate detection (e.g. a repeated candidate_id in the batch).
            db.flush()

        if not dry_run:
            db.commit()
    finally:
        if owns_session:
            db.close()

    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description=(
            "Create price_observations from SNKRDUNK candidates whose listing "
            "has an approved source_card_mapping, using that mapping's exact "
            "card_print_id. Does not scrape SNKRDUNK."
        )
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max number of candidates to check."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would happen without writing to the database.",
    )
    parser.add_argument(
        "--only-matched", action=argparse.BooleanOptionalAction, default=True,
        help="Restrict to match_status=matched (default). Pass --no-only-matched to "
        "also consider suggested candidates. Note this only widens the candidate "
        "pre-filter: an approved, active source_card_mapping is still required, so a "
        "merely suggested listing is not priced by relaxing this.",
    )
    parser.add_argument(
        "--since-run-id", type=int, default=None,
        help="Only consider candidates with discovery_run_id >= this value.",
    )
    args = parser.parse_args()

    summary = ingest_snkrdunk_candidate_prices(
        limit=args.limit,
        dry_run=args.dry_run,
        only_matched=args.only_matched,
        since_run_id=args.since_run_id,
    )
    summary.print_report()


if __name__ == "__main__":
    main()
