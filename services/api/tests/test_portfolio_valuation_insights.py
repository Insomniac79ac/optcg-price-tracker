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
    fields = dict(card_id=card.id, quantity=1)
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


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def test_best_performer_calculated_correctly(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")

    item_a = make_item(db_session, card_a, purchase_price_jpy=1000, quantity=1)
    make_item(db_session, card_b, purchase_price_jpy=1000, quantity=1)

    add_observation(db_session, card_a, snkrdunk, price_type="floor", price_jpy=2000)
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=1200)

    response = client.get("/collection/valuation")
    body = response.json()
    best = body["summary"]["insights"]["best_performing_item"]

    assert best["collection_item_id"] == item_a.id
    assert best["card_code"] == "OP01-001"
    assert best["pnl_jpy"] == 1000
    assert best["pnl_pct"] == 100.0
    assert best["basis"] == "market_floor"


def test_worst_performer_calculated_correctly(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")

    make_item(db_session, card_a, purchase_price_jpy=1000, quantity=1)
    item_b = make_item(db_session, card_b, purchase_price_jpy=1000, quantity=1)

    add_observation(db_session, card_a, snkrdunk, price_type="floor", price_jpy=2000)
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=500)

    response = client.get("/collection/valuation")
    body = response.json()
    worst = body["summary"]["insights"]["worst_performing_item"]

    assert worst["collection_item_id"] == item_b.id
    assert worst["card_code"] == "OP01-002"
    assert worst["pnl_jpy"] == -500
    assert worst["pnl_pct"] == -50.0
    assert worst["basis"] == "market_floor"


def test_missing_cost_basis_excluded_from_best_worst(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")

    make_item(db_session, card_a, purchase_price_jpy=None, quantity=1)
    item_b = make_item(db_session, card_b, purchase_price_jpy=1000, quantity=1)

    # card_a has no cost basis and a huge floor price - if it leaked into
    # ranking it would dominate both best and worst.
    add_observation(db_session, card_a, snkrdunk, price_type="floor", price_jpy=5000)
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=1200)

    response = client.get("/collection/valuation")
    body = response.json()
    insights = body["summary"]["insights"]

    assert insights["best_performing_item"]["collection_item_id"] == item_b.id
    assert insights["worst_performing_item"]["collection_item_id"] == item_b.id


def test_missing_current_value_excluded_from_best_worst(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")

    make_item(db_session, card_a, purchase_price_jpy=1000, quantity=1)
    item_b = make_item(db_session, card_b, purchase_price_jpy=1000, quantity=1)

    # card_a has cost basis but no price observations at all, so no current
    # value can be resolved for it (neither market floor nor retail sell).
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=1500)

    response = client.get("/collection/valuation")
    body = response.json()
    insights = body["summary"]["insights"]

    assert insights["best_performing_item"]["collection_item_id"] == item_b.id
    assert insights["worst_performing_item"]["collection_item_id"] == item_b.id


def test_fallback_from_snkrdunk_floor_to_yuyutei_sell(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    yuyutei = make_source(db_session, "yuyutei")

    make_item(db_session, card, purchase_price_jpy=1000, quantity=1)
    # No SNKRDUNK floor observation at all - only Yuyu-Tei sell.
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1300)

    response = client.get("/collection/valuation")
    body = response.json()
    insights = body["summary"]["insights"]

    assert insights["best_performing_item"]["basis"] == "retail"
    assert insights["best_performing_item"]["pnl_jpy"] == 300
    assert insights["highest_value_item"]["basis"] == "retail"
    assert insights["highest_value_item"]["value_jpy"] == 1300


def test_largest_retail_liquidation_gap_calculated_correctly(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    yuyutei = make_source(db_session, "yuyutei")

    item_a = make_item(db_session, card_a, quantity=1)
    make_item(db_session, card_b, quantity=1)

    add_observation(db_session, card_a, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card_a, yuyutei, price_type="buy", price_jpy=1000)
    add_observation(db_session, card_b, yuyutei, price_type="sell", price_jpy=2000)
    add_observation(db_session, card_b, yuyutei, price_type="buy", price_jpy=1900)

    response = client.get("/collection/valuation")
    body = response.json()
    gap = body["summary"]["insights"]["largest_retail_liquidation_gap"]

    assert gap["collection_item_id"] == item_a.id
    assert gap["gap_jpy"] == 500
    assert gap["gap_pct"] == round(500 / 1500 * 100, 2)


def test_highest_value_item_calculated_correctly(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")

    item_a = make_item(db_session, card_a, quantity=1)
    make_item(db_session, card_b, quantity=1)

    add_observation(db_session, card_a, snkrdunk, price_type="floor", price_jpy=3000)
    add_observation(db_session, card_b, snkrdunk, price_type="floor", price_jpy=1000)

    response = client.get("/collection/valuation")
    body = response.json()
    highest = body["summary"]["insights"]["highest_value_item"]

    assert highest["collection_item_id"] == item_a.id
    assert highest["value_jpy"] == 3000
    assert highest["basis"] == "market_floor"


def test_insufficient_data_returns_null_insights(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    make_item(db_session, card, purchase_price_jpy=None, quantity=1)

    response = client.get("/collection/valuation")
    body = response.json()
    insights = body["summary"]["insights"]

    assert insights["best_performing_item"] is None
    assert insights["worst_performing_item"] is None
    assert insights["largest_retail_liquidation_gap"] is None
    assert insights["highest_value_item"] is None
