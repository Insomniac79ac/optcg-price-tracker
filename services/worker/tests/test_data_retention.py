"""worker.data_retention - mirrors app.services.data_retention on the api
service (see that module's docstring for the full policy). These tests
focus on the protections most likely to break in a hand-duplicated copy:
latest-price and open/watching-signal-event protection, and the confirm
gate - the exhaustive per-table policy coverage lives in the api service's
tests/test_data_retention.py, since the logic is identical."""

from datetime import datetime, timedelta, timezone

import pytest

from worker.data_retention import PruneConfirmationRequired, prune_tables
from worker.models import Card, MarketSignalEvent, PriceObservation, RawSnapshot, Source

NOW = datetime.now(timezone.utc)


def make_card(db_session) -> Card:
    card = Card(card_code="OP01-001", name_en=None, name_jp=None, set_code="OP01", rarity="L", variant=None, language="en")
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def test_apply_without_confirm_raises(db_session):
    with pytest.raises(PruneConfirmationRequired):
        prune_tables(db_session, dry_run=False, tables=["raw_snapshots"], now=NOW)


def test_dry_run_does_not_delete(db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id, source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100), http_status=200,
            content_hash="old", raw_content="<html></html>",
        )
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["raw_snapshots"], now=NOW)

    assert result.results[0].rows_would_delete == 1
    assert db_session.query(RawSnapshot).count() == 1


def test_latest_price_observation_is_protected(db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
            observed_at=NOW - timedelta(days=500),
        )
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)

    assert result.results[0].rows_would_delete == 0


def test_open_and_watching_signal_events_are_protected(db_session):
    old = NOW - timedelta(days=500)
    db_session.add_all(
        [
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="a", status="open",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="b", status="watching",
                first_seen_at=old, last_seen_at=old,
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["market_signal_events"], now=NOW)

    assert result.results[0].rows_would_delete == 0


def test_old_dismissed_signal_events_are_pruned(db_session):
    old = NOW - timedelta(days=400)
    db_session.add(
        MarketSignalEvent(
            signal_type="price_up_7d", dedupe_key="a", status="dismissed",
            first_seen_at=old, last_seen_at=old,
        )
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["market_signal_events"], confirm="PRUNE", now=NOW
    )

    assert apply_result.results[0].rows_deleted == 1
    assert db_session.query(MarketSignalEvent).count() == 0


def test_unknown_table_is_skipped_not_pruned(db_session):
    result = prune_tables(db_session, dry_run=True, tables=["cards"], now=NOW)

    assert result.results[0].status == "skipped"
    assert result.results[0].rows_would_delete == 0
