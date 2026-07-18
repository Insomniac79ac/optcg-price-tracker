import sys

import pytest

from worker.job_locks import LockHeldError, acquire_lock
from worker.jobs.run_market_workflow import build_arg_parser, main, run_market_workflow
from worker.models import (
    Card,
    MarketWorkflowRun,
    PriceObservation,
    PriceRefreshRun,
    Source,
    SourceCardMapping,
)
from worker.settings import settings


def seed_yuyutei_mapping(db_session) -> tuple[Source, Card, SourceCardMapping]:
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    card = Card(
        card_code="OP01-001", name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(source)
    db_session.add(card)
    db_session.flush()

    mapping = SourceCardMapping(
        card_id=card.id, source_id=source.id, source_card_id="OP01-001",
        source_url="https://yuyu-tei.jp/sell/opc/card/op01/10001",
    )
    db_session.add(mapping)
    db_session.commit()
    return source, card, mapping


def test_workflow_creates_market_workflow_run_row(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    result = run_market_workflow(db_session, source="yuyutei", limit=5)

    assert result.status == "success"
    assert result.market_workflow_run_id is not None
    assert result.price_refresh_run_id is not None
    assert result.portfolio_snapshot_id is not None
    assert result.market_report_id is not None
    assert result.warnings == []

    run = db_session.query(MarketWorkflowRun).filter_by(id=result.market_workflow_run_id).one()
    assert run.status == "success"
    assert run.source == "yuyutei"
    assert run.limit == 5
    assert run.price_refresh_run_id == result.price_refresh_run_id
    assert run.portfolio_snapshot_id == result.portfolio_snapshot_id
    assert run.market_report_id == result.market_report_id
    assert run.finished_at is not None
    assert run.warnings_json == []


def test_workflow_marks_partial_success_when_report_generation_fails(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    def failing_generate_market_report(db, report_date=None):
        raise RuntimeError("report formula exploded")

    monkeypatch.setattr(
        "worker.jobs.refresh_prices.generate_market_report", failing_generate_market_report
    )

    result = run_market_workflow(db_session, source="yuyutei", limit=5)

    assert result.status == "partial_success"
    assert result.market_report_id is None
    assert any("report was not generated" in w for w in result.warnings)
    # The refresh itself, and the portfolio snapshot, still succeeded.
    assert result.price_refresh_run_id is not None
    assert result.portfolio_snapshot_id is not None

    run = db_session.query(MarketWorkflowRun).filter_by(id=result.market_workflow_run_id).one()
    assert run.status == "partial_success"


def test_workflow_marks_failed_when_price_refresh_fails(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    real_query = db_session.query

    def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    # Our own MarketWorkflowRun row creation uses add/commit, not query, so
    # breaking .query() only affects refresh_prices()'s internal mapping
    # lookup - mirrors
    # test_refresh_prices.py::test_crash_before_loop_marks_run_failed.
    monkeypatch.setattr(db_session, "query", boom)

    result = run_market_workflow(db_session, source="yuyutei", limit=5)

    assert result.status == "failed"
    assert any("Price refresh failed" in w for w in result.warnings)

    monkeypatch.setattr(db_session, "query", real_query)
    run = db_session.query(MarketWorkflowRun).filter_by(id=result.market_workflow_run_id).one()
    assert run.status == "failed"


def test_workflow_marks_failed_when_refresh_prices_crashes(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")

    def crash(*args, **kwargs):
        raise RuntimeError("totally unexpected crash")

    monkeypatch.setattr("worker.jobs.run_market_workflow.refresh_prices", crash)

    result = run_market_workflow(db_session, source="yuyutei", limit=5)

    assert result.status == "failed"
    assert result.error_message == "totally unexpected crash"
    assert result.price_refresh_run_id is None

    run = db_session.query(MarketWorkflowRun).filter_by(id=result.market_workflow_run_id).one()
    assert run.status == "failed"
    assert run.error_message == "totally unexpected crash"


def test_dry_run_skips_snapshot_report_and_digest(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    digest_calls = []
    monkeypatch.setattr(
        "worker.jobs.run_market_workflow.send_market_report_digest",
        lambda db: digest_calls.append(db),
    )

    result = run_market_workflow(
        db_session, source="yuyutei", limit=5, send_telegram=True, dry_run=True
    )

    assert result.status == "success"
    assert result.portfolio_snapshot_id is None
    assert result.market_report_id is None
    assert result.telegram_digest_status is None
    assert digest_calls == []
    assert db_session.query(PriceObservation).count() == 0

    run = db_session.query(PriceRefreshRun).filter_by(id=result.price_refresh_run_id).one()
    assert run.dry_run is True


def test_workflow_sends_telegram_digest_when_requested(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    sent_messages = []
    monkeypatch.setattr(
        "worker.market_report_digest.send_telegram_message",
        lambda text: sent_messages.append(text),
    )
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")

    result = run_market_workflow(db_session, source="yuyutei", limit=5, send_telegram=True)

    assert result.status == "success"
    assert result.telegram_digest_status == "sent"
    assert len(sent_messages) == 1


def test_workflow_defaults_limit_when_not_provided(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)

    result = run_market_workflow(db_session, source="yuyutei")

    run = db_session.query(MarketWorkflowRun).filter_by(id=result.market_workflow_run_id).one()
    assert run.limit == 10


def test_cli_runs_workflow(db_session, monkeypatch, capsys):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)
    monkeypatch.setattr(
        "worker.jobs.run_market_workflow.SessionLocal", lambda: db_session
    )
    monkeypatch.setattr(
        sys, "argv", ["run_market_workflow", "--source", "yuyutei", "--limit", "5"]
    )

    main()

    captured = capsys.readouterr()
    assert "status=success" in captured.out
    assert "market_workflow_run_id=" in captured.out


def test_arg_parser_accepts_flags():
    parser = build_arg_parser()
    args = parser.parse_args(
        ["--source", "all", "--limit", "20", "--send-telegram", "--dry-run"]
    )
    assert args.source == "all"
    assert args.limit == 20
    assert args.send_telegram is True
    assert args.dry_run is True


def test_arg_parser_rejects_invalid_source():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--source", "ebay"])


# --- locking -------------------------------------------------------------


def test_run_market_workflow_raises_lock_held_error_when_locked(db_session):
    acquire_lock(db_session, "market_workflow", "market_workflow:other", 3600)

    with pytest.raises(LockHeldError):
        run_market_workflow(db_session, source="yuyutei")

    assert db_session.query(MarketWorkflowRun).count() == 0


def test_run_market_workflow_skip_lock_bypasses_lock(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    seed_yuyutei_mapping(db_session)
    acquire_lock(db_session, "market_workflow", "market_workflow:other", 3600)

    result = run_market_workflow(db_session, source="yuyutei", skip_lock=True)

    assert result.market_workflow_run_id is not None


def test_cli_exits_2_when_lock_held(db_session, monkeypatch, capsys):
    acquire_lock(db_session, "market_workflow", "market_workflow:other", 3600)
    monkeypatch.setattr(
        "worker.jobs.run_market_workflow.SessionLocal", lambda: db_session
    )
    monkeypatch.setattr(sys, "argv", ["run_market_workflow"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert "Job already running: market_workflow" in out
