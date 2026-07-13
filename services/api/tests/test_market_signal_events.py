import itertools
from datetime import datetime, timezone

from app.models import (
    Card,
    CollectionItem,
    MarketSignalEvent,
    PriceObservation,
    Source,
    SourceCardMapping,
)
from app.services.market_signal_events import snapshot_market_signals

_dedupe_counter = itertools.count()


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


def make_item(db_session, card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


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


def make_event(db_session, **overrides) -> MarketSignalEvent:
    now = datetime.now(timezone.utc)
    fields = dict(
        signal_type="owned_above_target_sell",
        dedupe_key=f"test-dedupe-{next(_dedupe_counter)}",
        severity="info",
        suggested_action="review_sell_opportunity",
        status="open",
        message="test message",
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
    )
    fields.update(overrides)
    event = MarketSignalEvent(**fields)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


# --- snapshot_market_signals() -----------------------------------------------


def test_snapshot_creates_events(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, target_sell_price_jpy=1000)
    add_observation(
        db_session, card, snkrdunk, price_type="floor", price_jpy=1200,
        observed_at=datetime.now(timezone.utc),
    )

    result = snapshot_market_signals(db_session)

    assert result.created == 1
    assert result.updated == 0
    assert result.resolved == 0
    assert result.total_active == 1

    event = db_session.query(MarketSignalEvent).one()
    assert event.signal_type == "owned_above_target_sell"
    assert event.status == "open"
    assert event.seen_count == 1
    assert event.first_seen_at is not None
    assert event.last_seen_at is not None
    assert event.last_payload_json is not None


def test_snapshot_does_not_crash_when_card_has_multiple_missing_sources(db_session):
    """Regression test: a card with active mappings on more than one source,
    all missing price data, previously produced two missing_recent_price
    signals sharing the same card-level dedupe_key, crashing the snapshot
    with a unique-constraint violation on insert."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    make_mapping(db_session, card, yuyutei)
    make_mapping(db_session, card, snkrdunk)

    result = snapshot_market_signals(db_session)

    assert result.created == 1
    events = db_session.query(MarketSignalEvent).filter_by(
        signal_type="missing_recent_price"
    ).all()
    assert len(events) == 1
    assert "yuyutei" in events[0].message
    assert "snkrdunk" in events[0].message


def test_snapshot_updates_existing_events_and_increments_seen_count(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, target_sell_price_jpy=1000)
    add_observation(
        db_session, card, snkrdunk, price_type="floor", price_jpy=1200,
        observed_at=datetime.now(timezone.utc),
    )

    first = snapshot_market_signals(db_session)
    second = snapshot_market_signals(db_session)

    assert first.created == 1
    assert second.created == 0
    assert second.updated == 1

    event = db_session.query(MarketSignalEvent).one()
    assert event.seen_count == 2


def test_disappeared_open_event_becomes_resolved(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, target_sell_price_jpy=1000)
    add_observation(
        db_session, card, snkrdunk, price_type="floor", price_jpy=1200,
        observed_at=datetime.now(timezone.utc),
    )

    snapshot_market_signals(db_session)

    # Same collection_item_id, condition no longer qualifies.
    item.target_sell_price_jpy = None
    db_session.commit()

    result = snapshot_market_signals(db_session)

    assert result.resolved == 1
    event = db_session.query(MarketSignalEvent).one()
    assert event.status == "resolved"
    assert event.resolved_at is not None


def test_dismissed_event_remains_dismissed_if_signal_reappears(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    make_item(db_session, card, target_sell_price_jpy=1000)
    add_observation(
        db_session, card, snkrdunk, price_type="floor", price_jpy=1200,
        observed_at=datetime.now(timezone.utc),
    )

    snapshot_market_signals(db_session)
    event = db_session.query(MarketSignalEvent).one()
    event.status = "dismissed"
    event.dismissed_at = datetime.now(timezone.utc)
    db_session.commit()

    result = snapshot_market_signals(db_session)

    assert result.created == 0
    db_session.refresh(event)
    assert event.status == "dismissed"
    assert event.seen_count == 2


def test_resolved_event_reopens_if_signal_reappears(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    item = make_item(db_session, card, target_sell_price_jpy=1000)
    add_observation(
        db_session, card, snkrdunk, price_type="floor", price_jpy=1200,
        observed_at=datetime.now(timezone.utc),
    )

    snapshot_market_signals(db_session)

    item.target_sell_price_jpy = None
    db_session.commit()
    snapshot_market_signals(db_session)

    event = db_session.query(MarketSignalEvent).one()
    assert event.status == "resolved"

    item.target_sell_price_jpy = 1000
    db_session.commit()

    result = snapshot_market_signals(db_session)

    assert result.created == 0
    assert result.updated == 1
    db_session.refresh(event)
    assert event.status == "open"
    assert event.resolved_at is None


# --- GET /market/signal-events ------------------------------------------------


def test_list_filters_by_status(client, db_session):
    make_event(db_session, status="open")
    make_event(db_session, status="dismissed")

    response = client.get("/market/signal-events", params={"status": "open"})
    assert response.status_code == 200
    body = response.json()

    assert len(body["events"]) == 1
    assert body["events"][0]["status"] == "open"
    assert body["summary"]["total_events"] == 1


def test_list_filters_by_signal_type(client, db_session):
    make_event(db_session, signal_type="owned_above_target_sell")
    make_event(db_session, signal_type="stale_mapping_price")

    response = client.get(
        "/market/signal-events", params={"signal_type": "stale_mapping_price"}
    )
    body = response.json()

    assert len(body["events"]) == 1
    assert body["events"][0]["signal_type"] == "stale_mapping_price"


def test_list_filters_by_suggested_action(client, db_session):
    make_event(db_session, suggested_action="review_sell_opportunity")
    make_event(db_session, suggested_action="update_prices")

    response = client.get(
        "/market/signal-events", params={"suggested_action": "update_prices"}
    )
    body = response.json()

    assert len(body["events"]) == 1
    assert body["events"][0]["suggested_action"] == "update_prices"


def test_list_includes_card_details_and_owned_quantity(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, quantity=3)
    make_event(db_session, card_id=card.id, status="open")

    response = client.get("/market/signal-events")
    body = response.json()

    assert len(body["events"]) == 1
    event_out = body["events"][0]
    assert event_out["card_id"] == card.id
    assert event_out["card_code"] == card.card_code
    assert event_out["owned_quantity"] == 3


# --- PATCH / actions -----------------------------------------------------


def test_patch_status_and_notes(client, db_session):
    event = make_event(db_session, status="open")

    response = client.patch(
        f"/market/signal-events/{event.id}",
        json={"status": "watching", "notes": "keeping an eye on this"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "watching"
    assert body["notes"] == "keeping an eye on this"


def test_dismiss_endpoint_works(client, db_session):
    event = make_event(db_session, status="open")

    response = client.post(f"/market/signal-events/{event.id}/dismiss")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dismissed"
    assert body["dismissed_at"] is not None


def test_dismiss_clears_resolved_at(client, db_session):
    """Regression: dismissing a previously-resolved event must clear
    resolved_at, or the event would show a stale resolved timestamp while
    its status says dismissed."""
    event = make_event(
        db_session, status="resolved", resolved_at=datetime.now(timezone.utc)
    )

    response = client.post(f"/market/signal-events/{event.id}/dismiss")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dismissed"
    assert body["resolved_at"] is None


def test_watch_endpoint_works(client, db_session):
    event = make_event(
        db_session, status="dismissed", dismissed_at=datetime.now(timezone.utc)
    )

    response = client.post(f"/market/signal-events/{event.id}/watch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "watching"
    assert body["dismissed_at"] is None


def test_watch_clears_resolved_at(client, db_session):
    """Regression: watching a previously-resolved event must clear
    resolved_at, or the event would show a stale resolved timestamp while
    its status says watching."""
    event = make_event(
        db_session, status="resolved", resolved_at=datetime.now(timezone.utc)
    )

    response = client.post(f"/market/signal-events/{event.id}/watch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "watching"
    assert body["resolved_at"] is None


def test_resolve_endpoint_works(client, db_session):
    event = make_event(db_session, status="open")

    response = client.post(f"/market/signal-events/{event.id}/resolve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None


def test_resolve_clears_dismissed_at(client, db_session):
    """Regression: resolving a previously-dismissed event must clear
    dismissed_at, or the event would show a stale dismissed timestamp while
    its status says resolved."""
    event = make_event(
        db_session, status="dismissed", dismissed_at=datetime.now(timezone.utc)
    )

    response = client.post(f"/market/signal-events/{event.id}/resolve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["dismissed_at"] is None
