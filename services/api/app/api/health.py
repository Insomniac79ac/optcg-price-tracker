from fastapi import APIRouter

from app.config_check import check_database_connected, check_redis_connected
from app.env import get_app_env

router = APIRouter()


@router.get("/health")
def health() -> dict:
    database_connected = check_database_connected()
    redis_connected = check_redis_connected()
    return {
        "status": "ok" if database_connected else "degraded",
        "app_env": get_app_env(),
        "database_connected": database_connected,
        "redis_connected": redis_connected,
    }
