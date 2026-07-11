from datetime import datetime, timedelta, timezone

import pytest

import worker.jobs.check_alerts as check_alerts_module
from worker.jobs.check_alerts import check_alerts
from worker.models import (
    AlertEvent,
    AlertRule,
    Card,
    CollectionItem,
    PortfolioValuationSnapshot,
    PriceObservation,
    Source,
)


def seed_source_and_card(db_session, source_name: str, card_code: str = "OP01-001") -> tuple[Source, Card]:
    source = Source(name=source_name, base_url=f"https://{source_name}.example")
    card = Card(
        card_code=card_code, name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(source)
    db_session.add(card)
    db_session.flush()
    return source, card


def add_observation(
    db_session, card: Card, source: Source, price_type: str, price_jpy: int, observed_at: datetime
) -> PriceObservation:
    obs = PriceObservation(
        card_id=card.id, source_id=source.id, price_type=price_type,
        price_jpy=price_jpy, observed_at=observed_at,
    )
    db_session.add(obs)
    db_session.flush()
    return obs


def add_rule(db_session, **kwargs) -> AlertRule:
    defaults = {"is_active": True}
    defaults.update(kwargs)
    rule = AlertRule(**defaults)
    db_session.add(rule)
    db_session.flush()
    return rule


def make_collection_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.flush()
    return item


def make_snapshot(db_session, **overrides) -> PortfolioValuationSnapshot:
    fields = dict(
        total_items=1,
        total_quantity=1,
        total_cost_basis_jpy=1000,
        retail_value_jpy=1000,
        liquidation_value_jpy=1000,
        market_floor_value_jpy=1000,
        pnl_vs_retail_jpy=0,
        pnl_vs_liquidation_jpy=0,
        pnl_vs_market_floor_jpy=0,
        items_missing_yuyutei_sell=0,
        items_missing_yuyutei_buy=0,
        items_missing_snkrdunk_floor=0,
        items_missing_cost_basis=0,
        cards_above_target_sell=0,
    )
    fields.update(overrides)
    snapshot = PortfolioValuationSnapshot(**fields)
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


@pytest.fixture(autouse=True)
def stub_telegram(monkeypatch):
    """By default, sends succeed - individual tests override as needed."""
    calls = []

    def fake_send(text, client=None):
        calls.append(text)

    monkeypatch.setattr(check_alerts_module, "send_telegram_message", fake_send)
    return calls


def test_target_sell_alert_fires(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(db_session, name="Owned card above target sell", rule_type="owned_card_above_target_sell")
    make_collection_item(db_session, card, target_sell_price_jpy=1000, quantity=2)

    add_observation(db_session, card, source, "floor", 1200, datetime.now(timezone.utc))

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "owned_card_above_target_sell"
    assert events[0].status == "sent"
    assert events[0].card_id == card.id

    stored = db_session.query(AlertEvent).one()
    assert "1200" in stored.message
    assert "1000" in stored.message
    assert "SNKRDUNK floor" in stored.message
    assert "qty 2" in stored.message


def test_below_cost_basis_alert_fires(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="Owned card below cost basis 15%", rule_type="owned_card_below_cost_basis",
        threshold_pct=15.0,
    )
    make_collection_item(db_session, card, purchase_price_jpy=1000, quantity=1)

    # -20% drop from purchase price, past the 15% threshold.
    add_observation(db_session, card, source, "floor", 800, datetime.now(timezone.utc))

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "owned_card_below_cost_basis"
    assert events[0].status == "sent"

    stored = db_session.query(AlertEvent).one()
    assert "800" in stored.message
    assert "1000" in stored.message
    assert "20.0%" in stored.message


def test_below_cost_basis_below_threshold_creates_no_event(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="Owned card below cost basis 15%", rule_type="owned_card_below_cost_basis",
        threshold_pct=15.0,
    )
    make_collection_item(db_session, card, purchase_price_jpy=1000, quantity=1)

    # Only a 5% drop - below the 15% threshold.
    add_observation(db_session, card, source, "floor", 950, datetime.now(timezone.utc))

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0


def test_duplicate_target_alert_skipped_within_24h(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(db_session, name="Owned card above target sell", rule_type="owned_card_above_target_sell")
    make_collection_item(db_session, card, target_sell_price_jpy=1000, quantity=1)

    add_observation(db_session, card, source, "floor", 1200, datetime.now(timezone.utc))

    first = check_alerts(db_session, dry_run=False)
    assert len(first) == 1
    assert first[0].status == "sent"
    assert len(stub_telegram) == 1

    second = check_alerts(db_session, dry_run=False)

    assert len(second) == 1
    assert second[0].status == "skipped_duplicate"
    assert len(stub_telegram) == 1
    assert db_session.query(AlertEvent).count() == 2


def test_target_alert_can_fire_again_after_dedupe_window(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    rule = add_rule(db_session, name="Owned card above target sell", rule_type="owned_card_above_target_sell")
    item = make_collection_item(db_session, card, target_sell_price_jpy=1000, quantity=1)

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1200, now)

    # A prior alert for this exact collection item, just outside the 24h
    # dedupe window.
    old_event = AlertEvent(
        event_type="owned_card_above_target_sell",
        card_id=card.id,
        title="old alert",
        message="old alert",
        dedupe_key=f"rule:{rule.id}:collection_item:{item.id}",
        status="sent",
        created_at=now - timedelta(hours=25),
    )
    db_session.add(old_event)
    db_session.flush()

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].status == "sent"
    assert db_session.query(AlertEvent).count() == 2


def test_no_alert_when_target_price_missing(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(db_session, name="Owned card above target sell", rule_type="owned_card_above_target_sell")
    make_collection_item(db_session, card, target_sell_price_jpy=None, quantity=1)

    add_observation(db_session, card, source, "floor", 5000, datetime.now(timezone.utc))

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0


def test_no_alert_when_purchase_price_missing(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="Owned card below cost basis 15%", rule_type="owned_card_below_cost_basis",
        threshold_pct=15.0,
    )
    make_collection_item(db_session, card, purchase_price_jpy=None, quantity=1)

    add_observation(db_session, card, source, "floor", 1, datetime.now(timezone.utc))

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0


def test_dry_run_logs_expected_alert_without_sending(db_session, stub_telegram, caplog):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(db_session, name="Owned card above target sell", rule_type="owned_card_above_target_sell")
    make_collection_item(db_session, card, target_sell_price_jpy=1000, quantity=1)

    add_observation(db_session, card, source, "floor", 1200, datetime.now(timezone.utc))

    with caplog.at_level("INFO"):
        events = check_alerts(db_session, dry_run=True)

    assert len(events) == 1
    assert events[0].status == "pending"
    assert len(stub_telegram) == 0
    assert db_session.query(AlertEvent).count() == 0
    assert "[dry-run] would send Telegram alert" in caplog.text


def test_portfolio_value_change_alert_fires(db_session, stub_telegram):
    add_rule(
        db_session, name="Portfolio value change 10%", rule_type="portfolio_value_change_pct",
        threshold_pct=10.0,
    )

    now = datetime.now(timezone.utc)
    make_snapshot(db_session, market_floor_value_jpy=1000, created_at=now - timedelta(hours=1))
    make_snapshot(db_session, market_floor_value_jpy=1300, created_at=now)

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "portfolio_value_up"
    assert events[0].status == "sent"

    stored = db_session.query(AlertEvent).one()
    assert "1000" in stored.message
    assert "1300" in stored.message


def test_portfolio_value_change_below_threshold_creates_no_event(db_session, stub_telegram):
    add_rule(
        db_session, name="Portfolio value change 10%", rule_type="portfolio_value_change_pct",
        threshold_pct=10.0,
    )

    now = datetime.now(timezone.utc)
    make_snapshot(db_session, market_floor_value_jpy=1000, created_at=now - timedelta(hours=1))
    make_snapshot(db_session, market_floor_value_jpy=1050, created_at=now)  # only +5%

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0


def test_portfolio_value_change_skips_with_fewer_than_two_snapshots(db_session, stub_telegram):
    add_rule(
        db_session, name="Portfolio value change 10%", rule_type="portfolio_value_change_pct",
        threshold_pct=10.0,
    )
    make_snapshot(db_session, market_floor_value_jpy=1000)

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0
