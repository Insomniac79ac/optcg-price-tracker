from app.models import Card, CollectionItem, GradingSubmission, PriceObservation, Source


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


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    from datetime import datetime, timezone

    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=kwargs.pop("observed_at", None) or datetime.now(timezone.utc),
        **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_submission(db_session, item: CollectionItem, **overrides) -> GradingSubmission:
    fields = dict(
        collection_item_id=item.id,
        grading_company="PSA",
        submission_status="planned",
    )
    fields.update(overrides)
    submission = GradingSubmission(**fields)
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


# --- raw_market mode is unaffected -----------------------------------------


def test_raw_market_mode_unchanged_by_grading(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)
    make_submission(
        db_session,
        item,
        submission_status="received",
        final_grade="10",
        graded_value_jpy=99999,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "raw_market"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valuation_mode"] == "raw_market"
    assert body["summary"]["market_floor_value_jpy"] == 1700
    assert body["summary"]["graded_adjusted_value_jpy"] == 0
    assert body["summary"]["items_using_graded_value"] == 0
    assert body["summary"]["items_using_raw_fallback"] == 0
    assert body["summary"]["items_missing_graded_adjusted_value"] == 0

    out = body["items"][0]
    assert out["valuations"]["market_floor_value_jpy"] == 1700
    assert out["graded_adjusted"] == {
        "value_jpy": None,
        "basis": None,
        "grading_submission_id": None,
        "grading_company": None,
        "final_grade": None,
        "graded_value_jpy": None,
        "raw_fallback_basis": None,
        "pnl_jpy": None,
        "pnl_pct": None,
    }

    # Default query param behaves the same as an explicit raw_market.
    default_response = client.get("/collection/valuation")
    assert default_response.json()["summary"]["valuation_mode"] == "raw_market"


# --- graded_adjusted resolution ---------------------------------------------


def test_graded_adjusted_uses_received_graded_value(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    submission = make_submission(
        db_session,
        item,
        submission_status="received",
        grading_fee_jpy=0,
        shipping_fee_jpy=0,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
        final_grade="10",
        graded_value_jpy=15000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    assert response.status_code == 200
    body = response.json()
    out = body["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 15000
    assert out["basis"] == "graded_value"
    assert out["grading_submission_id"] == submission.id
    assert out["grading_company"] == "PSA"
    assert out["final_grade"] == "10"
    assert out["graded_value_jpy"] == 15000
    assert out["raw_fallback_basis"] is None
    assert out["pnl_jpy"] == 14000
    assert out["pnl_pct"] == 1400.0

    summary = body["summary"]
    assert summary["valuation_mode"] == "graded_adjusted"
    assert summary["graded_adjusted_value_jpy"] == 15000
    assert summary["items_using_graded_value"] == 1
    assert summary["items_using_raw_fallback"] == 0
    assert summary["items_missing_graded_adjusted_value"] == 0


def test_graded_adjusted_ignores_planned_submission(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)
    make_submission(
        db_session,
        item,
        submission_status="planned",
        graded_value_jpy=15000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 1700
    assert out["basis"] == "snkrdunk_floor"
    assert out["raw_fallback_basis"] == "snkrdunk_floor"
    assert out["grading_submission_id"] is None
    assert out["graded_value_jpy"] is None


def test_graded_adjusted_ignores_cancelled_submission(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)
    make_submission(
        db_session,
        item,
        submission_status="cancelled",
        graded_value_jpy=15000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 1700
    assert out["basis"] == "snkrdunk_floor"
    assert out["raw_fallback_basis"] == "snkrdunk_floor"


def test_graded_adjusted_falls_back_to_snkrdunk_floor(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 1700
    assert out["basis"] == "snkrdunk_floor"
    assert out["raw_fallback_basis"] == "snkrdunk_floor"

    summary = response.json()["summary"]
    assert summary["items_using_raw_fallback"] == 1
    assert summary["items_using_graded_value"] == 0


def test_graded_adjusted_falls_back_to_yuyutei_sell_if_snkrdunk_missing(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 1500
    assert out["basis"] == "yuyutei_sell"
    assert out["raw_fallback_basis"] == "yuyutei_sell"


def test_graded_adjusted_missing_when_no_prices_or_grading(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, quantity=1, purchase_price_jpy=1000)

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    body = response.json()
    out = body["items"][0]["graded_adjusted"]
    assert out["value_jpy"] is None
    assert out["basis"] is None
    assert out["pnl_jpy"] is None
    assert body["summary"]["items_missing_graded_adjusted_value"] == 1


# --- P/L and cost basis ------------------------------------------------------


def test_graded_adjusted_pnl_includes_grading_cost(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=5000)
    make_submission(
        db_session,
        item,
        submission_status="received",
        grading_fee_jpy=3000,
        shipping_fee_jpy=1000,
        insurance_fee_jpy=500,
        other_fee_jpy=0,
        final_grade="10",
        graded_value_jpy=20000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    # cost basis = 5000 (purchase) + 4500 (grading cost) = 9500
    # pnl = 20000 - 9500 = 10500
    assert out["pnl_jpy"] == 10500
    assert out["pnl_pct"] == round(10500 / 9500 * 100, 2)


def test_graded_adjusted_pnl_excludes_non_received_grading_cost(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=5000)
    # An earlier, unrelated in-flight submission on the same item - its cost
    # must not bleed into the graded-adjusted P/L. Created first so the
    # later 'received' submission below is the most-recently-updated one
    # (and therefore the one whose graded value is used).
    make_submission(
        db_session,
        item,
        submission_status="submitted",
        grading_fee_jpy=99999,
    )
    make_submission(
        db_session,
        item,
        submission_status="received",
        grading_fee_jpy=3000,
        shipping_fee_jpy=0,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
        final_grade="10",
        graded_value_jpy=20000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    # cost basis = 5000 + 3000 = 8000; pnl = 20000 - 8000 = 12000
    assert out["pnl_jpy"] == 12000


def test_graded_adjusted_pnl_null_when_purchase_price_missing(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=None)
    make_submission(
        db_session,
        item,
        submission_status="received",
        grading_fee_jpy=1000,
        final_grade="10",
        graded_value_jpy=15000,
    )

    response = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})

    out = response.json()["items"][0]["graded_adjusted"]
    assert out["value_jpy"] == 15000
    assert out["pnl_jpy"] is None
    assert out["pnl_pct"] is None
