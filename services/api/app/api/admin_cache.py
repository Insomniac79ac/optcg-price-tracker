from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_admin_token
from app.schemas import (
    CacheClearRequestIn,
    CacheClearResponseOut,
    CacheStatsOut,
    CacheStatusOut,
    CacheTtlOut,
)
from app.services.app_logging import record_app_log
from app.services.cache import cache_stats, clear_all_cache, current_backend_name, delete_cache_prefix
from app.settings import settings

router = APIRouter(prefix="/admin/cache", tags=["admin", "cache"], dependencies=[Depends(require_admin_token)])

CLEAR_CONFIRM_PHRASE = "CLEAR"


@router.get("/status", response_model=CacheStatusOut)
def cache_status_endpoint():
    return CacheStatusOut(
        enabled=settings.CACHE_ENABLED,
        backend=current_backend_name(),
        stats=CacheStatsOut(**cache_stats()),
        ttl=CacheTtlOut(
            dashboard=settings.CACHE_DASHBOARD_TTL_SECONDS,
            market=settings.CACHE_MARKET_TTL_SECONDS,
            collection=settings.CACHE_COLLECTION_TTL_SECONDS,
        ),
    )


@router.post("/clear", response_model=CacheClearResponseOut)
def cache_clear_endpoint(body: CacheClearRequestIn):
    if body.confirm != CLEAR_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400, detail=f"Cache clear requires confirm={CLEAR_CONFIRM_PHRASE!r}."
        )

    deleted_count = delete_cache_prefix(body.prefix) if body.prefix else clear_all_cache()

    record_app_log(
        "warning",
        "api",
        "cache_clear",
        f"Cache cleared (prefix={body.prefix or 'all'}).",
        context={"prefix": body.prefix, "deleted_count": deleted_count},
    )

    return CacheClearResponseOut(success=True, prefix=body.prefix, deleted_count=deleted_count)
