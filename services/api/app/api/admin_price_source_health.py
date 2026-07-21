"""Price source health endpoints, built on top of
app.services.price_source_health. See GET /admin/price-source-health (the
full report, cached) and GET /admin/price-source-health/gaps (a paginated,
gap_type-scoped drill-down, not cached).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.schemas import PriceGapItemOut, PriceSourceHealthGapsOut, PriceSourceHealthReportOut
from app.services.cache import get_or_set_cache
from app.services.cache_headers import set_cache_headers
from app.services.price_source_health import (
    GAP_TYPES,
    PriceSourceHealthFilters,
    compute_price_source_health,
    paginated_gaps,
)
from app.settings import settings

router = APIRouter(
    prefix="/admin/price-source-health", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("", response_model=PriceSourceHealthReportOut)
def get_price_source_health(
    response: Response,
    source: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    language: str | None = Query(default=None),
    include_inactive_mappings: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    cache_key = (
        f"admin/price_source_health:{source}:{set_code}:{rarity}:{variant}:{language}:"
        f"{include_inactive_mappings}"
    )
    ttl = settings.CACHE_PRICE_SOURCE_HEALTH_TTL_SECONDS

    def _load():
        filters = PriceSourceHealthFilters(
            source=source, set_code=set_code, rarity=rarity, variant=variant, language=language,
            include_inactive_mappings=include_inactive_mappings,
        )
        report = compute_price_source_health(db, filters)
        return PriceSourceHealthReportOut.model_validate(report.to_dict()).model_dump(mode="json")

    value, hit = get_or_set_cache(cache_key, ttl, _load)
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/gaps", response_model=PriceSourceHealthGapsOut)
def get_price_source_health_gaps(
    gap_type: str = Query(...),
    source: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if gap_type not in GAP_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid gap_type. Must be one of {list(GAP_TYPES)}")

    filters = PriceSourceHealthFilters(source=source, set_code=set_code, rarity=rarity)
    items, total = paginated_gaps(db, gap_type, filters, limit=limit, offset=offset)
    out_items = [PriceGapItemOut.model_validate(i.to_dict()) for i in items]
    return PriceSourceHealthGapsOut(
        gap_type=gap_type,
        items=out_items,
        pagination=pagination_response(out_items, total, limit, offset),
    )
