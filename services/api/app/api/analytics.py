from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.db import get_db
from app.models import User
from app.schemas import (
    BuyDecisionAction,
    BuyDecisionPriorityFilter,
    BuyDecisionSupportOut,
    BuySourcePreference,
    CollectionAnalyticsOut,
    GradingAnalyticsOut,
    PortfolioRiskOut,
    SellDecisionAction,
    SellDecisionSupportOut,
    ValuationMode,
    WishlistAnalyticsOut,
)
from app.services.buy_decision_support import get_buy_decision_support
from app.services.cache import get_or_set_cache
from app.services.cache_headers import set_cache_headers
from app.services.collection_analytics import get_collection_analytics
from app.services.grading_analytics import get_grading_analytics
from app.services.portfolio_risk import get_portfolio_risk
from app.services.sell_decision_support import get_sell_decision_support
from app.services.wishlist_analytics import get_wishlist_analytics
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


@router.get("/wishlist", response_model=WishlistAnalyticsOut)
def get_wishlist_analytics_endpoint(
    response: Response,
    include_removed: bool = Query(default=False),
    include_purchased: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = f"wishlist_analytics:{user.id}:{include_removed}:{include_purchased}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_wishlist_analytics(
            db, user_id=user.id, include_removed=include_removed, include_purchased=include_purchased
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/buy-decisions", response_model=BuyDecisionSupportOut)
def get_buy_decisions_endpoint(
    response: Response,
    source_preference: BuySourcePreference = Query(default="auto"),
    include_owned: bool = Query(default=False),
    include_purchased: bool = Query(default=False),
    min_score: int | None = Query(default=None, ge=0, le=100),
    action: BuyDecisionAction | None = Query(default=None),
    priority: BuyDecisionPriorityFilter | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = (
        f"buy_decisions:{user.id}:{source_preference}:{include_owned}:{include_purchased}:"
        f"{min_score}:{action}:{priority}:{limit}:{offset}"
    )
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_buy_decision_support(
            db,
            user_id=user.id,
            source_preference=source_preference,
            include_owned=include_owned,
            include_purchased=include_purchased,
            min_score=min_score,
            action=action,
            priority=priority,
            limit=limit,
            offset=offset,
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/grading", response_model=GradingAnalyticsOut)
def get_grading_analytics_endpoint(
    response: Response,
    include_cancelled: bool = Query(default=False),
    grading_company: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = (
        f"grading_analytics:{user.id}:{include_cancelled}:{grading_company}:{status}:{limit}:{offset}"
    )
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_grading_analytics(
            db,
            user_id=user.id,
            include_cancelled=include_cancelled,
            grading_company=grading_company,
            status=status,
            limit=limit,
            offset=offset,
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/portfolio-risk", response_model=PortfolioRiskOut)
def get_portfolio_risk_endpoint(
    response: Response,
    valuation_mode: ValuationMode = Query(default="raw_market"),
    include_sold: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = f"portfolio_risk:{user.id}:{valuation_mode}:{include_sold}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_portfolio_risk(
            db, user_id=user.id, valuation_mode=valuation_mode, include_sold=include_sold
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/sell-decisions", response_model=SellDecisionSupportOut)
def get_sell_decisions_endpoint(
    response: Response,
    valuation_mode: ValuationMode = Query(default="raw_market"),
    include_sold: bool = Query(default=False),
    min_score: int | None = Query(default=None, ge=0, le=100),
    action: SellDecisionAction | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = (
        f"sell_decisions:{user.id}:{valuation_mode}:{include_sold}:{min_score}:{action}:{limit}:{offset}"
    )
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: get_sell_decision_support(
            db,
            user_id=user.id,
            valuation_mode=valuation_mode,
            include_sold=include_sold,
            min_score=min_score,
            action=action,
            limit=limit,
            offset=offset,
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value
