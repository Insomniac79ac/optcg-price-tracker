from datetime import datetime, timezone

import pytest

from worker.adapters.base import PriceObservationData, RawSnapshotData
from worker.jobs import refresh_prices as refresh_prices_module
from worker.jobs.refresh_prices import build_arg_parser, log_run_config, refresh_prices
from worker.models import (
    Card,
    CollectionItem,
    MarketSignalEvent,
    PortfolioValuationSnapshot,
    PriceObservation,
    PriceRefreshRun,
    RawSnapshot,
    Source,
    SourceCardMapping,
)
from worker.settings import settings


class FetchError(Exception):
    pass


class StubAdapter:
    """Minimal SourceAdapter stand-in for exercising the refresh job without
    real network calls."""

    def __init__(self, source_name: str, fail_for: set[str] | None = None):
        self.source_name = source_name
        self._fail_for = fail_for or set()

    def fetch_card(self, mapping) -> RawSnapshotData:
        if mapping.source_card_id in self._fail_for:
            raise FetchError(f"boom: {mapping.source_card_id}")
        return RawSnapshotData(
            source_url=mapping.source_url or "",
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            content_hash="deadbeef",
            raw_content="<html></html>",
            parser_version="stub-v1",
        )

    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        return [
            PriceObservationData(
                price_type="sell",
                price_jpy=1000,
                observed_at=snapshot.fetched_at,
                stock_status="in_stock",
            )
        ]


