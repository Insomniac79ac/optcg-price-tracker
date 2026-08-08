from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Normalize a Postgres DATABASE_URL to the psycopg 3 driver scheme.

    Duplicated from services/worker/worker/settings.py (same reasoning
    there: Railway's standard Postgres.DATABASE_URL/postgres:// alias use a
    bare postgresql:// scheme, which makes SQLAlchemy default to psycopg2 -
    not installed here). Kept as a small duplicated utility rather than a
    shared import, consistent with how app/ and worker/ each already carry
    their own copy independently.
    """
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
    YUYUTEI_REQUEST_DELAY_MS: int = 1000
    BROWSER_LAUNCH_TIMEOUT_S: int = 30
    HOMEPAGE_NAV_TIMEOUT_S: int = 35
    PRODUCT_NAV_TIMEOUT_S: int = 35
    ARTIFACT_WRITE_TIMEOUT_S: int = 15
    TOTAL_RUN_TIMEOUT_S: int = 180
    # Wall-clock budget for an entire --approved-mappings batch (see
    # yuyutei_collector.batch) - independent of, and larger than, a single
    # mapping's own TOTAL_RUN_TIMEOUT_S above. Five mappings at up to 180s
    # each plus inter-mapping delays comfortably fits well under this;
    # sized generously so a batch is never cut off by this watchdog under
    # normal conditions, only as a true worst-case backstop.
    BATCH_TOTAL_TIMEOUT_S: int = 1200

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must not be empty.")
        return normalize_database_url(value)


settings = Settings()
