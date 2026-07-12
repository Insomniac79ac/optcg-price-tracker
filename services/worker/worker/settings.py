import logging

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

VALID_SCRAPING_MODES = ("mock", "live")
VALID_MARKET_WORKFLOW_SOURCES = ("all", "yuyutei", "snkrdunk")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"
    REDIS_URL: str = "redis://redis:6379/0"
    # Read only from the environment (SCRAPING_MODE env var / .env) - never
    # inferred from CLI args. mock is the safe default; live must be opted
    # into explicitly.
    SCRAPING_MODE: str = "mock"
    YUYUTEI_REQUEST_DELAY_MS: int = 1000
    SNKRDUNK_REQUEST_DELAY_MS: int = 1000
    SNKRDUNK_AUTO_MATCH_THRESHOLD: float = 0.92
    SNKRDUNK_SEED_FILE: str | None = None
    # How often Celery Beat schedules the automatic Yuyu-Tei price refresh.
    PRICE_REFRESH_INTERVAL_HOURS: int = 6
    # Telegram alerting - if either is unset, alert sends are logged and
    # skipped rather than attempted (see worker.alerts.telegram).
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    # Scheduled market intelligence workflow (worker.jobs.run_market_workflow) -
    # disabled by default so Celery Beat never runs it unless explicitly
    # opted into (see worker.celery_app._build_beat_schedule).
    MARKET_WORKFLOW_ENABLED: bool = False
    MARKET_WORKFLOW_SOURCE: str = "yuyutei"
    MARKET_WORKFLOW_LIMIT: int | None = None
    MARKET_WORKFLOW_SEND_TELEGRAM: bool = False
    MARKET_WORKFLOW_HOUR_UTC: int = 0
    MARKET_WORKFLOW_MINUTE_UTC: int = 0

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must not be empty.")
        return value

    @field_validator("REDIS_URL")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("REDIS_URL must not be empty.")
        return value

    @field_validator("SCRAPING_MODE")
    @classmethod
    def _validate_scraping_mode(cls, value: str) -> str:
        if value not in VALID_SCRAPING_MODES:
            raise ValueError(f"Invalid SCRAPING_MODE={value}. Expected mock or live.")
        return value

    @field_validator("YUYUTEI_REQUEST_DELAY_MS")
    @classmethod
    def _validate_yuyutei_request_delay_ms(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(
                f"Invalid YUYUTEI_REQUEST_DELAY_MS={value}. Must be a positive integer."
            )
        return value

    @field_validator("PRICE_REFRESH_INTERVAL_HOURS")
    @classmethod
    def _validate_price_refresh_interval_hours(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(
                f"Invalid PRICE_REFRESH_INTERVAL_HOURS={value}. Must be a positive integer."
            )
        return value

    @field_validator("MARKET_WORKFLOW_SOURCE")
    @classmethod
    def _validate_market_workflow_source(cls, value: str) -> str:
        if value not in VALID_MARKET_WORKFLOW_SOURCES:
            raise ValueError(
                f"Invalid MARKET_WORKFLOW_SOURCE={value}. "
                f"Expected one of {VALID_MARKET_WORKFLOW_SOURCES}."
            )
        return value

    @field_validator("MARKET_WORKFLOW_LIMIT")
    @classmethod
    def _validate_market_workflow_limit(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError(f"Invalid MARKET_WORKFLOW_LIMIT={value}. Must be a positive integer.")
        return value

    @field_validator("MARKET_WORKFLOW_HOUR_UTC")
    @classmethod
    def _validate_market_workflow_hour_utc(cls, value: int) -> int:
        if not (0 <= value <= 23):
            raise ValueError(f"Invalid MARKET_WORKFLOW_HOUR_UTC={value}. Must be 0-23.")
        return value

    @field_validator("MARKET_WORKFLOW_MINUTE_UTC")
    @classmethod
    def _validate_market_workflow_minute_utc(cls, value: int) -> int:
        if not (0 <= value <= 59):
            raise ValueError(f"Invalid MARKET_WORKFLOW_MINUTE_UTC={value}. Must be 0-59.")
        return value

    @model_validator(mode="after")
    def _warn_on_incomplete_telegram_config(self) -> "Settings":
        if self.TELEGRAM_BOT_TOKEN and not self.TELEGRAM_CHAT_ID:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is set but TELEGRAM_CHAT_ID is missing; "
                "Telegram alerts will not be sent."
            )
        if self.TELEGRAM_CHAT_ID and not self.TELEGRAM_BOT_TOKEN:
            logger.warning(
                "TELEGRAM_CHAT_ID is set but TELEGRAM_BOT_TOKEN is missing; "
                "Telegram alerts will not be sent."
            )
        return self


settings = Settings()
