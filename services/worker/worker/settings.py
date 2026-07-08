from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"
    REDIS_URL: str = "redis://redis:6379/0"
    SCRAPING_MODE: str = "mock"
    YUYUTEI_REQUEST_DELAY_MS: int = 1000
    SNKRDUNK_REQUEST_DELAY_MS: int = 1000
    SNKRDUNK_AUTO_MATCH_THRESHOLD: float = 0.92
    SNKRDUNK_SEED_FILE: str | None = None


settings = Settings()
