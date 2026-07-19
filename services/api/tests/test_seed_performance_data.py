import pytest

from app.cleanup_performance_data import CONFIRM_PHRASE, cleanup_performance_data
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
from app.seed_performance_data import CARD_CODE_PREFIX, seed_performance_data
from app.settings import settings


@pytest.fixture(autouse=True)
def _development_environment(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "APP_ENV", None)


def _seed_real_data(db_session):
    """A pre-existing real card + collection item, used to prove cleanup
    never touches anything outside the TEST-PERF-prefixed rows it created."""
    card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp=None,
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    db_session.add(card)
    db_session.flush()
    db_session.add(
        CollectionItem(user_id=1, card_id=card.id, quantity=1, status="hold")
    )
    db_session.commit()
    return card


def test_seed_dry_run_does_not_write_anything(db_session):
    summary = seed_performance_data(
        db_session,
        cards=5,
        price_observations_per_card=2,
        collection_items=2,
        wishlist_items=2,
        activity_events=3,
        log_events=3,
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.cards_created == 5
    assert summary.price_observations_created == 5 * 2
    assert summary.collection_items_created == 2
    assert summary.wishlist_items_created == 2
    assert summary.activity_events_created == 3
    assert summary.log_events_created == 3

    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 0
    assert db_session.query(PriceObservation).count() == 0
    assert db_session.query(CollectionItem).count() == 0
    assert db_session.query(WishlistItem).count() == 0
    assert db_session.query(CollectorActivityEvent).count() == 0
    assert db_session.query(AppLogEvent).count() == 0
    assert db_session.query(Source).count() == 0
    assert db_session.query(User).filter(User.google_sub == "test-perf-seed-user").count() == 0


def test_seed_real_run_creates_expected_rows_and_is_idempotent(db_session):
    summary = seed_performance_data(
        db_session,
        cards=3,
        price_observations_per_card=2,
        collection_items=2,
        wishlist_items=2,
        activity_events=2,
        log_events=2,
        dry_run=False,
    )

    assert summary.cards_created == 3
    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 3
    assert db_session.query(PriceObservation).count() == 3 * 2
    assert db_session.query(CollectionItem).count() == 2
    assert db_session.query(WishlistItem).count() == 2
    assert db_session.query(CollectorActivityEvent).count() == 2
    assert db_session.query(AppLogEvent).count() == 2

    # Re-running with the same (or larger) counts only tops up the
    # difference - it never creates duplicate rows for what already exists.
    summary2 = seed_performance_data(
        db_session,
        cards=3,
        price_observations_per_card=2,
        collection_items=2,
        wishlist_items=2,
        activity_events=2,
        log_events=2,
        dry_run=False,
    )
    assert summary2.cards_created == 0
    assert summary2.price_observations_created == 0
    assert summary2.collection_items_created == 0
    assert summary2.wishlist_items_created == 0
    assert summary2.activity_events_created == 0
    assert summary2.log_events_created == 0
    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 3


def test_seed_refuses_production_without_allow_flag(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")

    with pytest.raises(RuntimeError, match="production"):
        seed_performance_data(db_session, cards=1, dry_run=True)

    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 0


def test_seed_allows_production_with_allow_flag(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")

    summary = seed_performance_data(
        db_session, cards=1, price_observations_per_card=0, collection_items=0,
        wishlist_items=0, activity_events=0, log_events=0,
        dry_run=False, allow_production_test_data=True,
    )

    assert summary.cards_created == 1
    card = db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).one()
    assert card.card_code.startswith(CARD_CODE_PREFIX)


def test_cleanup_requires_confirm(db_session):
    seed_performance_data(db_session, cards=2, collection_items=0, wishlist_items=0,
                           price_observations_per_card=0, activity_events=0, log_events=0,
                           dry_run=False)

    with pytest.raises(RuntimeError, match="confirm"):
        cleanup_performance_data(db_session, confirm=None)
    with pytest.raises(RuntimeError, match="confirm"):
        cleanup_performance_data(db_session, confirm="wrong")

    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 2


def test_cleanup_deletes_only_test_perf_data(db_session):
    real_card = _seed_real_data(db_session)

    seed_performance_data(
        db_session,
        cards=3,
        price_observations_per_card=2,
        collection_items=2,
        wishlist_items=2,
        activity_events=2,
        log_events=2,
        dry_run=False,
    )

    summary = cleanup_performance_data(db_session, confirm=CONFIRM_PHRASE)

    assert summary.deleted["cards"] == 3
    assert summary.deleted["price_observations"] == 6
    assert summary.deleted["collection_items"] == 2
    assert summary.deleted["wishlist_items"] == 2
    assert summary.deleted["activity_events"] == 2
    assert summary.deleted["log_events"] == 2
    assert summary.deleted["test_source"] == 1
    assert summary.deleted["test_user"] == 1

    assert db_session.query(Card).filter(Card.card_code.like(f"{CARD_CODE_PREFIX}%")).count() == 0
    assert db_session.query(Source).filter(Source.name == "test-perf-source").count() == 0
    assert db_session.query(User).filter(User.google_sub == "test-perf-seed-user").count() == 0

    # Real, pre-existing data survives untouched.
    assert db_session.query(Card).filter(Card.id == real_card.id).count() == 1
    assert db_session.query(CollectionItem).filter(CollectionItem.card_id == real_card.id).count() == 1
