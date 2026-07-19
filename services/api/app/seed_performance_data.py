"""Synthetic data seed for local performance/load testing - see 'Performance
testing' in docs/performance_testing.md.

Every row this script creates is namespaced so it can never be mistaken for
(or collide with) real data, and so app.cleanup_performance_data can remove
exactly what this script created and nothing else:
  - Cards use card_code TEST-PERF-0001.. (real card codes look like
    OP01-001 and never start with "TEST-PERF-") and set_code "TEST-PERF".
  - The price source is a dedicated Source named "test-perf-source" - the
    real yuyutei/snkrdunk sources (app.seed) are never touched.
  - The collection/wishlist owner is a dedicated User
    (google_sub "test-perf-seed-user") - no real account is touched.
  - Activity events and log events are tagged event_type="test_perf_seed".

Idempotent: re-running only tops up whatever's missing relative to the
requested counts (e.g. asking for 20 price observations per card when 20
already exist creates nothing more for that card). Never overwrites or
deletes existing rows - use app.cleanup_performance_data for that.

Usage:
  python -m app.seed_performance_data --dry-run
  python -m app.seed_performance_data
  python -m app.seed_performance_data --cards 500 --price-observations-per-card 50
  python -m app.seed_performance_data --allow-production-test-data   # only if APP_ENV=production
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.env import is_production_environment
from app.models import (
    AppLogEvent,
    Card,
    CollectionItem,
    CollectorActivityEvent,
    PriceObservation,
    Source,
    User,
    WishlistItem,
)
from app.models.app_log_event import LOG_LEVELS
from app.models.wishlist_item import WISHLIST_PRIORITIES

CARD_CODE_PREFIX = "TEST-PERF-"
TEST_SET_CODE = "TEST-PERF"
TEST_RARITY = "C"
TEST_VARIANT = "base"
TEST_LANGUAGE = "jp"

TEST_SOURCE_NAME = "test-perf-source"
TEST_SOURCE_BASE_URL = "https://example.invalid/test-perf"

TEST_USER_GOOGLE_SUB = "test-perf-seed-user"
TEST_USER_EMAIL = "test-perf-seed@example.invalid"
TEST_USER_NAME = "Test Perf Seed User"

# Marker event_type - the only thing app.cleanup_performance_data trusts to
# identify synthetic activity/log events (never a substring match on
# message text, which could coincidentally match real data).
SEED_MARKER = "test_perf_seed"

# Log events only use non-alerting levels so seeding never trips
# error-rate-shaped dashboards/alerts with fake data.
_SEED_LOG_LEVELS = tuple(level for level in LOG_LEVELS if level in ("debug", "info", "warning"))


@dataclass
class SeedSummary:
    dry_run: bool
    cards_created: int = 0
    price_observations_created: int = 0
    collection_items_created: int = 0
    wishlist_items_created: int = 0
    activity_events_created: int = 0
    log_events_created: int = 0
    test_source_created: bool = False
    test_user_created: bool = False

    def print_report(self) -> None:
        verb = "would create" if self.dry_run else "created"
        print(f"dry_run={self.dry_run}")
        print(f"cards {verb}: {self.cards_created}")
        print(f"price_observations {verb}: {self.price_observations_created}")
        print(f"collection_items {verb}: {self.collection_items_created}")
        print(f"wishlist_items {verb}: {self.wishlist_items_created}")
        print(f"activity_events {verb}: {self.activity_events_created}")
        print(f"log_events {verb}: {self.log_events_created}")
        print(f"test_source {verb}: {1 if self.test_source_created else 0}")
        print(f"test_user {verb}: {1 if self.test_user_created else 0}")


def _seed_cards(db: Session, count: int, dry_run: bool) -> tuple[dict[str, Card | None], int]:
    codes = [f"{CARD_CODE_PREFIX}{i:04d}" for i in range(1, count + 1)]
    existing = {
        c.card_code: c
        for c in db.query(Card).filter(Card.card_code.in_(codes)).all()
    }
    result: dict[str, Card | None] = dict(existing)
    created = 0
    for code in codes:
        if code in existing:
            continue
        created += 1
        if dry_run:
            result[code] = None
            continue
        card = Card(
            card_code=code,
            name_en=f"Synthetic performance test card ({code})",
            name_jp=None,
            set_code=TEST_SET_CODE,
            rarity=TEST_RARITY,
            variant=TEST_VARIANT,
            language=TEST_LANGUAGE,
        )
        db.add(card)
        db.flush()
        result[code] = card
    return result, created


def _get_or_create_source(db: Session, dry_run: bool) -> tuple[Source | None, bool]:
    existing = db.query(Source).filter_by(name=TEST_SOURCE_NAME).one_or_none()
    if existing is not None:
        return existing, False
    if dry_run:
        return None, True
    source = Source(name=TEST_SOURCE_NAME, base_url=TEST_SOURCE_BASE_URL)
    db.add(source)
    db.flush()
    return source, True


def _get_or_create_user(db: Session, dry_run: bool) -> tuple[User | None, bool]:
    existing = db.query(User).filter_by(google_sub=TEST_USER_GOOGLE_SUB).one_or_none()
    if existing is not None:
        return existing, False
    if dry_run:
        return None, True
    user = User(google_sub=TEST_USER_GOOGLE_SUB, email=TEST_USER_EMAIL, name=TEST_USER_NAME)
    db.add(user)
    db.flush()
    return user, True


def _seed_price_observations(
    db: Session,
    cards_by_code: dict[str, Card | None],
    per_card: int,
    source: Source | None,
    dry_run: bool,
) -> int:
    if per_card <= 0:
        return 0
    created = 0
    for card in cards_by_code.values():
        if card is None or source is None:
            created += per_card
            continue
        existing_count = (
            db.query(PriceObservation)
            .filter_by(card_id=card.id, source_id=source.id)
            .count()
        )
        missing = max(0, per_card - existing_count)
        if missing == 0:
            continue
        created += missing
        if dry_run:
            continue
        base_price = 500 + (card.id * 7) % 4000
        for j in range(existing_count, per_card):
            observed_at = datetime.now(timezone.utc) - timedelta(days=(per_card - j))
            db.add(
                PriceObservation(
                    card_id=card.id,
                    source_id=source.id,
                    observed_at=observed_at,
                    price_type="sell",
                    price_jpy=base_price + j * 13,
                    condition_label="NM",
                    stock_status="in_stock",
                    listing_count=j + 1,
                )
            )
    if not dry_run:
        db.flush()
    return created


def _seed_collection_items(
    db: Session, cards_by_code: dict[str, Card | None], count: int, user: User | None, dry_run: bool
) -> int:
    if count <= 0:
        return 0
    created = 0
    for i, code in enumerate(list(cards_by_code.keys())[:count]):
        card = cards_by_code[code]
        if card is None or user is None:
            created += 1
            continue
        existing = (
            db.query(CollectionItem).filter_by(user_id=user.id, card_id=card.id).one_or_none()
        )
        if existing is not None:
            continue
        created += 1
        if dry_run:
            continue
        db.add(
            CollectionItem(
                user_id=user.id,
                card_id=card.id,
                quantity=1,
                condition_label="NM",
                purchase_price_jpy=1000 + i * 10,
                purchase_source="test-perf-seed",
                status="hold",
            )
        )
    if not dry_run:
        db.flush()
    return created


def _seed_wishlist_items(
    db: Session, cards_by_code: dict[str, Card | None], count: int, user: User | None, dry_run: bool
) -> int:
    if count <= 0:
        return 0
    created = 0
    for i, code in enumerate(list(cards_by_code.keys())[:count]):
        card = cards_by_code[code]
        if card is None or user is None:
            created += 1
            continue
        existing = (
            db.query(WishlistItem).filter_by(user_id=user.id, card_id=card.id).one_or_none()
        )
        if existing is not None:
            continue
        created += 1
        if dry_run:
            continue
        db.add(
            WishlistItem(
                user_id=user.id,
                card_id=card.id,
                priority=WISHLIST_PRIORITIES[i % len(WISHLIST_PRIORITIES)],
                status="watching",
                target_buy_price_jpy=800 + i * 5,
                desired_quantity=1,
            )
        )
    if not dry_run:
        db.flush()
    return created


def _seed_activity_events(
    db: Session, count: int, cards_by_code: dict[str, Card | None], dry_run: bool
) -> int:
    if count <= 0:
        return 0
    codes = list(cards_by_code.keys())
    created = 0
    for i in range(count):
        title = f"TEST-PERF synthetic activity #{i + 1}"
        existing = (
            db.query(CollectorActivityEvent)
            .filter_by(event_type=SEED_MARKER, title=title)
            .one_or_none()
        )
        if existing is not None:
            continue
        created += 1
        if dry_run:
            continue
        card = cards_by_code.get(codes[i % len(codes)]) if codes else None
        db.add(
            CollectorActivityEvent(
                event_type=SEED_MARKER,
                event_source="collection",
                card_id=card.id if card is not None else None,
                title=title,
                message="Synthetic activity event created by app.seed_performance_data for load testing.",
            )
        )
    if not dry_run:
        db.flush()
    return created


def _seed_log_events(db: Session, count: int, dry_run: bool) -> int:
    if count <= 0:
        return 0
    created = 0
    for i in range(count):
        message = f"TEST-PERF synthetic log event #{i + 1}"
        existing = (
            db.query(AppLogEvent).filter_by(event_type=SEED_MARKER, message=message).one_or_none()
        )
        if existing is not None:
            continue
        created += 1
        if dry_run:
            continue
        db.add(
            AppLogEvent(
                level=_SEED_LOG_LEVELS[i % len(_SEED_LOG_LEVELS)],
                service="test-perf-seed",
                event_type=SEED_MARKER,
                message=message,
                context_json={"seed_index": i + 1},
            )
        )
    if not dry_run:
        db.flush()
    return created


def seed_performance_data(
    db: Session,
    *,
    cards: int = 100,
    price_observations_per_card: int = 20,
    collection_items: int = 20,
    wishlist_items: int = 20,
    activity_events: int = 50,
    log_events: int = 50,
    dry_run: bool = False,
    allow_production_test_data: bool = False,
) -> SeedSummary:
    if is_production_environment() and not allow_production_test_data:
        raise RuntimeError(
            "Refusing to seed synthetic performance test data: APP_ENV/ENVIRONMENT is "
            "'production'. Pass allow_production_test_data=True (CLI: "
            "--allow-production-test-data) to override - seeded data still stays confined "
            "to TEST-PERF-prefixed rows."
        )

    cards_by_code, cards_created = _seed_cards(db, cards, dry_run)
    source, source_created = _get_or_create_source(db, dry_run)
    user, user_created = _get_or_create_user(db, dry_run)

    price_observations_created = _seed_price_observations(
        db, cards_by_code, price_observations_per_card, source, dry_run
    )
    collection_items_created = _seed_collection_items(db, cards_by_code, collection_items, user, dry_run)
    wishlist_items_created = _seed_wishlist_items(db, cards_by_code, wishlist_items, user, dry_run)
    activity_events_created = _seed_activity_events(db, activity_events, cards_by_code, dry_run)
    log_events_created = _seed_log_events(db, log_events, dry_run)

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return SeedSummary(
        dry_run=dry_run,
        cards_created=cards_created,
        price_observations_created=price_observations_created,
        collection_items_created=collection_items_created,
        wishlist_items_created=wishlist_items_created,
        activity_events_created=activity_events_created,
        log_events_created=log_events_created,
        test_source_created=source_created,
        test_user_created=user_created,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed deterministic TEST-PERF-prefixed synthetic data for local "
        "performance/load testing (pagination, cache, pruning, search, dashboard). "
        "Never touches real data. Local/dev only unless --allow-production-test-data "
        "is passed."
    )
    parser.add_argument("--cards", type=int, default=100)
    parser.add_argument("--price-observations-per-card", type=int, default=20)
    parser.add_argument("--collection-items", type=int, default=20)
    parser.add_argument("--wishlist-items", type=int, default=20)
    parser.add_argument("--activity-events", type=int, default=50)
    parser.add_argument("--log-events", type=int, default=50)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be created without writing anything."
    )
    parser.add_argument(
        "--allow-production-test-data",
        action="store_true",
        help="Required to run when APP_ENV/ENVIRONMENT=production. Seeded data is still "
        "confined to TEST-PERF-prefixed rows.",
    )
    args = parser.parse_args(argv)

    for name in (
        "cards",
        "price_observations_per_card",
        "collection_items",
        "wishlist_items",
        "activity_events",
        "log_events",
    ):
        if getattr(args, name) < 0:
            parser.error(f"--{name.replace('_', '-')} must be >= 0")

    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    db = SessionLocal()
    try:
        try:
            summary = seed_performance_data(
                db,
                cards=args.cards,
                price_observations_per_card=args.price_observations_per_card,
                collection_items=args.collection_items,
                wishlist_items=args.wishlist_items,
                activity_events=args.activity_events,
                log_events=args.log_events,
                dry_run=args.dry_run,
                allow_production_test_data=args.allow_production_test_data,
            )
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
    finally:
        db.close()

    summary.print_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
