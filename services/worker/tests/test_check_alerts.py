from datetime import datetime, timedelta, timezone

import pytest

import worker.jobs.check_alerts as check_alerts_module
from worker.alerts.telegram import TelegramSendError
from worker.jobs.check_alerts import check_alerts
from worker.models import AlertEvent, AlertRule, Card, PriceObservation, PriceRefreshRun, Source


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
    db_session,
    card: Card,
    source: Source,
    price_type: str,
    price_jpy: int,
    observed_at: datetime,
    stock_status: str | None = None,
) -> PriceObservation:
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at,
        stock_status=stock_status,
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


@pytest.fixture(autouse=True)
def stub_telegram(monkeypatch):
    """By default, sends succeed - individual tests override as needed."""
    calls = []

    def fake_send(text, client=None):
        calls.append(text)

    monkeypatch.setattr(check_alerts_module, "send_telegram_message", fake_send)
    return calls


def test_price_up_rule_creates_alert_event(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="Generic price up 10%", rule_type="price_change_pct",
        source_name="snkrdunk", price_type="floor", threshold_pct=10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1000, now - timedelta(hours=1))
    add_observation(db_session, card, source, "floor", 1300, now)

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "price_up"
    assert events[0].status == "sent"
    assert len(stub_telegram) == 1

    stored = db_session.query(AlertEvent).one()
    assert stored.event_type == "price_up"
    assert stored.status == "sent"
    assert stored.card_id == card.id
    assert stored.source_id == source.id


def test_price_down_rule_creates_alert_event(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="SNKRDUNK floor price down 10%", rule_type="price_change_pct",
        source_name="snkrdunk", price_type="floor", threshold_pct=-10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1000, now - timedelta(hours=1))
    add_observation(db_session, card, source, "floor", 850, now)

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "price_down"
    assert events[0].status == "sent"

    stored = db_session.query(AlertEvent).one()
    assert stored.event_type == "price_down"


def test_price_change_below_threshold_creates_no_event(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="SNKRDUNK floor price down 10%", rule_type="price_change_pct",
        source_name="snkrdunk", price_type="floor", threshold_pct=-10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1000, now - timedelta(hours=1))
    add_observation(db_session, card, source, "floor", 950, now)  # only -5%

    events = check_alerts(db_session, dry_run=False)

    assert events == []
    assert db_session.query(AlertEvent).count() == 0


def test_yuyutei_buy_up_rule_creates_alert_event(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "yuyutei")
    add_rule(
        db_session, name="Yuyu-Tei buy price up 10%", rule_type="yuyutei_buy_change_pct",
        source_name="yuyutei", price_type="buy", threshold_pct=10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "buy", 500, now - timedelta(hours=1))
    add_observation(db_session, card, source, "buy", 600, now)

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "yuyutei_buy_up"
    assert events[0].status == "sent"


def test_duplicate_alert_within_24h_is_skipped(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="SNKRDUNK floor price down 10%", rule_type="price_change_pct",
        source_name="snkrdunk", price_type="floor", threshold_pct=-10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1000, now - timedelta(hours=2))
    add_observation(db_session, card, source, "floor", 850, now - timedelta(hours=1))

    first_events = check_alerts(db_session, dry_run=False)
    assert len(first_events) == 1
    assert first_events[0].status == "sent"
    assert len(stub_telegram) == 1

    # Re-running with the same latest/previous pair should be recognized as
    # the same alert (same rule/card/source/price_type) within 24h.
    second_events = check_alerts(db_session, dry_run=False)

    assert len(second_events) == 1
    assert second_events[0].status == "skipped_duplicate"
    # No additional Telegram message was sent for the duplicate.
    assert len(stub_telegram) == 1

    assert db_session.query(AlertEvent).count() == 2


def test_dry_run_creates_no_sent_telegram_messages(db_session, stub_telegram):
    source, card = seed_source_and_card(db_session, "snkrdunk")
    add_rule(
        db_session, name="SNKRDUNK floor price down 10%", rule_type="price_change_pct",
        source_name="snkrdunk", price_type="floor", threshold_pct=-10.0,
    )

    now = datetime.now(timezone.utc)
    add_observation(db_session, card, source, "floor", 1000, now - timedelta(hours=1))
    add_observation(db_session, card, source, "floor", 850, now)

    events = check_alerts(db_session, dry_run=True)

    assert len(events) == 1
    assert events[0].status == "pending"
    assert len(stub_telegram) == 0

    # Dry runs never commit alert_events rows.
    assert db_session.query(AlertEvent).count() == 0


def test_refresh_failed_rule_creates_alert_event(db_session, stub_telegram):
    add_rule(db_session, name="Refresh failed", rule_type="refresh_failed")

    run = PriceRefreshRun(
        status="failed", scraping_mode="live", source_filter="yuyutei",
        limit_count=10, dry_run=False, error_message="network exploded",
    )
    db_session.add(run)
    db_session.flush()

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].event_type == "refresh_failed"
    assert events[0].refresh_run_id == run.id
    assert events[0].status == "sent"

    stored = db_session.query(AlertEvent).one()
    assert stored.refresh_run_id == run.id
    assert "network exploded" in stored.message


def test_refresh_failed_rule_does_not_realert_same_run(db_session, stub_telegram):
    add_rule(db_session, name="Refresh failed", rule_type="refresh_failed")

    run = PriceRefreshRun(
        status="failed", scraping_mode="live", source_filter="yuyutei",
        limit_count=10, dry_run=False, error_message="boom",
    )
    db_session.add(run)
    db_session.flush()

    first_events = check_alerts(db_session, dry_run=False)
    assert len(first_events) == 1

    second_events = check_alerts(db_session, dry_run=False)
    assert second_events == []
    assert db_session.query(AlertEvent).count() == 1


def test_missing_telegram_env_vars_marks_event_failed_not_crash(db_session, monkeypatch):
    def raise_not_configured(text, client=None):
        raise TelegramSendError("Telegram bot token or chat id not configured")

    monkeypatch.setattr(check_alerts_module, "send_telegram_message", raise_not_configured)

    add_rule(db_session, name="Refresh failed", rule_type="refresh_failed")
    run = PriceRefreshRun(
        status="failed", scraping_mode="live", source_filter="yuyutei",
        limit_count=10, dry_run=False, error_message="boom",
    )
    db_session.add(run)
    db_session.flush()

    events = check_alerts(db_session, dry_run=False)

    assert len(events) == 1
    assert events[0].status == "failed"

    stored = db_session.query(AlertEvent).one()
    assert stored.status == "failed"
    assert stored.error_message is not None
