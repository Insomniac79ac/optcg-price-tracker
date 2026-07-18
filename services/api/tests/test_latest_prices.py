"""app.services.latest_prices - the shared window-function-backed latest
price lookup used by portfolio_valuation.py/wishlist.py in place of each
service reducing full observation history in Python."""

from datetime import datetime, timedelta, timezone

from app.models import Card, PriceObservation, Source
from app.services.latest_prices import get_latest_price_map, get_latest_prices_for_cards


def make_card(db_session, **overrides) -> Card:
    fields = dict(card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str) -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def test_get_latest_prices_for_cards_returns_one_row_per_series(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=yuyutei.id,
                price_type="sell",
                price_jpy=1000,
                observed_at=now - timedelta(days=1),
            ),
            PriceObservation(
                card_id=card.id,
                source_id=yuyutei.id,
                price_type="sell",
                price_jpy=1200,
                observed_at=now,
            ),
            PriceObservation(
                card_id=card.id,
                source_id=yuyutei.id,
                price_type="buy",
                price_jpy=800,
                observed_at=now,
            ),
            PriceObservation(
                card_id=card.id,
                source_id=snkrdunk.id,
                price_type="floor",
                price_jpy=1100,
                observed_at=now,
            ),
        ]
    )
    db_session.commit()

    by_card = get_latest_prices_for_cards(db_session, [card.id])

    assert card.id in by_card
    series = {(o.source_id, o.price_type): o.price_jpy for o in by_card[card.id]}
    assert series == {
        (yuyutei.id, "sell"): 1200,
        (yuyutei.id, "buy"): 800,
        (snkrdunk.id, "floor"): 1100,
    }


def test_get_latest_prices_for_cards_ignores_older_observations(db_session):
    card = make_card(db_session)
    source = make_source(db_session, "yuyutei")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=999,
                observed_at=now - timedelta(days=30),
            ),
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=500,
                observed_at=now - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    by_card = get_latest_prices_for_cards(db_session, [card.id])

    prices = [o.price_jpy for o in by_card[card.id]]
    assert prices == [500]
    assert 999 not in prices


def test_get_latest_prices_for_cards_empty_input_returns_empty_dict(db_session):
    assert get_latest_prices_for_cards(db_session, []) == {}


def test_get_latest_price_map_keys_by_source_name_and_price_type(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=yuyutei.id, price_type="sell", price_jpy=1200, observed_at=now
            ),
            PriceObservation(
                card_id=card.id, source_id=snkrdunk.id, price_type="floor", price_jpy=1100, observed_at=now
            ),
        ]
    )
    db_session.commit()

    price_map = get_latest_price_map(db_session, [card.id])

    assert price_map[card.id][("yuyutei", "sell")].price_jpy == 1200
    assert price_map[card.id][("snkrdunk", "floor")].price_jpy == 1100


def test_get_latest_price_map_filters_by_source_names_and_price_types(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=yuyutei.id, price_type="sell", price_jpy=1200, observed_at=now
            ),
            PriceObservation(
                card_id=card.id, source_id=yuyutei.id, price_type="buy", price_jpy=800, observed_at=now
            ),
            PriceObservation(
                card_id=card.id, source_id=snkrdunk.id, price_type="floor", price_jpy=1100, observed_at=now
            ),
        ]
    )
    db_session.commit()

    price_map = get_latest_price_map(
        db_session, [card.id], source_names=("yuyutei",), price_types=("sell",)
    )

    assert list(price_map[card.id].keys()) == [("yuyutei", "sell")]
