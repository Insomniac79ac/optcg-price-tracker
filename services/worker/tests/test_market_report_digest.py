import worker.market_report_digest as digest_module
from worker.market_report import generate_market_report
from worker.models import MarketReportDigestSend
from worker.settings import settings


def _configure_telegram(monkeypatch, token="bot-token", chat_id="12345"):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", chat_id)


def _unconfigure_telegram(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)


def test_no_report_returns_none(db_session):
    result = digest_module.send_market_report_digest(db_session)

    assert result is None


def test_dry_run_does_not_touch_database(db_session, monkeypatch):
    _unconfigure_telegram(monkeypatch)
    report = generate_market_report(db_session)

    result = digest_module.send_market_report_digest(db_session, dry_run=True)

    assert result.status == "pending"
    assert result.sent is False
    assert "OPCG Market Report" in result.message_text
    assert digest_module.get_digest_send(db_session, report.id) is None


def test_missing_telegram_config_returns_skipped(db_session, monkeypatch):
    _unconfigure_telegram(monkeypatch)
    report = generate_market_report(db_session)

    result = digest_module.send_market_report_digest(db_session)

    assert result.status == "skipped"
    assert "not configured" in result.skipped_reason

    row = digest_module.get_digest_send(db_session, report.id)
    assert row is not None
    assert row.status == "skipped"


def test_send_creates_row_when_configured(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    report = generate_market_report(db_session)

    sent_messages = []
    monkeypatch.setattr(
        digest_module, "send_telegram_message", lambda text: sent_messages.append(text)
    )

    result = digest_module.send_market_report_digest(db_session)

    assert result.status == "sent"
    assert result.sent is True
    assert len(sent_messages) == 1

    row = db_session.query(MarketReportDigestSend).filter_by(report_id=report.id).one()
    assert row.status == "sent"
    assert row.sent_at is not None


def test_duplicate_send_skipped_without_force(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    generate_market_report(db_session)

    sent_messages = []
    monkeypatch.setattr(
        digest_module, "send_telegram_message", lambda text: sent_messages.append(text)
    )

    first = digest_module.send_market_report_digest(db_session)
    second = digest_module.send_market_report_digest(db_session)

    assert first.status == "sent"
    assert second.status == "skipped"
    assert len(sent_messages) == 1


def test_force_allows_resend(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    generate_market_report(db_session)

    sent_messages = []
    monkeypatch.setattr(
        digest_module, "send_telegram_message", lambda text: sent_messages.append(text)
    )

    digest_module.send_market_report_digest(db_session)
    forced = digest_module.send_market_report_digest(db_session, force=True)

    assert forced.status == "sent"
    assert len(sent_messages) == 2


def test_format_digest_message_handles_empty_report(db_session):
    report = generate_market_report(db_session)

    message = digest_module.format_digest_message(report)

    assert "OPCG Market Report" in message
    assert "Top buy: not available" in message
