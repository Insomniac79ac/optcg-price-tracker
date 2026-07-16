from app.models import AppLogEvent
from app.services.app_logging import (
    MIN_PRUNE_OLDER_THAN_DAYS,
    PruneConfirmationRequired,
    log_exception,
    prune_app_logs,
    record_app_log,
    sanitize_context,
)


def test_record_app_log_creates_row(db_session):
    record_app_log(
        "info",
        "api",
        "startup",
        "API started.",
        context={"app_env": "development"},
        related_run_id=1,
        related_entity_type="price_refresh_run",
        related_entity_id=1,
    )

    rows = db_session.query(AppLogEvent).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.level == "info"
    assert row.service == "api"
    assert row.event_type == "startup"
    assert row.message == "API started."
    assert row.context_json == {"app_env": "development"}
    assert row.related_run_id == 1
    assert row.related_entity_type == "price_refresh_run"
    assert row.related_entity_id == 1


def test_record_app_log_defaults_unknown_level_to_info(db_session):
    record_app_log("not-a-real-level", "api", "startup", "test")

    row = db_session.query(AppLogEvent).one()
    assert row.level == "info"


def test_log_exception_stores_traceback(db_session):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        log_exception("api", "backup", "Backup export failed.", exc)

    row = db_session.query(AppLogEvent).one()
    assert row.level == "error"
    assert "ValueError: boom" in row.traceback


def test_sanitize_context_redacts_secret_like_keys():
    context = {
        "admin_token": "super-secret-value",
        "user_password": "hunter2",
        "api_key": "abc123",
        "Authorization": "Bearer xyz",
        "session_cookie": "abc",
        "safe_field": "keep-me",
        "nested": {"access_token": "should-be-redacted", "count": 5},
    }

    sanitized = sanitize_context(context)

    assert sanitized["admin_token"] == "[REDACTED]"
    assert sanitized["user_password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["session_cookie"] == "[REDACTED]"
    assert sanitized["safe_field"] == "keep-me"
    assert sanitized["nested"]["access_token"] == "[REDACTED]"
    assert sanitized["nested"]["count"] == 5


def test_record_app_log_persists_redacted_context(db_session):
    record_app_log(
        "warning",
        "api",
        "import",
        "test",
        context={"token": "leak-me", "row": 3},
    )

    row = db_session.query(AppLogEvent).one()
    assert row.context_json == {"token": "[REDACTED]", "row": 3}


def test_record_app_log_db_failure_does_not_raise(db_session, monkeypatch):
    import app.services.app_logging as app_logging_module

    class BrokenSessionLocal:
        def __call__(self):
            raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(app_logging_module, "SessionLocal", BrokenSessionLocal())

    # Must not raise, even though the underlying session factory is broken.
    record_app_log("error", "api", "startup", "should not crash caller")


def test_prune_dry_run_does_not_delete(db_session):
    import datetime as dt

    old = AppLogEvent(level="info", service="api", event_type="startup", message="old")
    db_session.add(old)
    db_session.commit()
    db_session.execute(
        AppLogEvent.__table__.update()
        .where(AppLogEvent.id == old.id)
        .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60))
    )
    db_session.commit()

    result = prune_app_logs(db_session, older_than_days=30, dry_run=True)

    assert result.dry_run is True
    assert result.would_delete == 1
    assert result.deleted == 0
    assert db_session.query(AppLogEvent).count() == 1


def test_prune_actual_deletes_older_logs(db_session):
    import datetime as dt

    old = AppLogEvent(level="info", service="api", event_type="startup", message="old")
    recent = AppLogEvent(level="info", service="api", event_type="startup", message="recent")
    db_session.add_all([old, recent])
    db_session.commit()
    db_session.execute(
        AppLogEvent.__table__.update()
        .where(AppLogEvent.id == old.id)
        .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60))
    )
    db_session.commit()

    result = prune_app_logs(db_session, older_than_days=30, dry_run=False)

    assert result.dry_run is False
    assert result.deleted == 1
    remaining = db_session.query(AppLogEvent).all()
    assert len(remaining) == 1
    assert remaining[0].message == "recent"


def test_prune_refuses_less_than_min_days_without_confirm(db_session):
    assert MIN_PRUNE_OLDER_THAN_DAYS == 7
    try:
        prune_app_logs(db_session, older_than_days=3, dry_run=True)
        assert False, "expected PruneConfirmationRequired"
    except PruneConfirmationRequired:
        pass


def test_prune_allows_less_than_min_days_with_confirm(db_session):
    result = prune_app_logs(db_session, older_than_days=3, dry_run=True, confirm="PRUNE")
    assert result.older_than_days == 3