def seed_source_and_card(db_session, source_name: str, card_code: str) -> tuple[Source, Card]:
    source = Source(name=source_name, base_url=f"https://{source_name}.example")
    card = Card(
        card_code=card_code, name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(source)
    db_session.add(card)
    db_session.flush()
    return source, card


def make_source_card_mapping(
    db_session, source: Source, card: Card, source_card_id: str, **overrides
) -> SourceCardMapping:
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        source_card_id=source_card_id,
        source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{source_card_id}",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.flush()
    return mapping


def test_live_mode_skips_unsupported_sources_safely(db_session):
    yuyutei_source, yuyutei_card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    snkrdunk_source, snkrdunk_card = seed_source_and_card(db_session, "snkrdunk", "OP01-002")
    make_source_card_mapping(db_session, yuyutei_source, yuyutei_card, "OP01-001")
    make_source_card_mapping(db_session, snkrdunk_source, snkrdunk_card, "OP01-002")

    # Simulates SCRAPING_MODE=live, where only yuyutei has a live adapter.
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.mappings_processed == 1
    observations = db_session.query(PriceObservation).all()
    assert len(observations) == 1
    assert observations[0].card_id == yuyutei_card.id


def test_inactive_mappings_are_skipped(db_session):
    source, active_card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    inactive_card = Card(
        card_code="OP01-002", name_en="Inactive Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(inactive_card)
    db_session.flush()
    make_source_card_mapping(db_session, source, active_card, "OP01-001")
    make_source_card_mapping(db_session, source, inactive_card, "OP01-002", is_active=False)

    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.mappings_checked == 1
    assert summary.mappings_processed == 1
    observations = db_session.query(PriceObservation).all()
    assert len(observations) == 1
    assert observations[0].card_id == active_card.id


def test_refresh_run_is_created(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters, source="yuyutei")

    assert summary.id is not None
    run = db_session.query(PriceRefreshRun).filter_by(id=summary.id).one()
    assert run.scraping_mode is not None
    assert run.source_filter == "yuyutei"
    assert run.limit_count == 10
    assert run.dry_run is False
    assert run.started_at is not None
    assert run.finished_at is not None


def test_successful_run_is_marked_completed(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.status == "completed"
    run = db_session.query(PriceRefreshRun).filter_by(id=summary.id).one()
    assert run.status == "completed"
    assert run.mappings_checked == 1
    assert run.mappings_failed == 0
    assert run.snapshots_created == 1
    assert run.observations_parsed == 1
    assert run.observations_inserted == 1


def test_failed_mapping_increments_mappings_failed_and_marks_completed_with_warnings(db_session):
    source, card_ok = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    card_fail = Card(
        card_code="OP01-002", name_en="Test Card 2", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(card_fail)
    db_session.flush()
    make_source_card_mapping(db_session, source, card_fail, "OP01-002")
    make_source_card_mapping(db_session, source, card_ok, "OP01-001")

    adapters = {"yuyutei": StubAdapter("yuyutei", fail_for={"OP01-002"})}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.mappings_failed == 1
    assert summary.mappings_processed == 1
    assert summary.status == "completed_with_warnings"

    run = db_session.query(PriceRefreshRun).filter_by(id=summary.id).one()
    assert run.status == "completed_with_warnings"
    assert run.mappings_failed == 1

    observations = db_session.query(PriceObservation).all()
    assert len(observations) == 1
    assert observations[0].card_id == card_ok.id


def test_successful_non_dry_run_creates_portfolio_snapshot(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.status == "completed"
    assert summary.portfolio_snapshot_id is not None
    snapshot = (
        db_session.query(PortfolioValuationSnapshot)
        .filter_by(id=summary.portfolio_snapshot_id)
        .one()
    )
    assert snapshot.total_items == 0
    assert f"portfolio_snapshot_id={summary.portfolio_snapshot_id}" in summary.report_lines()


def test_dry_run_does_not_create_portfolio_snapshot(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters, dry_run=True)

    assert summary.portfolio_snapshot_id is None
    assert db_session.query(PortfolioValuationSnapshot).count() == 0


def test_portfolio_snapshot_failure_does_not_crash_refresh_job(db_session, monkeypatch):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    def boom(db):
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(refresh_prices_module, "create_portfolio_valuation_snapshot", boom)

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.status == "completed"
    assert summary.mappings_processed == 1
    assert summary.portfolio_snapshot_id is None
    assert db_session.query(PortfolioValuationSnapshot).count() == 0
    # Session must still be usable afterward - a leftover failed transaction
    # would break any caller that keeps using db after refresh_prices returns.
    assert db_session.query(PriceRefreshRun).filter_by(id=summary.id).one().status == "completed"


def test_successful_non_dry_run_snapshots_market_signals(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    db_session.add(CollectionItem(card_id=card.id, quantity=1, target_sell_price_jpy=500))
    db_session.flush()
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert summary.status == "completed"
    assert summary.market_signal_events_created == 1
    assert summary.market_signal_events_updated == 0
    assert summary.market_signal_events_resolved == 0

    event = db_session.query(MarketSignalEvent).one()
    assert event.signal_type == "owned_above_target_sell"
    assert event.card_id == card.id

    assert "market_signal_events_created=1 updated=0 resolved=0" in summary.report_lines()


def test_dry_run_does_not_snapshot_market_signals(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    db_session.add(CollectionItem(card_id=card.id, quantity=1, target_sell_price_jpy=500))
    db_session.flush()
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters, dry_run=True)

    assert summary.market_signal_events_created is None
    assert summary.market_signal_events_updated is None
    assert summary.market_signal_events_resolved is None
    assert db_session.query(MarketSignalEvent).count() == 0


def test_dry_run_creates_no_database_rows(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")

    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters, dry_run=True)

    assert summary.mappings_processed == 1
    assert db_session.query(RawSnapshot).count() == 0
    assert db_session.query(PriceObservation).count() == 0


def test_dry_run_does_not_insert_but_still_records_parsed_counts(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    summary = refresh_prices(limit=10, db=db_session, adapters=adapters, dry_run=True)

    # No price_observations actually persisted...
    assert db_session.query(PriceObservation).count() == 0
    assert summary.observations_inserted == 0

    # ...but the run still records what was fetched/parsed, and is itself
    # persisted (dry runs are worth auditing too).
    assert summary.mappings_checked == 1
    assert summary.snapshots_created == 1
    assert summary.observations_parsed == 1
    assert summary.status == "completed"

    run = db_session.query(PriceRefreshRun).filter_by(id=summary.id).one()
    assert run.dry_run is True
    assert run.mappings_checked == 1
    assert run.snapshots_created == 1
    assert run.observations_parsed == 1
    assert run.observations_inserted == 0


def test_crash_before_loop_marks_run_failed(db_session, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    # Break db.query on this session instance only, simulating an unexpected
    # crash right after the run row is created but before any mapping is
    # processed - a genuine "whole job crashes" scenario.
    monkeypatch.setattr(db_session, "query", boom)

    summary = refresh_prices(limit=10, db=db_session, adapters={"yuyutei": StubAdapter("yuyutei")})

    assert summary.status == "failed"
    assert summary.error_message is not None
    assert summary.mappings_checked == 0


def test_dry_run_flag_does_not_change_scraping_mode(monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")

    parser = build_arg_parser()
    args = parser.parse_args(["--source", "yuyutei", "--limit", "3", "--dry-run"])

    assert args.dry_run is True
    assert args.source == "yuyutei"
    assert args.limit == 3
    # --dry-run must only ever set args.dry_run - it must never leak into,
    # override, or be mistaken for SCRAPING_MODE.
    assert settings.SCRAPING_MODE == "mock"


def test_verbose_and_dry_run_are_independent_boolean_flags():
    parser = build_arg_parser()

    args = parser.parse_args(["--source", "all"])
    assert args.dry_run is False
    assert args.verbose is False

    args = parser.parse_args(["--dry-run", "--verbose"])
    assert args.dry_run is True
    assert args.verbose is True


def test_source_only_accepts_known_choices():
    parser = build_arg_parser()

    for value in ("yuyutei", "snkrdunk", "all"):
        args = parser.parse_args(["--source", value])
        assert args.source == value

    with pytest.raises(SystemExit):
        parser.parse_args(["--source", "bogus"])


def test_limit_is_parsed_as_integer():
    parser = build_arg_parser()

    args = parser.parse_args(["--limit", "7"])

    assert args.limit == 7
    assert isinstance(args.limit, int)


def test_log_run_config_logs_mode_and_dry_run_separately(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")

    with caplog.at_level("INFO"):
        log_run_config(source="yuyutei", limit=3, dry_run=True)

    assert "SCRAPING_MODE=mock" in caplog.text
    assert "source_filter=yuyutei" in caplog.text
    assert "limit=3" in caplog.text
    assert "dry_run=true" in caplog.text
    assert "SCRAPING_MODE=--dry-run" not in caplog.text


def test_log_run_config_live_mode_with_dry_run(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "live")

    with caplog.at_level("INFO"):
        log_run_config(source="yuyutei", limit=3, dry_run=True)

    assert "SCRAPING_MODE=live" in caplog.text
    assert "dry_run=true" in caplog.text
    assert "SCRAPING_MODE=--dry-run" not in caplog.text


def test_log_run_config_dry_run_false_logs_lowercase_false(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")

    with caplog.at_level("INFO"):
        log_run_config(source="all", limit=10, dry_run=False)

    assert "dry_run=false" in caplog.text