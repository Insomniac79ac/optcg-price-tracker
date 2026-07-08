from datetime import datetime, timedelta, timezone

import pytest

from app.models import Card, PriceObservation, Source
from app.seed import CARDS, SOURCES


@pytest.fixture()
def seeded_db(db_session):
    for data in SOURCES:
        db_session.add(Source(**data))
    for data in CARDS:
        db_session.add(Card(**data))
    db_session.commit()
    return db_session


def add_observation(db, card, source, *, price_type, price_jpy, observed_at, **kwargs):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at,
        **kwargs,
    )
    db.add(obs)
    db.flush()
    return obs


def test_movers_empty_when_no_cards(client, db_session):
    response = client.get("/market/movers")
    assert response.status_code == 200
    assert response.json() == []


def test_movers_card_without_price_observations(client, seeded_db):
    response = client.get("/market/movers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(CARDS)

    luffy_entry = next(m for m in body if m["card_code"] == "OP01-001")
    assert luffy_entry["latest_prices"] == []
    assert luffy_entry["signals"] == {
        "change_24h_pct": None,
        "change_7d_pct": None,
        "change_30d_pct": None,
        "yuyutei_spread_jpy": None,
        "snkrdunk_floor_vs_yuyutei_buy_jpy": None,
    }


def test_movers_groups_latest_price_by_source_and_price_type(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()
    snkrdunk = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    now = datetime.now(timezone.utc)

    add_observation(
        seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1000,
        observed_at=now - timedelta(days=2),
    )
    add_observation(
        seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1200,
        observed_at=now, stock_status="in_stock",
    )
    add_observation(
        seeded_db, luffy, yuyutei, price_type="buy", price_jpy=900,
        observed_at=now, stock_status="buying",
    )
    add_observation(
        seeded_db, luffy, snkrdunk, price_type="floor", price_jpy=1100,
        observed_at=now, condition_label="raw", listing_count=3,
    )
    seeded_db.commit()

    response = client.get("/market/movers")
    assert response.status_code == 200
    entry = next(m for m in response.json() if m["card_code"] == "OP01-001")

    prices_by_key = {(p["source"], p["price_type"]): p for p in entry["latest_prices"]}
    assert len(prices_by_key) == 3
    assert prices_by_key[("yuyutei", "sell")]["price_jpy"] == 1200
    assert prices_by_key[("yuyutei", "buy")]["price_jpy"] == 900
    assert prices_by_key[("yuyutei", "buy")]["stock_status"] == "buying"
    assert prices_by_key[("snkrdunk", "floor")]["price_jpy"] == 1100
    assert prices_by_key[("snkrdunk", "floor")]["condition_label"] == "raw"
    assert prices_by_key[("snkrdunk", "floor")]["listing_count"] == 3


def test_movers_spread_calculation(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()
    snkrdunk = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    now = datetime.now(timezone.utc)

    add_observation(seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1200, observed_at=now)
    add_observation(seeded_db, luffy, yuyutei, price_type="buy", price_jpy=900, observed_at=now)
    add_observation(
        seeded_db, luffy, snkrdunk, price_type="floor", price_jpy=1100, observed_at=now
    )
    seeded_db.commit()

    response = client.get("/market/movers")
    entry = next(m for m in response.json() if m["card_code"] == "OP01-001")

    assert entry["signals"]["yuyutei_spread_jpy"] == 300
    assert entry["signals"]["snkrdunk_floor_vs_yuyutei_buy_jpy"] == 200


def test_movers_change_pct_uses_historical_observation(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()
    now = datetime.now(timezone.utc)

    add_observation(
        seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1000,
        observed_at=now - timedelta(days=2),
    )
    add_observation(
        seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1100, observed_at=now,
    )
    seeded_db.commit()

    response = client.get("/market/movers")
    entry = next(m for m in response.json() if m["card_code"] == "OP01-001")

    assert entry["signals"]["change_24h_pct"] == 10.0
    assert entry["signals"]["change_7d_pct"] is None


def test_movers_filters_by_source(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()
    snkrdunk = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    now = datetime.now(timezone.utc)

    add_observation(seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1200, observed_at=now)
    add_observation(
        seeded_db, luffy, snkrdunk, price_type="floor", price_jpy=1100, observed_at=now
    )
    seeded_db.commit()

    response = client.get("/market/movers", params={"source": "snkrdunk"})
    entry = next(m for m in response.json() if m["card_code"] == "OP01-001")

    assert len(entry["latest_prices"]) == 1
    assert entry["latest_prices"][0]["source"] == "snkrdunk"
    # Filtering the displayed prices doesn't change the underlying signals.
    assert entry["signals"]["yuyutei_spread_jpy"] is None


def test_movers_filters_by_price_type(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()
    now = datetime.now(timezone.utc)

    add_observation(seeded_db, luffy, yuyutei, price_type="sell", price_jpy=1200, observed_at=now)
    add_observation(seeded_db, luffy, yuyutei, price_type="buy", price_jpy=900, observed_at=now)
    seeded_db.commit()

    response = client.get("/market/movers", params={"price_type": "buy"})
    entry = next(m for m in response.json() if m["card_code"] == "OP01-001")

    assert len(entry["latest_prices"]) == 1
    assert entry["latest_prices"][0]["price_type"] == "buy"


def test_movers_filters_by_rarity_and_variant(client, seeded_db):
    response = client.get("/market/movers", params={"rarity": "SEC"})
    assert response.status_code == 200
    body = response.json()
    assert body
    assert all(m["rarity"] == "SEC" for m in body)

    response = client.get("/market/movers", params={"variant": "alt_art"})
    body = response.json()
    assert body
    assert all(m["variant"] == "alt_art" for m in body)


def test_movers_rejects_invalid_source(client, seeded_db):
    response = client.get("/market/movers", params={"source": "bogus"})
    assert response.status_code == 400


def test_movers_rejects_invalid_price_type(client, seeded_db):
    response = client.get("/market/movers", params={"price_type": "bogus"})
    assert response.status_code == 400


def test_movers_pagination(client, seeded_db):
    response = client.get("/market/movers", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    assert len(response.json()) == 2

    response = client.get("/market/movers", params={"limit": 100, "offset": len(CARDS) - 1})
    assert len(response.json()) == 1
