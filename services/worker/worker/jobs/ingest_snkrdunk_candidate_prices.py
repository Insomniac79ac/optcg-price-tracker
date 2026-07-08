"""Creates price_observations from SNKRDUNK candidates that have already been
matched to a canonical card (via live discovery or manual CSV import +
review). This is a pure DB-to-DB job - it does not scrape SNKRDUNK.
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from worker.db import SessionLocal
from worker.matching.candidate_store import get_snkrdunk_source
from worker.models import PriceObservation, SnkrdunkCandidate

logger = logging.getLogger(__name__)

PRICE_TYPE = "floor"
ELIGIBLE_STATUSES_ONLY_MATCHED = ("auto_matched",)
ELIGIBLE_STATUSES_ALL = ("auto_matched", "needs_review")


@dataclass
class IngestSummary:
    candidates_checked: int = 0
    observations_created: int = 0
    observations_skipped_duplicate: int = 0
    candidates_skipped_unmatched: int = 0
    candidates_skipped_missing_price: int = 0

    def print_report(self) -> None:
        print(f"candidates_checked: {self.candidates_checked}")
        print(f"observations_created: {self.observations_created}")
        print(f"observations_skipped_duplicate: {self.observations_skipped_duplicate}")
        print(f"candidates_skipped_unmatched: {self.candidates_skipped_unmatched}")
        print(f"candidates_skipped_missing_price: {self.candidates_skipped_missing_price}")


def _is_duplicate(
    db: Session, candidate: SnkrdunkCandidate, source_id: int, observed_at: datetime
) -> bool:
    """Candidate-based dedup first (cheap and exact once candidate_id is
    populated), falling back to a same-day composite match for observations
    that predate the candidate_id column or were created via another path."""
    existing_by_candidate = (
        db.query(PriceObservation).filter_by(candidate_id=candidate.id).first()
    )
    if existing_by_candidate is not None:
        return True

    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    existing = (
        db.query(PriceObservation)
        .filter(
            PriceObservation.card_id == candidate.matched_card_id,
            PriceObservation.source_id == source_id,
            PriceObservation.price_type == PRICE_TYPE,
            PriceObservation.price_jpy == candidate.price_jpy,
            PriceObservation.condition_label == candidate.condition_label,
            PriceObservation.observed_at >= day_start,
            PriceObservation.observed_at < day_end,
        )
        .first()
    )
    return existing is not None


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

            if candidate.match_status not in eligible_statuses or candidate.matched_card_id is None:
                summary.candidates_skipped_unmatched += 1
                continue

            if candidate.price_jpy is None:
                summary.candidates_skipped_missing_price += 1
                continue

            observed_at = candidate.created_at or datetime.now(timezone.utc)

            if _is_duplicate(db, candidate, source.id, observed_at):
                summary.observations_skipped_duplicate += 1
                continue

            summary.observations_created += 1
            if dry_run:
                continue

            db.add(
                PriceObservation(
                    card_id=candidate.matched_card_id,
                    source_id=source.id,
                    observed_at=observed_at,
                    price_type=PRICE_TYPE,
                    price_jpy=candidate.price_jpy,
                    condition_label=candidate.condition_label,
                    stock_status=None,
                    listing_count=candidate.listing_count,
                    raw_snapshot_id=None,
                    candidate_id=candidate.id,
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
            "Create price_observations from matched SNKRDUNK candidates "
            "(manual CSV import + review is the current source of these). "
            "Does not scrape SNKRDUNK."
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
        help="Restrict to match_status=auto_matched (default). Pass --no-only-matched to "
        "also consider needs_review candidates that already carry an advisory matched_card_id.",
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
