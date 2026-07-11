from datetime import datetime, timedelta, timezone

from app.models import Card, CollectionItem, PriceObservation, Source, SourceCardMapping


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


def make_source(db_session, name: str) -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, observed_at):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_mapping(db_session, card, source, **overrides) -> SourceCardMapping:
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        source_card_id=card.card_code,
        is_active=True,
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def make_item(db_session, card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def test_detects_price_up_7d(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)

    response = client.get("/market/signals")
    assert response.status_code == 200
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "price_up_7d")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["change_pct"] == 15.0
    assert signal["suggested_action"] == "monitor_momentum"
    assert body["summary"]["by_signal_type"]["price_up_7d"] == 1


def test_detects_price_down_7d(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=850, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "price_down_7d")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["change_pct"] == -15.0
    assert signal["suggested_action"] == "monitor_drop"


def test_detects_price_up_30d(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=30))
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1250, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "price_up_30d")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["change_pct"] == 25.0


def test_detects_price_down_30d(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=30))
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=750, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "price_down_30d")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["change_pct"] == -25.0


def test_detects_yuyutei_spread_compressed(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "yuyutei_buy_sell_spread_compressed")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["spread_pct"] == 10.0
    assert signal["suggested_action"] == "review_sell_opportunity"


def test_detects_yuyutei_spread_wide(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=400, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "yuyutei_buy_sell_spread_wide")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["spread_pct"] == 60.0


def test_detects_snkrdunk_below_yuyutei_sell(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1200, observed_at=now)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "snkrdunk_floor_below_yuyutei_sell")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["gap_jpy"] == -200
    assert signal["metrics"]["gap_pct"] == -16.67
    assert signal["suggested_action"] == "review_buy_opportunity"
    assert "16.67% below" in signal["message"]


def test_detects_snkrdunk_above_yuyutei_sell(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    now = datetime.now(timezone.utc)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1200, observed_at=now)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "snkrdunk_floor_above_yuyutei_sell")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["gap_jpy"] == 200
    assert signal["metrics"]["gap_pct"] == 20.0
    assert signal["suggested_action"] == "review_sell_opportunity"


def test_detects_owned_above_target_sell(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, quantity=2, target_sell_price_jpy=1000)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1200, observed_at=datetime.now(timezone.utc))

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "owned_above_target_sell")
    assert signal["card_id"] == card.id
    assert signal["owned_quantity"] == item.quantity
    assert signal["metrics"]["gap_jpy"] == 200
    assert signal["metrics"]["gap_pct"] == 20.0
    assert signal["suggested_action"] == "review_sell_opportunity"


def test_detects_owned_below_cost_basis(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=700, observed_at=datetime.now(timezone.utc))

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "owned_below_cost_basis")
    assert signal["card_id"] == card.id
    assert signal["metrics"]["gap_jpy"] == -300
    assert signal["metrics"]["gap_pct"] == -30.0
    assert signal["severity"] == "warning"
    assert signal["suggested_action"] == "monitor_drop"


def test_detects_missing_recent_price(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_mapping(db_session, card, yuyutei)

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "missing_recent_price")
    assert signal["card_id"] == card.id
    assert signal["severity"] == "warning"
    assert signal["suggested_action"] == "review_mapping"


def test_detects_stale_mapping_price(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_mapping(db_session, card, yuyutei)
    add_observation(
        db_session, card, yuyutei, price_type="sell", price_jpy=1000,
        observed_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )

    response = client.get("/market/signals")
    body = response.json()

    signal = next(s for s in body["signals"] if s["signal_type"] == "stale_mapping_price")
    assert signal["card_id"] == card.id
    assert signal["severity"] == "warning"
    assert signal["suggested_action"] == "update_prices"


def test_filters_by_signal_type(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    now = datetime.now(timezone.utc)

    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)

    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=1200, observed_at=now)
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=1000, observed_at=now)

    response = client.get("/market/signals", params={"signal_type": "price_up_7d"})
    body = response.json()

    assert len(body["signals"]) == 1
    assert body["signals"][0]["signal_type"] == "price_up_7d"
    assert body["signals"][0]["card_id"] == card_a.id
    assert body["summary"]["total_signals"] == 1


def test_filters_by_set_code(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", set_code="OP01")
    card_b = make_card(db_session, card_code="OP02-001", set_code="OP02")
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)

    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)
    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)

    response = client.get("/market/signals", params={"set_code": "OP01"})
    body = response.json()

    assert len(body["signals"]) == 1
    assert body["signals"][0]["card_id"] == card_a.id


def test_filters_by_rarity(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-002", rarity="SR")
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)

    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)
    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)

    response = client.get("/market/signals", params={"rarity": "SR"})
    body = response.json()

    assert len(body["signals"]) == 1
    assert body["signals"][0]["card_id"] == card_b.id


def test_filters_by_owned(client, db_session):
    owned_card = make_card(db_session, card_code="OP01-001")
    unowned_card = make_card(db_session, card_code="OP01-002")
    yuyutei = make_source(db_session, "yuyutei")
    now = datetime.now(timezone.utc)

    make_item(db_session, owned_card, quantity=3)

    add_observation(db_session, owned_card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, owned_card, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)
    add_observation(db_session, unowned_card, yuyutei, price_type="sell", price_jpy=1000, observed_at=now - timedelta(days=7))
    add_observation(db_session, unowned_card, yuyutei, price_type="sell", price_jpy=1150, observed_at=now)

    response = client.get(
        "/market/signals", params={"signal_type": "price_up_7d", "owned": "true"}
    )
    body = response.json()
    assert len(body["signals"]) == 1
    assert body["signals"][0]["card_id"] == owned_card.id
    assert body["signals"][0]["owned_quantity"] == 3

    response = client.get(
        "/market/signals", params={"signal_type": "price_up_7d", "owned": "false"}
    )
    body = response.json()
    assert len(body["signals"]) == 1
    assert body["signals"][0]["card_id"] == unowned_card.id
    assert body["signals"][0]["owned_quantity"] == 0


def test_empty_data_returns_empty_signals(client, db_session):
    response = client.get("/market/signals")
    assert response.status_code == 200
    body = response.json()

    assert body["signals"] == []
    assert body["summary"]["total_signals"] == 0
    assert body["summary"]["owned_signal_count"] == 0
    assert body["summary"]["market_signal_count"] == 0
    assert body["summary"]["data_quality_signal_count"] == 0
    assert all(count == 0 for count in body["summary"]["by_signal_type"].values())
