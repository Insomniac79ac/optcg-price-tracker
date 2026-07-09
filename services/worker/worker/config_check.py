import logging

from sqlalchemy import text

from worker.db import engine
from worker.settings import settings

logger = logging.getLogger(__name__)


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
