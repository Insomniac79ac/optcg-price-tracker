from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_SCRAPING_MODES = ("mock", "live")


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

    @field_validator("SCRAPING_MODE")
    @classmethod
    def _validate_scraping_mode(cls, value: str) -> str:
        if value not in VALID_SCRAPING_MODES:
            raise ValueError(f"Invalid SCRAPING_MODE={value}. Expected mock or live.")
        return value


settings = Settings()
