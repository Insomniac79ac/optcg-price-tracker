from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, pagination_response
from app.db import get_db
from app.models import AnalyticsDigestReport, User
from app.schemas import (
    AnalyticsDigestOut,
    AnalyticsDigestReportListOut,
    AnalyticsDigestReportOut,
    AnalyticsDigestReportSummaryOut,
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
from app.services.analytics_digest import build_analytics_digest
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


@router.get("/digest", response_model=AnalyticsDigestOut)
def get_analytics_digest_endpoint(
    response: Response,
    valuation_mode: ValuationMode = Query(default="raw_market"),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = f"analytics_digest:{user.id}:{valuation_mode}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key,
        ttl,
        lambda: build_analytics_digest(
            db, user_id=user.id, valuation_mode=valuation_mode
        ).model_dump(mode="json"),
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


def _digest_report_to_out(report: AnalyticsDigestReport) -> AnalyticsDigestReportOut:
    payload = report.digest_payload_json
    return AnalyticsDigestReportOut(
        id=report.id,
        created_at=report.created_at,
        valuation_mode=report.valuation_mode,
        summary=payload["summary"],
        sections=payload["sections"],
        priority_items=payload["priority_items"],
        deterministic_summary_lines=payload["deterministic_summary_lines"],
        payload=payload,
    )


def _digest_report_to_summary_out(report: AnalyticsDigestReport) -> AnalyticsDigestReportSummaryOut:
    return AnalyticsDigestReportSummaryOut(
        id=report.id,
        created_at=report.created_at,
        valuation_mode=report.valuation_mode,
        collection_value_jpy=report.collection_value_jpy,
        graded_adjusted_value_jpy=report.graded_adjusted_value_jpy,
        portfolio_risk_score=report.portfolio_risk_score,
        portfolio_risk_level=report.portfolio_risk_level,
        wishlist_target_hits=report.wishlist_target_hits,
        buy_review_count=report.buy_review_count,
        sell_review_count=report.sell_review_count,
        grading_roi_jpy=report.grading_roi_jpy,
    )


@router.get("/digest/latest", response_model=AnalyticsDigestReportOut)
def get_latest_analytics_digest_endpoint(
    response: Response,
    valuation_mode: ValuationMode | None = Query(default=None),
    db: Session = Depends(get_db),
):
    def _load() -> dict:
        query = select(AnalyticsDigestReport)
        if valuation_mode is not None:
            query = query.where(AnalyticsDigestReport.valuation_mode == valuation_mode)
        report = db.scalar(
            query.order_by(AnalyticsDigestReport.created_at.desc(), AnalyticsDigestReport.id.desc())
        )
        if report is None:
            raise HTTPException(status_code=404, detail="No analytics digest reports found")
        return _digest_report_to_out(report).model_dump(mode="json")

    cache_key = f"analytics_digest:latest:{valuation_mode}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(cache_key, ttl, _load)
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/digest/reports", response_model=AnalyticsDigestReportListOut)
def list_analytics_digest_reports_endpoint(
    response: Response,
    valuation_mode: ValuationMode | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    def _load() -> dict:
        query = select(AnalyticsDigestReport)
        count_query = select(func.count()).select_from(AnalyticsDigestReport)
        if valuation_mode is not None:
            query = query.where(AnalyticsDigestReport.valuation_mode == valuation_mode)
            count_query = count_query.where(AnalyticsDigestReport.valuation_mode == valuation_mode)
        total = db.scalar(count_query) or 0
        reports = db.scalars(
            query.order_by(AnalyticsDigestReport.created_at.desc(), AnalyticsDigestReport.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        reports_out = [_digest_report_to_summary_out(r) for r in reports]
        return AnalyticsDigestReportListOut(
            reports=reports_out,
            total=total,
            limit=limit,
            offset=offset,
            pagination=pagination_response(reports_out, total, limit, offset),
        ).model_dump(mode="json")

    cache_key = f"analytics_digest:reports:{valuation_mode}:{limit}:{offset}"
    ttl = settings.CACHE_COLLECTION_TTL_SECONDS
    value, hit = get_or_set_cache(cache_key, ttl, _load)
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value


@router.get("/digest/reports/{report_id}", response_model=AnalyticsDigestReportOut)
def get_analytics_digest_report_endpoint(report_id: int, db: Session = Depends(get_db)):
    report = db.get(AnalyticsDigestReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Analytics digest report not found")
    return _digest_report_to_out(report)


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
