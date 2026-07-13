from datetime import datetime, timedelta, timezone

from app.models import Card, CollectionItem, PriceObservation, Source


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_source(db_session, name: str) -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, observed_at=None, **kwargs):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at or datetime.now(timezone.utc),
        **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def test_valuation_empty_collection_returns_zero_summary(client, db_session):
    response = client.get("/collection/valuation")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["summary"] == {
        "total_items": 0,
        "total_quantity": 0,
        "total_cost_basis_jpy": 0,
        "retail_value_jpy": 0,
        "liquidation_value_jpy": 0,
        "market_floor_value_jpy": 0,
        "pnl_vs_retail_jpy": 0,
        "pnl_vs_retail_pct": 0.0,
        "pnl_vs_liquidation_jpy": 0,
        "pnl_vs_liquidation_pct": 0.0,
        "pnl_vs_market_floor_jpy": 0,
        "pnl_vs_market_floor_pct": 0.0,
        "items_missing_yuyutei_sell": 0,
        "items_missing_yuyutei_buy": 0,
        "items_missing_snkrdunk_floor": 0,
        "items_missing_cost_basis": 0,
        "cards_above_target_sell": 0,
        "insights": {
            "best_performing_item": None,
            "worst_performing_item": None,
            "largest_retail_liquidation_gap": None,
            "highest_value_item": None,
        },
        "valuation_mode": "raw_market",
        "graded_adjusted_value_jpy": 0,
        "pnl_vs_graded_adjusted_jpy": 0,
        "pnl_vs_graded_adjusted_pct": 0.0,
        "items_using_graded_value": 0,
        "items_using_raw_fallback": 0,
        "items_missing_graded_adjusted_value": 0,
    }


def test_valuation_with_all_prices_available(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(
        db_session,
        card,
        quantity=1,
        purchase_price_jpy=1000,
        target_sell_price_jpy=2000,
    )

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)
    add_observation(
        db_session,
        card,
        snkrdunk,
        price_type="floor",
        price_jpy=1700,
        listing_count=3,
        condition_label="raw",
    )

    response = client.get("/collection/valuation")

    assert response.status_code == 200
    body = response.json()
    out = next(i for i in body["items"] if i["collection_item_id"] == item.id)

    assert out["cost_basis_jpy"] == 1000
    assert out["latest_prices"]["yuyutei_sell"]["price_jpy"] == 1500
    assert out["latest_prices"]["yuyutei_buy"]["price_jpy"] == 900
    assert out["latest_prices"]["snkrdunk_floor"]["price_jpy"] == 1700
    assert out["latest_prices"]["snkrdunk_floor"]["listing_count"] == 3
    assert out["latest_prices"]["snkrdunk_floor"]["condition_label"] == "raw"

    valuations = out["valuations"]
    assert valuations["retail_value_jpy"] == 1500
    assert valuations["liquidation_value_jpy"] == 900
    assert valuations["market_floor_value_jpy"] == 1700
    assert valuations["pnl_vs_retail_jpy"] == 500
    assert valuations["pnl_vs_retail_pct"] == 50.0
    assert valuations["pnl_vs_liquidation_jpy"] == -100
    assert valuations["pnl_vs_liquidation_pct"] == -10.0
    assert valuations["pnl_vs_market_floor_jpy"] == 700
    assert valuations["pnl_vs_market_floor_pct"] == 70.0

    flags = out["flags"]
    assert flags["missing_yuyutei_sell"] is False
    assert flags["missing_yuyutei_buy"] is False
    assert flags["missing_snkrdunk_floor"] is False
    assert flags["missing_cost_basis"] is False
    assert flags["above_target_sell"] is False


def test_valuation_missing_yuyutei_sell(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, purchase_price_jpy=1000)

    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["latest_prices"]["yuyutei_sell"] is None
    assert out["valuations"]["retail_value_jpy"] is None
    assert out["valuations"]["pnl_vs_retail_jpy"] is None
    assert out["valuations"]["pnl_vs_retail_pct"] is None
    assert out["flags"]["missing_yuyutei_sell"] is True
    assert body["summary"]["items_missing_yuyutei_sell"] == 1
    assert body["summary"]["retail_value_jpy"] == 0


