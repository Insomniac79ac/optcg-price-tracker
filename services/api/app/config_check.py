import logging
from dataclasses import dataclass, field

from sqlalchemy import text

from app.db import engine
from app.env import get_app_env, is_production_environment
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ConfigCheckResult:
    ok: bool
    app_env: str
    errors: list[str] = field(default_factory=list)

    def print_report(self) -> None:
        print(f"api_config_status: {'ok' if self.ok else 'invalid'}")
        print(f"environment: {self.app_env}")
        for error in self.errors:
            print(f"error: {error}")


def validate_config() -> ConfigCheckResult:
    """Validates config that depends on more than one setting at once (and
    so can't live on a single Settings field_validator) - currently just
    that ADMIN_TOKEN is configured whenever APP_ENV/ENVIRONMENT is
    'production'. DATABASE_URL/REDIS_URL are validated directly on Settings
    (see app/settings.py) - if this function runs at all, those already
    passed, since constructing `settings` would have raised otherwise."""
    errors: list[str] = []

    if is_production_environment() and not settings.ADMIN_TOKEN:
        errors.append(
            "ADMIN_TOKEN is required when APP_ENV/ENVIRONMENT is 'production'."
        )

    return ConfigCheckResult(ok=not errors, app_env=get_app_env(), errors=errors)


def check_database_connected() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False


def check_redis_connected() -> bool:
    try:
        import redis

        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception as exc:
        logger.warning("Redis connectivity check failed: %s", exc)
        return False
