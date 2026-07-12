from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"
    REDIS_URL: str = "redis://redis:6379/0"
    ENVIRONMENT: str | None = None
    APP_ENV: str | None = None
    ADMIN_TOKEN: str | None = None
    # Telegram alerting - if either is unset, digest sends are logged and
    # skipped rather than attempted (see app.services.telegram_client).
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

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


settings = Settings()
