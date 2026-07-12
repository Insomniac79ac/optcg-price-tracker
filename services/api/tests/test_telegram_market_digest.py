import app.services.telegram_market_digest as digest_module
from app.models import MarketReportDigestSend
from app.services.market_report import generate_market_report
from app.services.telegram_client import TelegramSendError
from app.settings import settings


def _configure_telegram(monkeypatch, token="bot-token", chat_id="12345"):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", chat_id)


def _unconfigure_telegram(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)


# --- send_market_report_digest -----------------------------------------------


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
    assert result.sent is False
    assert "not configured" in result.skipped_reason

    row = digest_module.get_digest_send(db_session, report.id)
    assert row is not None
    assert row.status == "skipped"
    assert row.sent_at is None


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
    assert row.destination == "telegram"
    assert row.sent_at is not None
    assert row.message_text == result.message_text


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
    assert second.skipped_reason == "Digest already sent for this report."
    assert len(sent_messages) == 1  # not sent again


def test_force_allows_resend(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    report = generate_market_report(db_session)

    sent_messages = []
    monkeypatch.setattr(
        digest_module, "send_telegram_message", lambda text: sent_messages.append(text)
    )

    digest_module.send_market_report_digest(db_session)
    forced = digest_module.send_market_report_digest(db_session, force=True)

    assert forced.status == "sent"
    assert len(sent_messages) == 2

    # Still exactly one row for (report_id, destination) - forced resend
    # updates the same row rather than creating a duplicate.
    rows = db_session.query(MarketReportDigestSend).filter_by(report_id=report.id).all()
    assert len(rows) == 1


def test_send_failure_records_failed_status(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    report = generate_market_report(db_session)

    def _raise(text):
        raise TelegramSendError("boom")

    monkeypatch.setattr(digest_module, "send_telegram_message", _raise)

    result = digest_module.send_market_report_digest(db_session)

    assert result.status == "failed"
    assert result.sent is False
    assert result.error_message == "boom"

    row = digest_module.get_digest_send(db_session, report.id)
    assert row.status == "failed"
    assert row.error_message == "boom"


def test_failed_send_can_be_retried_without_force(db_session, monkeypatch):
    _configure_telegram(monkeypatch)
    generate_market_report(db_session)

    def _raise(text):
        raise TelegramSendError("boom")

    monkeypatch.setattr(digest_module, "send_telegram_message", _raise)
    first = digest_module.send_market_report_digest(db_session)
    assert first.status == "failed"

    sent_messages = []
    monkeypatch.setattr(
        digest_module, "send_telegram_message", lambda text: sent_messages.append(text)
    )
    second = digest_module.send_market_report_digest(db_session)

    assert second.status == "sent"
    assert len(sent_messages) == 1


# --- format_digest_message ---------------------------------------------------


def test_format_digest_message_handles_empty_report(db_session):
    report = generate_market_report(db_session)

    message = digest_module.format_digest_message(report)

    assert "OPCG Market Report" in message
    assert "Top buy: not available" in message
    assert "Top sell: not available" in message
    assert "Top owned: not available" in message


def test_format_digest_message_truncates_when_too_long(db_session):
    report = generate_market_report(db_session)
    # Force the full message over the safe length so truncation kicks in,
    # without needing to seed a huge number of real opportunities.
    report.report_payload_json["deterministic_summary_lines"] = ["x" * 4000]

    message = digest_module.format_digest_message(report)

    assert digest_module.TRUNCATION_NOTE in message
    assert "Top opportunities:" not in message


def test_format_digest_message_fits_under_safe_length_normally(db_session):
    report = generate_market_report(db_session)

    message = digest_module.format_digest_message(report)

    assert len(message) <= digest_module.TELEGRAM_SAFE_MESSAGE_LENGTH
