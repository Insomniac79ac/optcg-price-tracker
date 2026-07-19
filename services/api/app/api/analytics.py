from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import User
from app.schemas import CollectionAnalyticsOut, ValuationMode
from app.services.cache import get_or_set_cache
from app.services.cache_headers import set_cache_headers
from app.services.collection_analytics import get_collection_analytics
from app.settings import settings

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/collection", response_model=CollectionAnalyticsOut)
def get_collection_analytics_endpoint(
    response: Response,
    valuation_mode: ValuationMode = Query(default="raw_market"),
    include_sold: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = f"collection_analytics:{user.id}:{valuation_mode}:{include_sold}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_collection_analytics(
            db, user_id=user.id, valuation_mode=valuation_mode, include_sold=include_sold
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value
