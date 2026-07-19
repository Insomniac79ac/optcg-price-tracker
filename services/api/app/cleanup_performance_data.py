"""Deletes the synthetic TEST-PERF-* data created by
app.seed_performance_data - see 'Performance testing' in
docs/performance_testing.md.

Deletes are scoped as narrowly as possible: cards are looked up by exact
card_code prefix first to get their primary key ids, and every dependent
row is then deleted by id (card_id IN (...) / user_id IN (...)) rather than
by re-matching on a data value - the same TEST-PERF card_code prefix can
never collide with a real card code (real ones look like OP01-001), but
child tables are still deleted by the parent's id, not by guessing at their
own content, to keep this safe even if that ever changes. Activity/log
events are identified by the exact event_type="test_perf_seed" marker set
by the seed script, never by matching on message text.

Requires --confirm DELETE_TEST_PERF_DATA - refuses to run otherwise.

Usage:
  python -m app.cleanup_performance_data --confirm DELETE_TEST_PERF_DATA
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    AppLogEvent,
    Card,
    CollectionItem,
    CollectorActivityEvent,
    PriceObservation,
    Source,
    SourceCardMapping,
    User,
    WishlistItem,
)
from app.seed_performance_data import (
    CARD_CODE_PREFIX,
    SEED_MARKER,
    TEST_SOURCE_NAME,
    TEST_USER_GOOGLE_SUB,
)

CONFIRM_PHRASE = "DELETE_TEST_PERF_DATA"


@dataclass
class CleanupSummary:
    deleted: dict[str, int] = field(default_factory=dict)

    def print_report(self) -> None:
        for table_name, count in self.deleted.items():
            print(f"deleted {table_name}: {count}")


def cleanup_performance_data(db: Session, confirm: str | None) -> CleanupSummary:
    if confirm != CONFIRM_PHRASE:
        raise RuntimeError(
            f"Refusing to delete test performance data: pass confirm={CONFIRM_PHRASE!r} "
            f"(CLI: --confirm {CONFIRM_PHRASE})."
        )

    card_ids = [
        row[0]
        for row in db.query(Card.id).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).all()
    ]
    user_ids = [
        row[0] for row in db.query(User.id).filter(User.google_sub == TEST_USER_GOOGLE_SUB).all()
    ]

    summary = CleanupSummary()

    if card_ids:
        summary.deleted["price_observations"] = (
            db.query(PriceObservation)
            .filter(PriceObservation.card_id.in_(card_ids))
            .delete(synchronize_session=False)
        )
        summary.deleted["source_card_mappings"] = (
            db.query(SourceCardMapping)
            .filter(SourceCardMapping.card_id.in_(card_ids))
            .delete(synchronize_session=False)
        )
        summary.deleted["collection_items"] = (
            db.query(CollectionItem)
            .filter(CollectionItem.card_id.in_(card_ids))
            .delete(synchronize_session=False)
        )
        summary.deleted["wishlist_items"] = (
            db.query(WishlistItem)
            .filter(WishlistItem.card_id.in_(card_ids))
            .delete(synchronize_session=False)
        )
    else:
        summary.deleted["price_observations"] = 0
        summary.deleted["source_card_mappings"] = 0
        summary.deleted["collection_items"] = 0
        summary.deleted["wishlist_items"] = 0

    # Defensive: a collection/wishlist item could in principle be owned by
    # the test-perf user but point at a non-TEST-PERF card (shouldn't
    # happen given what the seed script creates, but this keeps the test
    # user fully cleaned up regardless).
    if user_ids:
        summary.deleted["collection_items"] += (
            db.query(CollectionItem)
            .filter(CollectionItem.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )
        summary.deleted["wishlist_items"] += (
            db.query(WishlistItem)
            .filter(WishlistItem.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )

    summary.deleted["activity_events"] = (
        db.query(CollectorActivityEvent)
        .filter(CollectorActivityEvent.event_type == SEED_MARKER)
        .delete(synchronize_session=False)
    )
    summary.deleted["log_events"] = (
        db.query(AppLogEvent)
        .filter(AppLogEvent.event_type == SEED_MARKER)
        .delete(synchronize_session=False)
    )

    summary.deleted["cards"] = (
        db.query(Card).filter(Card.id.in_(card_ids)).delete(synchronize_session=False)
        if card_ids
        else 0
    )
    summary.deleted["test_source"] = (
        db.query(Source).filter(Source.name == TEST_SOURCE_NAME).delete(synchronize_session=False)
    )
    summary.deleted["test_user"] = (
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        if user_ids
        else 0
    )

    db.commit()
    return summary


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete synthetic TEST-PERF-* data created by app.seed_performance_data. "
        "Deletes only TEST-PERF-prefixed cards and their dependent rows, plus the dedicated "
        "test source/user and test_perf_seed-tagged activity/log events - never real data."
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default=None,
        help=f"Must be exactly {CONFIRM_PHRASE!r}.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    db = SessionLocal()
    try:
        try:
            summary = cleanup_performance_data(db, confirm=args.confirm)
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
    finally:
        db.close()

    summary.print_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
