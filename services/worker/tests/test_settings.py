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
