from datetime import datetime, timezone

from app.models import (
    Card,
    CollectionItem,
    GradingSubmission,
    PortfolioValuationSnapshot,
    PriceObservation,
    Source,
)
from app.snapshot_portfolio_valuation import snapshot_portfolio_valuation


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


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


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


def test_snapshot_creates_row_for_empty_collection(db_session):
    snapshot = snapshot_portfolio_valuation(db_session)

    assert snapshot.id is not None
    assert db_session.query(PortfolioValuationSnapshot).count() == 1
    assert snapshot.total_items == 0
    assert snapshot.total_quantity == 0
    assert snapshot.total_cost_basis_jpy == 0
    assert snapshot.retail_value_jpy == 0
    assert snapshot.liquidation_value_jpy == 0
    assert snapshot.market_floor_value_jpy == 0
    assert snapshot.pnl_vs_retail_jpy == 0
    assert snapshot.pnl_vs_liquidation_jpy == 0
    assert snapshot.pnl_vs_market_floor_jpy == 0
    assert snapshot.items_missing_yuyutei_sell == 0
    assert snapshot.items_missing_yuyutei_buy == 0
    assert snapshot.items_missing_snkrdunk_floor == 0
    assert snapshot.items_missing_cost_basis == 0
    assert snapshot.cards_above_target_sell == 0


def test_snapshot_creates_row_with_collection_data(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(
        db_session, card, quantity=2, purchase_price_jpy=1000, target_sell_price_jpy=1600
    )

    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1500)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1700)

    snapshot = snapshot_portfolio_valuation(db_session)

    assert snapshot.id is not None
    assert snapshot.total_items == 1
    assert snapshot.total_quantity == 2
    assert snapshot.total_cost_basis_jpy == 2000
    assert snapshot.retail_value_jpy == 3000
    assert snapshot.liquidation_value_jpy == 1800
    assert snapshot.market_floor_value_jpy == 3400
    assert snapshot.pnl_vs_retail_jpy == 1000
    assert snapshot.pnl_vs_liquidation_jpy == -200
    assert snapshot.pnl_vs_market_floor_jpy == 1400
    assert snapshot.cards_above_target_sell == 1
    # No grading submission exists yet, so the graded-adjusted figures fall
    # back to the SNKRDUNK floor value for the one owned item.
    assert snapshot.graded_adjusted_value_jpy == 3400
    assert snapshot.items_using_graded_value == 0
    assert snapshot.items_using_raw_fallback == 1
    assert snapshot.items_missing_graded_adjusted_value == 0

    stored = db_session.query(PortfolioValuationSnapshot).filter_by(id=snapshot.id).one()
    assert stored.total_items == 1


def test_snapshot_stores_graded_adjusted_fields(db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, purchase_price_jpy=1000)
    db_session.add(
        GradingSubmission(
            collection_item_id=item.id,
            grading_company="PSA",
            submission_status="received",
            grading_fee_jpy=3000,
            shipping_fee_jpy=1000,
            insurance_fee_jpy=0,
            other_fee_jpy=0,
            final_grade="10",
            graded_value_jpy=15000,
        )
    )
    db_session.commit()

    snapshot = snapshot_portfolio_valuation(db_session)

    # cost basis 1000 + grading cost 4000 = 5000; pnl = 15000 - 5000 = 10000.
    assert snapshot.graded_adjusted_value_jpy == 15000
    assert snapshot.pnl_vs_graded_adjusted_jpy == 10000
    assert snapshot.items_using_graded_value == 1
    assert snapshot.items_using_raw_fallback == 0
    assert snapshot.items_missing_graded_adjusted_value == 0

    stored = db_session.query(PortfolioValuationSnapshot).filter_by(id=snapshot.id).one()
    assert stored.graded_adjusted_value_jpy == 15000