def test_valuation_missing_yuyutei_buy(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, purchase_price_jpy=1000)

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["latest_prices"]["yuyutei_buy"] is None
    assert out["valuations"]["liquidation_value_jpy"] is None
    assert out["valuations"]["pnl_vs_liquidation_jpy"] is None
    assert out["flags"]["missing_yuyutei_buy"] is True
    assert body["summary"]["items_missing_yuyutei_buy"] == 1
    assert body["summary"]["liquidation_value_jpy"] == 0


def test_valuation_missing_snkrdunk_floor(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, purchase_price_jpy=1000)

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["latest_prices"]["snkrdunk_floor"] is None
    assert out["valuations"]["market_floor_value_jpy"] is None
    assert out["valuations"]["pnl_vs_market_floor_jpy"] is None
    assert out["flags"]["missing_snkrdunk_floor"] is True
    assert body["summary"]["items_missing_snkrdunk_floor"] == 1
    assert body["summary"]["market_floor_value_jpy"] == 0


def test_valuation_missing_purchase_price(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, purchase_price_jpy=None)

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["cost_basis_jpy"] is None
    assert out["valuations"]["retail_value_jpy"] == 1500
    assert out["valuations"]["pnl_vs_retail_jpy"] is None
    assert out["valuations"]["pnl_vs_retail_pct"] is None
    assert out["flags"]["missing_cost_basis"] is True
    assert body["summary"]["items_missing_cost_basis"] == 1
    assert body["summary"]["total_cost_basis_jpy"] == 0
    # Price is present, so it should still count toward the retail total.
    assert body["summary"]["retail_value_jpy"] == 1500


def test_valuation_quantity_multiplication(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, quantity=4, purchase_price_jpy=1000)

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["cost_basis_jpy"] == 4000
    assert out["valuations"]["retail_value_jpy"] == 6000
    assert out["valuations"]["liquidation_value_jpy"] == 3600
    assert out["valuations"]["market_floor_value_jpy"] == 6800


def test_valuation_uses_latest_price_observation(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, purchase_price_jpy=1000)

    now = datetime.now(timezone.utc)
    add_observation(
        db_session, card, yuyutei, price_type="sell", price_jpy=1200, observed_at=now - timedelta(days=5)
    )
    add_observation(
        db_session, card, yuyutei, price_type="sell", price_jpy=1500, observed_at=now
    )

    response = client.get("/collection/valuation")
    body = response.json()
    out = body["items"][0]

    assert out["valuations"]["retail_value_jpy"] == 1500


def test_valuation_target_sell_detection(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")

    above = make_item(db_session, card, target_sell_price_jpy=1000, quantity=1)
    below = make_item(db_session, card, target_sell_price_jpy=2000, quantity=1)

    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1500)

    response = client.get("/collection/valuation")
    body = response.json()

    above_out = next(i for i in body["items"] if i["collection_item_id"] == above.id)
    below_out = next(i for i in body["items"] if i["collection_item_id"] == below.id)

    assert above_out["flags"]["above_target_sell"] is True
    assert below_out["flags"]["above_target_sell"] is False
    assert body["summary"]["cards_above_target_sell"] == 1


def test_valuation_summary_aggregates_multiple_items(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    make_item(db_session, card, quantity=2, purchase_price_jpy=1000)
    make_item(db_session, card, quantity=1, purchase_price_jpy=500)

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)

    response = client.get("/collection/valuation")
    body = response.json()
    summary = body["summary"]

    assert summary["total_items"] == 2
    assert summary["total_quantity"] == 3
    assert summary["total_cost_basis_jpy"] == 2 * 1000 + 1 * 500
    assert summary["retail_value_jpy"] == 2 * 1500 + 1 * 1500
    assert summary["liquidation_value_jpy"] == 2 * 900 + 1 * 900
    assert summary["market_floor_value_jpy"] == 2 * 1700 + 1 * 1700
