from app.settings import settings

DEV_ENVIRONMENT_VALUE = "development"
PRODUCTION_ENVIRONMENT_VALUE = "production"


def is_development_environment() -> bool:
    env = (settings.ENVIRONMENT or settings.APP_ENV or "").strip().lower()
    return env == DEV_ENVIRONMENT_VALUE


def get_app_env() -> str:
    """Normalized environment name for reporting (health, check_config) and
    for the production/ADMIN_TOKEN startup check - defaults to
    'development' when neither ENVIRONMENT nor APP_ENV is set.

    This is a reporting default, not a security bypass: it must never be
    used to decide whether to allow an admin request without a token - that
    stays on is_development_environment() above, which is strict and treats
    an unset environment as NOT development."""
    env = (settings.ENVIRONMENT or settings.APP_ENV or "").strip().lower()
    return env or DEV_ENVIRONMENT_VALUE


def is_production_environment() -> bool:
    return get_app_env() == PRODUCTION_ENVIRONMENT_VALUE


def file_jobs_sync_fallback_effective() -> bool:
    """settings.FILE_JOBS_SYNC_FALLBACK, or - if unset - true in development
    and false everywhere else, per 'FILE_JOBS_SYNC_FALLBACK default true in
    development, default false in production' (docs/operations.md 'Large
    import/export jobs'). An explicit env var always wins over this
    environment-based default."""
    if settings.FILE_JOBS_SYNC_FALLBACK is not None:
        return settings.FILE_JOBS_SYNC_FALLBACK
    return is_development_environment()
