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
    MarketAnalyticsBasesOut,
    MarketAnalyticsFiltersOut,
    MarketAnalyticsOverviewOut,
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
from app.services.market_analytics import (
    BasisError,
    build_overview,
    list_bases,
    list_filter_options,
    parse_price_basis,
)
from app.services.portfolio_risk import get_portfolio_risk
from app.services.sell_decision_support import get_sell_decision_support
from app.services.wishlist_analytics import get_wishlist_analytics
from app.settings import settings

router = APIRouter(prefix="/analytics", tags=["analytics"])


# --- current-state market analytics ------------------------------------
#
# DELIBERATELY UNAUTHENTICATED, unlike every other endpoint in this router.
# The rest of /analytics describes what one collector OWNS and must be gated.
# These three describe the catalogue's own prices, and every number they return
# is already public and unauthenticated through GET /prints and
# GET /prints/{id}/market-index - they only count what those already serve.
# /market/filters likewise only republishes the set codes and rarities already
# on every public tile.
# Gating an aggregate of public data would be a lock on the front door of a
# building with no walls, and would keep the market landscape out of the
# public product it is being built for.


@router.get("/market/bases", response_model=MarketAnalyticsBasesOut)
def get_market_bases_endpoint(db: Session = Depends(get_db)):
    """Which price bases a client may select, derived from configuration.

    There is no allowlist here and no source name in this module: the list is
    the intersection of the `sources` table and the primary instruments
    declared in app.services.source_instruments, so a newly configured source
    appears the day it is registered, with no edit to this route, this schema
    or the frontend."""
    return MarketAnalyticsBasesOut(bases=list_bases(db))


@router.get("/market/filters", response_model=MarketAnalyticsFiltersOut)
def get_market_filters_endpoint(db: Session = Depends(get_db)):
    """Which SET and RARITY values the overview will accept, derived from the
    active catalogue.

    Unauthenticated for the same reason the two routes around it are: these are
    the set codes and rarities already printed on every public tile.

    It exists because the alternative was worse in three different ways. The
    print catalogue's facets publish treatment, rarity, language and
    verification status but no release product, so a client had no honest
    source for the SET control: it could sweep /prints and pay 44 requests to
    rediscover something the database answers in one, read the LEGACY
    /cards/catalogue whose `set_code` is spelled `OP01` where this filter wants
    `OP-01` (and whose rows carry legacy card identity - see
    resolveCanonicalPrintIdentity), or hardcode a list that goes stale the day
    a set ships. A filter's vocabulary belongs to whoever owns the filter, so
    it is published here beside the endpoint that accepts it."""
    return MarketAnalyticsFiltersOut(**list_filter_options(db))


@router.get("/market/overview", response_model=MarketAnalyticsOverviewOut)
def get_market_overview_endpoint(
    price_basis: str = Query(default="market_index"),
    set_code: str | None = Query(default=None, alias="set", max_length=32),
    rarity: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
):
    """CURRENT market landscape for one basis and one slice of the catalogue.

    No window parameter, by design: this tranche reports what prices ARE, not
    how they moved. An unrecognised source is not a 404 - it comes back as an
    explicitly unavailable basis with truthful zero counts, the same way a
    print series does, because "Atlas does not price with that" is an answer.
    """
    try:
        basis = parse_price_basis(price_basis)
    except BasisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MarketAnalyticsOverviewOut(
        **build_overview(db, basis=basis, set_code=set_code, rarity=rarity)
    )


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
