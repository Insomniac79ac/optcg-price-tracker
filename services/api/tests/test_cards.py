from datetime import date, datetime, timezone

import pytest

from app.models import Card, PriceObservation, Source
from app.seed import DEMO_CARDS, SOURCES


@pytest.fixture()
def seeded_db(db_session):
    for data in SOURCES:
        db_session.add(Source(**data))
    for data in DEMO_CARDS:
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
    assert len(data) == len(DEMO_CARDS)
    assert {card["card_code"] for card in data} == {c["card_code"] for c in DEMO_CARDS}


def test_get_card_returns_one_card(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.get(f"/cards/{luffy.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["card_code"] == "OP01-001"
    assert body["name_en"] == "Monkey D. Luffy"


def test_get_card_returns_enrichment_fields_when_present(client, db_session):
    card = Card(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
        release_date=date(2022, 12, 2),
        artist="Some Artist",
        character="Monkey D. Luffy",
        color="red",
        card_type="leader",
        cost=None,
        power=5000,
        counter=None,
        attribute="strike",
        effect_text="[Activate: Main] Once per turn...",
        trigger_text=None,
    )
    db_session.add(card)
    db_session.commit()

    response = client.get(f"/cards/{card.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["release_date"] == "2022-12-02"
    assert body["artist"] == "Some Artist"
    assert body["character"] == "Monkey D. Luffy"
    assert body["color"] == "red"
    assert body["card_type"] == "leader"
    assert body["power"] == 5000
    assert body["attribute"] == "strike"
    assert body["effect_text"] == "[Activate: Main] Once per turn..."
    assert body["cost"] is None
    assert body["counter"] is None
    assert body["trigger_text"] is None


def test_get_card_enrichment_fields_null_when_absent(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.get(f"/cards/{luffy.id}")

    assert response.status_code == 200
    body = response.json()
    for field in (
        "release_date", "artist", "character", "color", "card_type",
        "cost", "power", "counter", "attribute", "effect_text", "trigger_text",
    ):
        assert body[field] is None


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
