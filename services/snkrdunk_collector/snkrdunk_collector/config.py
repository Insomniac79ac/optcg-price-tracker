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
    # How many mappings ONE unscoped --approved-mappings run may process.
    #
    # WHY A LIMIT IS THE FIX AND A BIGGER TIMEOUT IS NOT. Collection is
    # serial by design (never parallel SNKRDUNK requests), so a run's cost
    # grows linearly with the approved population while BATCH_TOTAL_TIMEOUT_S
    # stays fixed. Once the population outgrows the budget the run is cut off
    # mid-list, and because selection was id-ordered it was cut off at the
    # SAME PLACE every night - the tail was never collected at all. Raising
    # the timeout only moves that cliff; it does not remove it.
    #
    # A bounded run plus a fair order removes it: each run takes the least
    # recently attempted slice, so every mapping is reached within a
    # predictable number of runs no matter how large the population grows.
    #
    # 70 is deliberately conservative against the measured 15.0s/mapping
    # (1500s for 100 mappings, 2026-08-31): 70 x 15.0s = 1050s, 58% of the
    # 1800s budget, leaving room for slow pages and retries rather than
    # targeting the theoretical ~110 maximum.
    #
    # Applies ONLY to an unscoped run. An explicit --mapping-ids or --limit
    # states the caller's own scope and is never silently truncated.
    BATCH_MAX_MAPPINGS_PER_RUN: int = 70

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must not be empty.")
        return normalize_database_url(value)


settings = Settings()
