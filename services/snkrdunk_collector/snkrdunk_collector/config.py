"""Non-secret runtime configuration - mirrors
services/yuyutei_collector/yuyutei_collector/config.py's structure and
DATABASE_URL-normalization reasoning (Railway's Postgres.DATABASE_URL uses a
bare postgresql:// scheme, which makes SQLAlchemy default to psycopg2 - not
installed here; normalize to psycopg 3 explicitly)."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"

    # Non-secret scraper configuration - all overridable via plain Railway
    # service variables, no credentials involved.
    BROWSER_LAUNCH_TIMEOUT_S: int = 30
    HOMEPAGE_NAV_TIMEOUT_S: int = 35
    PRODUCT_NAV_TIMEOUT_S: int = 35
    SALES_HISTORY_NAV_TIMEOUT_S: int = 35
    IMAGE_FETCH_TIMEOUT_S: int = 20
    TOTAL_RUN_TIMEOUT_S: int = 180
    # Conservative fixed delay between mappings in an --approved-mappings
    # batch (see batch.py) - mirrors YUYUTEI_REQUEST_DELAY_MS's reasoning.
    SNKRDUNK_REQUEST_DELAY_MS: int = 1000
    # Wall-clock budget for an entire --approved-mappings batch, independent
    # of (and larger than) a single mapping's own TOTAL_RUN_TIMEOUT_S. 20
    # mappings at up to 180s each plus inter-mapping delays comfortably fits
    # well under this.
    BATCH_TOTAL_TIMEOUT_S: int = 1800

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must not be empty.")
        return normalize_database_url(value)


settings = Settings()
