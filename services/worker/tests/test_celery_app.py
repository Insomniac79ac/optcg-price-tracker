from datetime import datetime, timedelta, timezone

from celery.schedules import crontab

import worker.celery_app as celery_app_module
from worker.celery_app import (
    _build_beat_schedule,
    app,
    prune_data_retention_task,
    refresh_yuyutei_prices,
    run_market_workflow_task,
    run_price_refresh,
)
from worker.models import (
    AppLogEvent,
    Card,
    MarketWorkflowRun,
    PriceObservation,
    PriceRefreshRun,
    RawSnapshot,
    Source,
    SourceCardMapping,
)
from worker.settings import Settings, settings


def test_celery_task_can_be_imported():
    assert refresh_yuyutei_prices.name == "worker.celery_app.refresh_yuyutei_prices"
    assert "worker.celery_app.refresh_yuyutei_prices" in app.tasks


def test_beat_schedule_runs_every_price_refresh_interval_hours():
    enabled = Settings(_env_file=None, LEGACY_PRICE_REFRESH_ENABLED=True, PRICE_REFRESH_INTERVAL_HOURS=6)

    entry = _build_beat_schedule(enabled)["refresh-yuyutei-prices"]

    assert entry["task"] == "worker.celery_app.refresh_yuyutei_prices"
    assert entry["schedule"] == timedelta(hours=6)


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


