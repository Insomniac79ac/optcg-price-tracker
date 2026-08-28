from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Normalize a Postgres DATABASE_URL to the psycopg 3 driver scheme.

    Railway's standard Postgres.DATABASE_URL (and the postgres:// alias) use
    a bare postgresql:// scheme, which makes SQLAlchemy default to psycopg2 -
    not installed here (psycopg 3 is). This rewrites only the scheme prefix;
    everything after it (credentials, host, port, database, query string) is
    left byte-for-byte untouched. Already-normalized and unrecognized URLs
    pass through unchanged.
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

    # Artwork as an exact-print evidence channel (app.services.artwork_evidence).
    # OFF by design, not by oversight: the thresholds are provisional and the
    # control corpus (17 exact prints, 14 of them discrimination-testable) is
    # not yet large enough to justify letting an image eliminate a printing
    # unattended. With it off, resolve_exact_print behaves exactly as before -
    # artwork is never consulted and never appears in an explanation.
    ARTWORK_EVIDENCE_ENABLED: bool = False
    ADMIN_LOGIN_EMAIL: str | None = None
    ADMIN_LOGIN_PASSWORD_HASH: str | None = None
    ADMIN_LOGIN_MAX_ATTEMPTS: int = 5
    ADMIN_LOGIN_WINDOW_SECONDS: int = 900
    ADMIN_LOGIN_LOCKOUT_SECONDS: int = 1800

    # Cloudflare R2 object storage (app.services.object_storage) - the future
    # home of mirrored, content-addressed display images. All five are
    # optional and unset by default: nothing in normal API startup, GET
    # /prints, the collectors, the worker or the test suite constructs R2
    # storage, and none of them may be made to require these. They are
    # validated together, and only when an R2ObjectStorage is explicitly
    # constructed - a missing one raises R2ConfigurationError there rather
    # than at import or startup. There is deliberately no fallback to AWS
    # credential discovery (env/instance metadata/~/.aws): if these are not
    # set, no client is built at all.
    #
    # R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY are secrets and must come from
    # the runtime environment - never a committed file, log line, exception
    # message or repr. R2_ACCOUNT_ID, R2_BUCKET_NAME and R2_PUBLIC_BASE_URL
    # are not secrets.
    #
    # R2_PUBLIC_BASE_URL is the *public delivery origin* (the bucket's
    # r2.dev URL or a custom domain), not the S3 API endpoint - the API
    # endpoint is derived from R2_ACCOUNT_ID and is never used to build a
    # public URL. See docs/deployment.md section 1f.
    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET_NAME: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must not be empty.")
        return normalize_database_url(value)

    @field_validator("REDIS_URL")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("REDIS_URL must not be empty.")
        return value


settings = Settings()
