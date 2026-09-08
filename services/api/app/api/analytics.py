from datetime import date

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
    CardPirateIndexBreakOut,
    CardPirateIndexChangeOut,
    CardPirateIndexCompositionOut,
    CardPirateIndexOut,
    CardPirateIndexPointOut,
    CardPirateIndexRarityBucketOut,
    CardPirateIndexWindowOut,
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
from app.services.card_pirate_index_composition import (
    CompositionIntegrityError,
    get_index_composition,
)
from app.services.card_pirate_index_read import (
    UnknownWindowError,
    get_index_series,
)
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


@router.get("/index", response_model=CardPirateIndexOut)
def get_card_pirate_index_endpoint(
    response: Response,
    window: str | None = Query(default=None, max_length=8),
    db: Session = Depends(get_db),
):
    """The published Card Pirate Index over one window.

    DELIBERATELY UNAUTHENTICATED, on exactly the argument the three
    /market/* routes above already make: every number here is an aggregate of
    values that are already public through GET /prints and
    GET /prints/{id}/market-index. Gating an aggregate of public data would be
    a lock on the front door of a building with no walls.

    READ-ONLY BY CONSTRUCTION. This serves `card_pirate_index_points` and
    runs no estimator: the level for a date is the level that was published on
    that date, not one re-derived now. That is the same immutability argument
    the points table itself was created for - a read-time recomputation would
    let a later change to the cap or to MIN_CONSTITUENTS silently rewrite a
    number a collector already screenshotted.

    The window narrows which stored rows are returned and nothing else. There
    is no forward-fill, no interpolation and no padding: a request reaching
    further back than the archive goes is answered with the archive that
    exists, and `covers_requested_window` reports the shortfall rather than
    the response disguising it.

    OMITTING `?window=` MEANS "the server's own default", not a fixed token.
    The route used to fall back to `3m` here while the payload's
    `default_window` said `all`, so a client that wanted the product default
    had to know the two disagreed and ask for something else - the frontend
    carried a `BOOTSTRAP_WINDOW` constant to do exactly that. There is now one
    notion of default: section 13.1's ladder, resolved server-side against the
    archive's real extent. The day three months of history exists, a request
    with no window starts returning `3m` with no client change.

    An implicit request is otherwise indistinguishable from the explicit
    request for the same token: `requested_window` names the window actually
    selected, and every field beside it describes that window.
    """
    try:
        series = get_index_series(db, window=window)
    except UnknownWindowError as exc:
        # 400, not 422: the token is a value this endpoint knows it does not
        # support, and the message names the supported grammar so a client is
        # never left guessing.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    set_cache_headers(response, hit=False, ttl_seconds=300, cache_key=None)
    return CardPirateIndexOut(
        scope_kind=series.scope_kind,
        scope_key=series.scope_key,
        methodology_version=series.methodology_version,
        index_version=series.index_version,
        source_semantics_version=series.source_semantics_version,
        requested_window=series.requested_window,
        window_start=series.window_start,
        available_from=series.available_from,
        available_to=series.available_to,
        covers_requested_window=series.covers_requested_window,
        points=[
            CardPirateIndexPointOut(
                date=p.point_date,
                value=p.index_value,
                is_base=p.is_base,
                prior_point_date=p.prior_point_date,
                step_days=p.step_days,
                chain_link_log_return=p.chain_link_log_return,
                constituent_count=p.constituent_count,
                eligible_print_count=p.eligible_print_count,
                movers_up=p.movers_up,
                movers_down=p.movers_down,
                movers_flat=p.movers_flat,
                capped_count=p.capped_count,
            )
            for p in series.points
        ],
        starting_value=series.starting_value,
        current_value=series.current_value,
        low_value=series.low_value,
        high_value=series.high_value,
        change=(
            CardPirateIndexChangeOut(
                absolute=series.change.absolute,
                pct=series.change.pct,
                from_date=series.change.from_date,
                to_date=series.change.to_date,
                spans_break=series.change.spans_break,
            )
            if series.change is not None
            else None
        ),
        change_unavailable_reason=series.change_unavailable_reason,
        # Section 12.1's server-authored metadata. Passed through exactly as
        # the read service decided it - the route neither re-derives the ladder
        # nor filters the break list, because either would put a second copy of
        # a frozen rule on this side of the boundary.
        windows=[
            CardPirateIndexWindowOut(
                token=w.token,
                available=w.available,
                covered_days=w.covered_days,
                required_days=w.required_days,
            )
            for w in series.windows
        ],
        default_window=series.default_window,
        breaks=[
            CardPirateIndexBreakOut(
                at=b.at,
                reason=b.reason,
                from_methodology_version=b.from_methodology_version,
                to_methodology_version=b.to_methodology_version,
                from_index_version=b.from_index_version,
                to_index_version=b.to_index_version,
                from_source_semantics_version=b.from_source_semantics_version,
                to_source_semantics_version=b.to_source_semantics_version,
                carried=b.carried,
                carried_level=b.carried_level,
                carried_from_point_date=b.carried_from_point_date,
                prior_point_date=b.prior_point_date,
                step_days=b.step_days,
            )
            for b in series.breaks
        ],
    )



@router.get("/index/composition", response_model=CardPirateIndexCompositionOut)
def get_card_pirate_index_composition_endpoint(
    response: Response,
    date_: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    """What was in the Card Pirate Index on one published day, by rarity.

    UNAUTHENTICATED for the same reason the index itself is: this is an
    aggregate over prints whose rarity is already public at GET /prints, and
    it names none of them.

    READ-ONLY AND ARCHIVE-ONLY. The constituent set is reconstructed from the
    archived `market_index_snapshots` for the selected point's own two days,
    through the estimator's own membership predicate. No live resolver runs,
    no price is recomputed, and `price_observations` is never read - so this
    answers "what was in the index on that day", not "what would be in it if
    it were computed now".

    A SUPPLIED `?date=` SELECTS EXACTLY THAT DAY, and 404s when no published
    point exists for it. It never falls back to the nearest published day: a
    caller who asked for 2026-09-05 and silently received 2026-09-04's
    composition would caption someone else's numbers with their own date, and
    nothing in the payload would let them notice.

    SEPARATE FROM `/analytics/index` ON PURPOSE. The composition does not vary
    with `?window=`, so folding it into that payload would make all seven
    window presses pay a two-day snapshot rescan that cannot change the
    answer.
    """
    try:
        composition = get_index_composition(db, on=date_)
    except CompositionIntegrityError as exc:
        # 500, not a degraded 200. The derivation disagreeing with the
        # published point means one of the two is wrong, and this endpoint has
        # no way to know which - so it publishes neither.
        raise HTTPException(
            status_code=500,
            detail=f"index composition failed its integrity check: {exc}",
        ) from exc

    if composition is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no published Card Pirate Index point for {date_.isoformat()}"
                if date_ is not None
                else "no published Card Pirate Index point"
            ),
        )

    # A real key, not None. `set_cache_headers` stamps X-Cache-Key only in a
    # development environment, and its parameter is typed `str` - passing None
    # crashes there while looking fine everywhere else, which is exactly the
    # kind of defect that reaches a developer's console and nobody else's.
    set_cache_headers(
        response,
        hit=False,
        ttl_seconds=300,
        cache_key=f"analytics:index:composition:{composition.as_of.isoformat()}",
    )
    return CardPirateIndexCompositionOut(
        as_of=composition.as_of,
        constituent_count=composition.constituent_count,
        rarity=[
            CardPirateIndexRarityBucketOut(
                key=b.key, label=b.label, count=b.count, pct=float(b.pct)
            )
            for b in composition.rarity
        ],
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
