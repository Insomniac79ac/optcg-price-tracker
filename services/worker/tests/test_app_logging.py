from worker.app_logging import log_exception, record_app_log, sanitize_context
from worker.models import AppLogEvent


def test_record_app_log_creates_row(db_session):
    record_app_log(
        "info",
        "worker",
        "price_refresh",
        "Price refresh run 1 started.",
        related_run_id=1,
        related_entity_type="price_refresh_run",
        related_entity_id=1,
    )

    row = db_session.query(AppLogEvent).one()
    assert row.level == "info"
    assert row.service == "worker"
    assert row.event_type == "price_refresh"
    assert row.related_run_id == 1


def test_sanitize_context_redacts_secret_like_keys():
    sanitized = sanitize_context({"telegram_bot_token": "leak-me", "count": 3})
    assert sanitized["telegram_bot_token"] == "[REDACTED]"
    assert sanitized["count"] == 3


def test_log_exception_stores_traceback(db_session):
    try:
        raise ValueError("scraping boom")
    except ValueError as exc:
        log_exception("worker", "scraping", "Failed to fetch mapping.", exc)

    row = db_session.query(AppLogEvent).one()
    assert row.level == "error"
    assert "ValueError: scraping boom" in row.traceback


def test_record_app_log_db_failure_does_not_raise(monkeypatch):
    import worker.app_logging as app_logging_module

    class BrokenSessionLocal:
        def __call__(self):
            raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(app_logging_module, "SessionLocal", BrokenSessionLocal())

    record_app_log("error", "worker", "price_refresh", "should not crash caller")