def test_task_calls_refresh_logic_and_records_price_refresh_run(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    _source, card, _mapping = seed_yuyutei_mapping(db_session)
    # Captured before the call: the task's internal db.close() (same session
    # object, since SessionLocal is monkeypatched to return it) detaches
    # already-loaded ORM objects like `card`, so read what we need now.
    card_id = card.id

    # Calling a Celery task directly (not .delay()/.apply_async()) runs it
    # synchronously in-process - no broker connection needed for this.
    result = refresh_yuyutei_prices(limit=5)

    assert result["status"] == "completed"
    assert result["source_filter"] == "yuyutei"

    run = db_session.query(PriceRefreshRun).filter_by(id=result["id"]).one()
    assert run.source_filter == "yuyutei"
    assert run.scraping_mode == "mock"

    observations = db_session.query(PriceObservation).filter_by(card_id=card_id).all()
    assert len(observations) == 2  # sell + buy, from the mock yuyutei fixture


def test_task_does_not_force_live_mode(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    seed_yuyutei_mapping(db_session)

    refresh_yuyutei_prices(limit=5)

    # The task must never set/override SCRAPING_MODE itself - it only reads it.
    assert settings.SCRAPING_MODE == "mock"


def test_mock_mode_remains_default():
    assert Settings.model_fields["SCRAPING_MODE"].default == "mock"


def test_run_price_refresh_task_can_be_imported():
    assert run_price_refresh.name == "worker.celery_app.run_price_refresh"
    assert "worker.celery_app.run_price_refresh" in app.tasks


def test_run_price_refresh_delegates_to_same_refresh_logic(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    _source, card, _mapping = seed_yuyutei_mapping(db_session)
    card_id = card.id

    result = run_price_refresh(source="yuyutei", limit=5, dry_run=False)

    assert result["status"] == "completed"
    assert result["source_filter"] == "yuyutei"

    run = db_session.query(PriceRefreshRun).filter_by(id=result["id"]).one()
    assert run.source_filter == "yuyutei"
    assert run.dry_run is False

    observations = db_session.query(PriceObservation).filter_by(card_id=card_id).all()
    assert len(observations) == 2


def test_run_price_refresh_respects_dry_run(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    seed_yuyutei_mapping(db_session)

    result = run_price_refresh(source="yuyutei", limit=5, dry_run=True)

    assert result["dry_run"] is True
    assert result["observations_inserted"] == 0


def test_run_price_refresh_defaults_to_all_sources(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    seed_yuyutei_mapping(db_session)

    result = run_price_refresh(limit=5)

    assert result["source_filter"] == "all"


# --- run_market_workflow_task / beat schedule -------------------------------


def test_run_market_workflow_task_can_be_imported():
    assert run_market_workflow_task.name == "worker.celery_app.run_market_workflow_task"
    assert "worker.celery_app.run_market_workflow_task" in app.tasks


def test_run_market_workflow_task_delegates_to_job(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SCRAPING_MODE", "mock")
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    seed_yuyutei_mapping(db_session)

    result = run_market_workflow_task(source="yuyutei", limit=5)

    assert result["status"] == "success"
    assert result["market_workflow_run_id"] is not None

    run = db_session.query(MarketWorkflowRun).filter_by(id=result["market_workflow_run_id"]).one()
    assert run.source == "yuyutei"
    assert run.limit == 5


def test_beat_schedule_excludes_market_workflow_when_disabled():
    disabled = Settings(_env_file=None, MARKET_WORKFLOW_ENABLED=False, LEGACY_PRICE_REFRESH_ENABLED=True)

    schedule = _build_beat_schedule(disabled)

    assert "run-market-workflow" not in schedule
    assert "refresh-yuyutei-prices" in schedule


def test_beat_schedule_includes_market_workflow_when_enabled():
    enabled = Settings(
        _env_file=None,
        MARKET_WORKFLOW_ENABLED=True,
        MARKET_WORKFLOW_SOURCE="all",
        MARKET_WORKFLOW_LIMIT=25,
        MARKET_WORKFLOW_SEND_TELEGRAM=True,
        MARKET_WORKFLOW_HOUR_UTC=3,
        MARKET_WORKFLOW_MINUTE_UTC=45,
    )

    schedule = _build_beat_schedule(enabled)

    entry = schedule["run-market-workflow"]
    assert entry["task"] == "worker.celery_app.run_market_workflow_task"
    assert entry["schedule"] == crontab(hour=3, minute=45)
    assert entry["kwargs"] == {
        "source": "all",
        "limit": 25,
        "send_telegram": True,
        "dry_run": False,
    }


def test_module_level_beat_schedule_disabled_by_default():
    # MARKET_WORKFLOW_ENABLED defaults to False and no test in this session
    # sets it in the real environment, so the schedule actually built at
    # import time must not include the workflow entry.
    assert settings.MARKET_WORKFLOW_ENABLED is False
    assert "run-market-workflow" not in app.conf.beat_schedule


# --- refresh-yuyutei-prices / LEGACY_PRICE_REFRESH_ENABLED ------------------


def test_beat_schedule_excludes_legacy_refresh_when_disabled():
    disabled = Settings(_env_file=None, LEGACY_PRICE_REFRESH_ENABLED=False)

    schedule = _build_beat_schedule(disabled)

    assert "refresh-yuyutei-prices" not in schedule


def test_beat_schedule_includes_legacy_refresh_when_enabled():
    enabled = Settings(_env_file=None, LEGACY_PRICE_REFRESH_ENABLED=True, PRICE_REFRESH_INTERVAL_HOURS=6)

    schedule = _build_beat_schedule(enabled)

    entry = schedule["refresh-yuyutei-prices"]
    assert entry["task"] == "worker.celery_app.refresh_yuyutei_prices"
    assert entry["schedule"] == timedelta(hours=6)


def test_legacy_refresh_flag_does_not_affect_other_schedules():
    settings_with_others_enabled = Settings(
        _env_file=None,
        LEGACY_PRICE_REFRESH_ENABLED=False,
        MARKET_WORKFLOW_ENABLED=True,
        DATA_RETENTION_ENABLED=True,
    )

    schedule = _build_beat_schedule(settings_with_others_enabled)

    assert "refresh-yuyutei-prices" not in schedule
    assert "run-market-workflow" in schedule
    assert "prune-data-retention" in schedule


def test_module_level_beat_schedule_excludes_legacy_refresh_by_default():
    # LEGACY_PRICE_REFRESH_ENABLED defaults to False and no test in this
    # session sets it in the real environment, so the schedule actually
    # built at import time must not include the legacy refresh entry.
    assert settings.LEGACY_PRICE_REFRESH_ENABLED is False
    assert "refresh-yuyutei-prices" not in app.conf.beat_schedule


def test_importing_celery_app_performs_no_source_requests(monkeypatch):
    import importlib

    import httpx

    def _forbidden_get(self, *args, **kwargs):
        raise AssertionError("worker.celery_app import must not perform any HTTP request")

    monkeypatch.setattr(httpx.Client, "get", _forbidden_get)

    # Reload rather than just re-check the already-imported module, so this
    # test actually exercises module-level execution (imports, settings
    # validation, Celery app/schedule construction) under the patched client.
    importlib.reload(celery_app_module)


# --- prune_data_retention_task / beat schedule ------------------------------


def test_prune_data_retention_task_can_be_imported():
    assert prune_data_retention_task.name == "worker.celery_app.prune_data_retention_task"
    assert "worker.celery_app.prune_data_retention_task" in app.tasks


def test_beat_schedule_excludes_data_retention_when_disabled():
    disabled = Settings(_env_file=None, DATA_RETENTION_ENABLED=False, LEGACY_PRICE_REFRESH_ENABLED=True)

    schedule = _build_beat_schedule(disabled)

    assert "prune-data-retention" not in schedule
    assert "refresh-yuyutei-prices" in schedule


def test_beat_schedule_includes_data_retention_when_enabled():
    enabled = Settings(
        _env_file=None,
        DATA_RETENTION_ENABLED=True,
        DATA_RETENTION_HOUR_UTC=3,
        DATA_RETENTION_MINUTE_UTC=45,
    )

    schedule = _build_beat_schedule(enabled)

    entry = schedule["prune-data-retention"]
    assert entry["task"] == "worker.celery_app.prune_data_retention_task"
    assert entry["schedule"] == crontab(hour=3, minute=45)


def test_module_level_beat_schedule_excludes_data_retention_by_default():
    assert settings.DATA_RETENTION_ENABLED is False
    assert "prune-data-retention" not in app.conf.beat_schedule


def test_prune_data_retention_task_deletes_old_rows(db_session, monkeypatch):
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)

    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.commit()
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://yuyu-tei.jp/old",
            fetched_at=datetime.now(timezone.utc) - timedelta(days=100),
            http_status=200,
            content_hash="old",
            raw_content="<html></html>",
        )
    )
    db_session.commit()

    result = prune_data_retention_task()

    assert result["summary"]["total_rows_deleted"] == 1
    assert db_session.query(RawSnapshot).count() == 0


def test_prune_data_retention_task_records_app_log(db_session, monkeypatch):
    monkeypatch.setattr(celery_app_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr("worker.celery_app.SessionLocal", lambda: db_session)
    # worker.app_logging.record_app_log opens its own session by design -
    # redirect it to the same in-memory db this test uses (mirrors how
    # tests/conftest.py's autouse fixture does this for the api service).
    import worker.app_logging as app_logging_module

    monkeypatch.setattr(app_logging_module, "SessionLocal", lambda: db_session)

    prune_data_retention_task()

    logs = db_session.query(AppLogEvent).filter_by(event_type="data_retention_prune").all()
    assert len(logs) == 1
    assert logs[0].service == "worker"


def test_prune_data_retention_task_never_raises_on_failure(db_session, monkeypatch):
    def _broken_session():
        raise RuntimeError("db is down")

    monkeypatch.setattr(celery_app_module, "SessionLocal", _broken_session)

    import worker.app_logging as app_logging_module

    monkeypatch.setattr(app_logging_module, "SessionLocal", lambda: db_session)

    result = prune_data_retention_task()

    assert result["status"] == "failed"
    logs = db_session.query(AppLogEvent).filter_by(event_type="data_retention_prune_failed").all()
    assert len(logs) == 1
