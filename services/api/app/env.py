from app.settings import settings

DEV_ENVIRONMENT_VALUE = "development"


def is_development_environment() -> bool:
    env = (settings.ENVIRONMENT or settings.APP_ENV or "").strip().lower()
    return env == DEV_ENVIRONMENT_VALUE
