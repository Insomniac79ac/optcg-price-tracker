from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"
    REDIS_URL: str = "redis://redis:6379/0"
    ENVIRONMENT: str | None = None
    APP_ENV: str | None = None
    ADMIN_TOKEN: str | None = None
    # Shared secret used to verify the short-lived bearer JWT the frontend
    # mints (in its NextAuth session callback) for per-user requests to
    # /collection, /grading, /collector - see app.auth.require_current_user.
    API_JWT_SECRET: str | None = None
    # CORS lockdown for production (e.g. the Vercel frontend's origin(s)).
    # Both unset (the local/dev default) falls back to allow_origins=["*"] -
    # see app/main.py. CORS_ALLOWED_ORIGINS is a comma-separated exact-origin
    # list; CORS_ALLOW_ORIGIN_REGEX additionally covers Vercel preview
    # deployments (e.g. "https://.*\\.vercel\\.app").
    CORS_ALLOWED_ORIGINS: str | None = None
    CORS_ALLOW_ORIGIN_REGEX: str | None = None
    # Telegram alerting - if either is unset, digest sends are logged and
    # skipped rather than attempted (see app.services.telegram_client).
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    # Where scripts/db_backup.sh writes gzipped pg_dump backups - relative to
    # this process's cwd (== /app in the api container, matching the
    # `./data:/app/data` volume mount in docker-compose.prod.yml, so this
    # resolves to the same directory the script writes to on the host). See
    # app.api.admin_db_backups (GET /admin/db-backups).
    DB_BACKUP_DIR: str = "data/backups/db"

    # In-memory per-IP request rate limiting - see app.core.rate_limit and
    # 'Rate limiting' in docs/deployment.md. Single-instance only (state
    # lives in this process's memory); a distributed deployment should move
    # this to a reverse proxy or Redis instead. Disabling is a warning, not a
    # startup failure, in production - see app.core.env_validation.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PUBLIC_READ_PER_5M: int = 300
    RATE_LIMIT_COLLECTION_WRITE_PER_5M: int = 60
    RATE_LIMIT_ADMIN_PER_5M: int = 120
    RATE_LIMIT_IMPORT_EXPORT_PER_10M: int = 20
    RATE_LIMIT_SEARCH_PER_5M: int = 120

    # Per-request timing (app.core.request_timing) - every response gets an
    # X-Process-Time-Ms header regardless; a request slower than
    # SLOW_REQUEST_MS additionally gets a warning app_log_events row (see
    # GET /admin/performance/summary). Disabling only stops the log write,
    # the header is always added.
    SLOW_REQUEST_LOGGING_ENABLED: bool = True
    SLOW_REQUEST_MS: int = 1000

    # Per-response size visibility (app.core.response_size) - every response
    # gets an X-Response-Size-Bytes header regardless; a response larger than
    # RESPONSE_SIZE_WARNING_BYTES additionally gets a warning app_log_events
    # row (event_type=response_size_warning, see GET /admin/performance/summary
    # and GET /admin/logs?event_type=response_size_warning). Never blocks the
    # response - visibility only, same as SLOW_REQUEST_* above.
    RESPONSE_SIZE_WARNING_ENABLED: bool = True
    RESPONSE_SIZE_WARNING_BYTES: int = 1_000_000

    # Read-endpoint caching (app.services.cache) - see 'Cache operations' in
    # docs/operations.md and GET /admin/cache/status. CACHE_BACKEND=redis
    # (the default) falls back to an in-memory cache only in development if
    # Redis is unreachable; in every other environment a Redis failure just
    # makes individual reads uncached rather than switching backend. Setting
    # CACHE_BACKEND=none (or CACHE_ENABLED=false) disables caching outright.
    CACHE_ENABLED: bool = True
    CACHE_BACKEND: str = "redis"
    CACHE_DEFAULT_TTL_SECONDS: int = 60
    CACHE_DASHBOARD_TTL_SECONDS: int = 60
    CACHE_MARKET_TTL_SECONDS: int = 120
    CACHE_COLLECTION_TTL_SECONDS: int = 60
    CACHE_CATALOG_COVERAGE_TTL_SECONDS: int = 120
    CACHE_PRICE_SOURCE_HEALTH_TTL_SECONDS: int = 60

    # Background file jobs (app.services.file_jobs / app.services.
    # file_job_storage) - see 'Large import/export jobs' in
    # docs/operations.md and GET/POST /file-jobs*. FILE_JOB_STORAGE_DIR is
    # relative to this process's cwd, same convention as DB_BACKUP_DIR above.
    # FILE_JOBS_SYNC_FALLBACK left unset (None) picks its default from the
    # environment (true in development, false otherwise) - see
    # app.env.file_jobs_sync_fallback_effective(); set it explicitly to
    # override that in either direction.
    FILE_JOB_STORAGE_DIR: str = "data/file_jobs"
    FILE_JOB_MAX_UPLOAD_MB: int = 50
    FILE_JOBS_SYNC_FALLBACK: bool | None = None

    # Temporary single-admin Credentials login (app.api.admin_login, POST
    # /auth/admin/verify) - a staging-only prototype until Google OAuth plus
    # an admin-email allowlist replaces it. Deliberately NOT a user-table
    # row: ADMIN_LOGIN_EMAIL/ADMIN_LOGIN_PASSWORD_HASH are the entire
    # "account". ADMIN_LOGIN_ENABLED defaults to false, and the endpoint
    # additionally treats a missing email/hash as disabled regardless of
    # this flag (see app.api.admin_login) - there is no default identity or
    # password. ADMIN_LOGIN_PASSWORD_HASH is a standard Argon2id encoded
    # hash string (see app.core.admin_password) - never the plaintext
    # password, and never ADMIN_TOKEN itself. Suggested staging values for
    # the throttle settings: 5 attempts / 15 minutes, 30-minute lockout -
    # see app.core.admin_login_throttle for the Redis-backed enforcement
    # (deliberately not app.core.rate_limit, which is in-memory/per-process
    # and unsuitable for a public login endpoint).
    ADMIN_LOGIN_ENABLED: bool = False
    ADMIN_LOGIN_EMAIL: str | None = None
    ADMIN_LOGIN_PASSWORD_HASH: str | None = None
    ADMIN_LOGIN_MAX_ATTEMPTS: int = 5
    ADMIN_LOGIN_WINDOW_SECONDS: int = 900
    ADMIN_LOGIN_LOCKOUT_SECONDS: int = 1800

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
