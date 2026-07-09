import pytest
from pydantic import ValidationError

from worker.settings import Settings


def test_default_scraping_mode_is_mock(monkeypatch):
    monkeypatch.delenv("SCRAPING_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.SCRAPING_MODE == "mock"


def test_scraping_mode_live_is_valid(monkeypatch):
    monkeypatch.delenv("SCRAPING_MODE", raising=False)

    settings = Settings(_env_file=None, SCRAPING_MODE="live")

    assert settings.SCRAPING_MODE == "live"


def test_invalid_scraping_mode_raises_clear_error(monkeypatch):
    monkeypatch.delenv("SCRAPING_MODE", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, SCRAPING_MODE="bogus")

    assert "Invalid SCRAPING_MODE=bogus. Expected mock or live." in str(exc_info.value)


def test_scraping_mode_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("SCRAPING_MODE", "live")

    settings = Settings(_env_file=None)

    assert settings.SCRAPING_MODE == "live"


def test_yuyutei_request_delay_ms_rejects_zero():
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, YUYUTEI_REQUEST_DELAY_MS=0)

    assert "YUYUTEI_REQUEST_DELAY_MS" in str(exc_info.value)


def test_yuyutei_request_delay_ms_rejects_negative():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, YUYUTEI_REQUEST_DELAY_MS=-100)


def test_yuyutei_request_delay_ms_accepts_positive_value():
    settings = Settings(_env_file=None, YUYUTEI_REQUEST_DELAY_MS=500)

    assert settings.YUYUTEI_REQUEST_DELAY_MS == 500


def test_price_refresh_interval_hours_rejects_zero():
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, PRICE_REFRESH_INTERVAL_HOURS=0)

    assert "PRICE_REFRESH_INTERVAL_HOURS" in str(exc_info.value)


def test_price_refresh_interval_hours_rejects_negative():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, PRICE_REFRESH_INTERVAL_HOURS=-6)


def test_database_url_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="")


def test_redis_url_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REDIS_URL="")


def test_telegram_bot_token_without_chat_id_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        Settings(_env_file=None, TELEGRAM_BOT_TOKEN="abc", TELEGRAM_CHAT_ID=None)

    assert "TELEGRAM_CHAT_ID is missing" in caplog.text


def test_telegram_chat_id_without_bot_token_logs_warning(caplog):
    with caplog.at_level("WARNING"):
        Settings(_env_file=None, TELEGRAM_CHAT_ID="123", TELEGRAM_BOT_TOKEN=None)

    assert "TELEGRAM_BOT_TOKEN is missing" in caplog.text


def test_telegram_fully_configured_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        Settings(_env_file=None, TELEGRAM_BOT_TOKEN="abc", TELEGRAM_CHAT_ID="123")

    assert "Telegram" not in caplog.text


def test_telegram_fully_unset_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        Settings(_env_file=None, TELEGRAM_BOT_TOKEN=None, TELEGRAM_CHAT_ID=None)

    assert "Telegram" not in caplog.text
