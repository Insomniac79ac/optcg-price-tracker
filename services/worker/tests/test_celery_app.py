from datetime import timedelta

import worker.celery_app as celery_app_module
from worker.celery_app import app, refresh_yuyutei_prices
from worker.models import Card, PriceObservation, PriceRefreshRun, Source, SourceCardMapping
from worker.settings import Settings, settings


def test_celery_task_can_be_imported():
    assert refresh_yuyutei_prices.name == "worker.celery_app.refresh_yuyutei_prices"
    assert "worker.celery_app.refresh_yuyutei_prices" in app.tasks


def test_beat_schedule_runs_every_price_refresh_interval_hours():
    entry = app.conf.beat_schedule["refresh-yuyutei-prices"]

    assert entry["task"] == "worker.celery_app.refresh_yuyutei_prices"
    assert entry["schedule"] == timedelta(hours=settings.PRICE_REFRESH_INTERVAL_HOURS)


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
