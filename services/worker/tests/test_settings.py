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


def test_market_workflow_disabled_by_default():
    settings = Settings(_env_file=None)

    assert settings.MARKET_WORKFLOW_ENABLED is False
    assert settings.MARKET_WORKFLOW_SOURCE == "yuyutei"
    assert settings.MARKET_WORKFLOW_LIMIT is None
    assert settings.MARKET_WORKFLOW_SEND_TELEGRAM is False
    assert settings.MARKET_WORKFLOW_HOUR_UTC == 0
    assert settings.MARKET_WORKFLOW_MINUTE_UTC == 0


def test_market_workflow_source_accepts_valid_values():
    for value in ("all", "yuyutei", "snkrdunk"):
        settings = Settings(_env_file=None, MARKET_WORKFLOW_SOURCE=value)
        assert settings.MARKET_WORKFLOW_SOURCE == value


def test_market_workflow_source_rejects_invalid_value():
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, MARKET_WORKFLOW_SOURCE="ebay")

    assert "Invalid MARKET_WORKFLOW_SOURCE=ebay" in str(exc_info.value)


def test_market_workflow_limit_rejects_non_positive():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_LIMIT=0)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_LIMIT=-5)


def test_market_workflow_hour_utc_rejects_out_of_range():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_HOUR_UTC=24)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_HOUR_UTC=-1)


def test_market_workflow_minute_utc_rejects_out_of_range():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_MINUTE_UTC=60)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, MARKET_WORKFLOW_MINUTE_UTC=-1)
