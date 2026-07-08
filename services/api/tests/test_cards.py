from datetime import datetime, timezone

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


def test_list_cards_empty(client, db_session):
    response = client.get("/cards")
    assert response.status_code == 200
    assert response.json() == []


def test_list_cards_returns_seeded_cards(client, seeded_db):
    response = client.get("/cards")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(CARDS)
    assert {card["card_code"] for card in data} == {c["card_code"] for c in CARDS}


def test_get_card_returns_one_card(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.get(f"/cards/{luffy.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["card_code"] == "OP01-001"
    assert body["name_en"] == "Monkey D. Luffy"


def test_get_card_not_found_returns_404(client, seeded_db):
    response = client.get("/cards/999999")
    assert response.status_code == 404


def test_get_card_prices_ordered_by_observed_at(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    yuyutei = seeded_db.query(Source).filter_by(name="yuyutei").one()

    seeded_db.add_all(
        [
            PriceObservation(
                card_id=luffy.id,
                source_id=yuyutei.id,
                observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                price_type="listing",
                price_jpy=1200,
            ),
            PriceObservation(
                card_id=luffy.id,
                source_id=yuyutei.id,
                observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                price_type="listing",
                price_jpy=1000,
            ),
        ]
    )
    seeded_db.commit()

    response = client.get(f"/cards/{luffy.id}/prices")

    assert response.status_code == 200
    data = response.json()
    assert [p["price_jpy"] for p in data] == [1000, 1200]
    assert all(p["source"] == "yuyutei" for p in data)


def test_get_card_prices_not_found_returns_404(client, seeded_db):
    response = client.get("/cards/999999/prices")
    assert response.status_code == 404


def test_get_card_prices_empty_list_for_card_without_prices(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.get(f"/cards/{luffy.id}/prices")

    assert response.status_code == 200
    assert response.json() == []
