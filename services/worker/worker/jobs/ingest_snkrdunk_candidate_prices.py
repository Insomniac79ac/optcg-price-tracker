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
and `approved`, and stamp the observation with the mapping's own
`card_print_id`, `source_card_mapping_id` and `card_id`. `card_id` may be
NULL on a print-authoritative mapping and is passed through exactly as it is
found; the composite FK
(source_card_mapping_id, card_print_id, source_id) is what keeps the row
honest, and it is enforced by the database, not here.

LEGACY MAPPINGS STILL PRICE. A mapping that predates exact prints
(card_print_id IS NULL, card_id set) is still ingested, and stamps neither
lineage column - the same both-or-neither rule refresh_prices follows, and
the same one ck_price_observations_lineage_paired enforces.
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from worker.db import SessionLocal
from worker.matching.candidate_store import get_snkrdunk_source
from worker.models import PriceObservation, SnkrdunkCandidate, SourceCardMapping

logger = logging.getLogger(__name__)

PRICE_TYPE = "floor"
ELIGIBLE_STATUSES_ONLY_MATCHED = ("matched",)
ELIGIBLE_STATUSES_ALL = ("matched", "suggested")

# Only an approved mapping is a statement that a human confirmed which
# printing this listing sells. `needs_review` and `rejected` are explicitly
# not that, and an inactive row has been withdrawn.
APPROVED_REVIEW_STATUS = "approved"


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

    Keyed on (source_id, source_url) - the database's own uniqueness contract
    for a listing (`uq_source_card_mappings_source_url`), and the same key the
    api's approval endpoints write through - never on the candidate's legacy
    card pointer, which cannot distinguish two printings of one card.

    Returns None rather than raising for every "not priceable" shape, so the
    caller can count it and move on:

      * no source_url to key on;
      * no mapping, or one that is inactive or not `approved`;
      * a mapping that names neither a print nor a legacy card, which
        identifies nothing at all and must never become an observation.
    """
    if not candidate.source_url:
        return None

    mapping = (
        db.query(SourceCardMapping)
        .filter(
            SourceCardMapping.source_id == source_id,
            SourceCardMapping.source_url == candidate.source_url,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.review_status == APPROVED_REVIEW_STATUS,
        )
        .one_or_none()
    )
    if mapping is None:
        return None
    if mapping.card_print_id is None and mapping.card_id is None:
        return None
    return mapping


def _is_duplicate(
    db: Session,
    candidate: SnkrdunkCandidate,
    mapping: SourceCardMapping,
    source_id: int,
    observed_at: datetime,
) -> bool:
    """Candidate-based dedup first (cheap and exact once candidate_id is
    populated), falling back to a same-day composite match for observations
    that predate the candidate_id column or were created via another path.

    The fallback matches on whatever actually identifies the row. For a
    print-authoritative observation that is the lineage pair, NOT card_id:
    `card_id` is NULL there, and `PriceObservation.card_id == None` renders as
    `card_id IS NULL`, which would match every other print-authoritative row
    in the same day at the same price and suppress a legitimate observation.
    Legacy rows keep the card_id comparison they always had.
    """
    existing_by_candidate = (
        db.query(PriceObservation).filter_by(candidate_id=candidate.id).first()
    )
    if existing_by_candidate is not None:
        return True

    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    query = db.query(PriceObservation).filter(
        PriceObservation.source_id == source_id,
        PriceObservation.price_type == PRICE_TYPE,
        PriceObservation.price_jpy == candidate.price_jpy,
        PriceObservation.condition_label == candidate.condition_label,
        PriceObservation.observed_at >= day_start,
        PriceObservation.observed_at < day_end,
    )
    if mapping.card_print_id is not None:
        query = query.filter(
            PriceObservation.source_card_mapping_id == mapping.id,
            PriceObservation.card_print_id == mapping.card_print_id,
        )
    else:
        query = query.filter(PriceObservation.card_id == mapping.card_id)

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

            observed_at = candidate.created_at or datetime.now(timezone.utc)

            if _is_duplicate(db, candidate, mapping, source.id, observed_at):
                summary.observations_skipped_duplicate += 1
                continue

            summary.observations_created += 1
            if dry_run:
                continue

            # Lineage is copied from the mapping, never derived - and stamped
            # both-or-neither, which is what ck_price_observations_lineage_
            # paired requires. This mirrors refresh_prices exactly, so the
            # Yuyu-Tei and SNKRDUNK write paths cannot drift apart.
            if mapping.card_print_id is not None:
                source_card_mapping_id = mapping.id
                observation_card_print_id = mapping.card_print_id
            else:
                source_card_mapping_id = None
                observation_card_print_id = None

            db.add(
                PriceObservation(
                    # Straight through from the mapping, NULL included. The
                    # observation must not claim a legacy card the mapping
                    # itself does not claim.
                    card_id=mapping.card_id,
                    source_id=source.id,
                    observed_at=observed_at,
                    price_type=PRICE_TYPE,
                    price_jpy=candidate.price_jpy,
                    condition_label=candidate.condition_label,
                    stock_status=None,
                    listing_count=candidate.listing_count,
                    raw_snapshot_id=None,
                    candidate_id=candidate.id,
                    source_card_mapping_id=source_card_mapping_id,
                    card_print_id=observation_card_print_id,
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
