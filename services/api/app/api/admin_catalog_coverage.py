"""Catalog coverage endpoints, built on top of app.services.catalog_coverage.
See GET /admin/catalog-coverage (the full report, cached) and GET
/admin/catalog-coverage/gaps (a paginated, gap_type-scoped drill-down, not
cached - see that module's docstring for why).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.schemas import CatalogCoverageGapItemOut, CatalogCoverageGapsOut, CatalogCoverageReportOut
from app.services.cache import get_or_set_cache
from app.services.cache_headers import set_cache_headers
from app.services.catalog_coverage import (
    GAP_TYPES,
    CatalogCoverageFilters,
    compute_catalog_coverage,
    paginated_gaps,
)
from app.settings import settings

router = APIRouter(prefix="/admin/catalog-coverage", tags=["admin"], dependencies=[Depends(require_admin_token)])

SEVERITY_VALUES = ("critical", "warning", "review")


@router.get("", response_model=CatalogCoverageReportOut)
def get_catalog_coverage(
    response: Response,
    set_code: str | None = Query(default=None),
    language: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    cache_key = f"admin/catalog_coverage:{set_code}:{language}:{variant}:{rarity}:{include_inactive}"
    ttl = settings.CACHE_CATALOG_COVERAGE_TTL_SECONDS

    def _load():
        filters = CatalogCoverageFilters(
            set_code=set_code, language=language, variant=variant, rarity=rarity,
            include_inactive=include_inactive,
        )
        report = compute_catalog_coverage(db, filters)
        return CatalogCoverageReportOut.model_validate(report.to_dict()).model_dump(mode="json")

    value, hit = get_or_set_cache(cache_key, ttl, _load)
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/gaps", response_model=CatalogCoverageGapsOut)
def get_catalog_coverage_gaps(
    gap_type: str = Query(...),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    language: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if gap_type not in GAP_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid gap_type. Must be one of {list(GAP_TYPES)}")
    if severity is not None and severity not in SEVERITY_VALUES:
        raise HTTPException(
            status_code=400, detail=f"Invalid severity. Must be one of {list(SEVERITY_VALUES)}"
        )

    filters = CatalogCoverageFilters(set_code=set_code, language=language, variant=variant, rarity=rarity)
    items, total = paginated_gaps(
        db, gap_type, filters, severity=severity, limit=limit, offset=offset
    )
    out_items = [
        CatalogCoverageGapItemOut.model_validate(i.to_dict()) for i in items
    ]
    return CatalogCoverageGapsOut(
        gap_type=gap_type,
        items=out_items,
        pagination=pagination_response(out_items, total, limit, offset),
    )
