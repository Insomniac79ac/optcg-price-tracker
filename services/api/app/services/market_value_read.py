"""SELECT-only projection of persisted MarketValuePoint and ReleaseProduct.

No archive replay, live valuation, source access or writer dependency. The
frozen engine supplies only version/precision/reason constants. Publication
decisions are persisted evidence, never recalculated from today's catalogue.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.market_value_schemas import (
    MarketValueMovementOut,
    MarketValueMovementSummaryOut,
    MarketValueOut,
    MarketValueReleaseOut,
    MarketValueReleasesOut,
    MarketValueSeriesPointOut,
    MarketValueTrackedOut,
    MarketValueWindow,
)
from app.models.market_value_point import MarketValuePoint
from app.models.release_product import ReleaseProduct
from app.services.market_value import (
    CALCULATION_DECIMAL_PRECISION,
    METHODOLOGY_VERSION,
    PublicationReason,
)
from app.services.release_ordering import ORDERING_BASIS, public_release_ordering

WINDOW_DAYS = {"7d": 7, "30d": 30, "all": None}


class MarketValueUnavailableError(RuntimeError):
    """The requested persisted v1 read model has not been seeded."""


class UnknownMarketValueReleaseError(LookupError):
    pass


def _scope(release_product_id: int | None):
    return (
        MarketValuePoint.scope_kind
        == ("overall" if release_product_id is None else "release"),
        MarketValuePoint.release_product_id == release_product_id,
        MarketValuePoint.methodology_version == METHODOLOGY_VERSION,
    )


def _latest_date(db: Session, release_product_id: int | None) -> date:
    latest = db.scalar(
        select(func.max(MarketValuePoint.point_date)).where(*_scope(release_product_id))
    )
    if latest is None:
        raise MarketValueUnavailableError("market_value_not_seeded")
    return latest


def _tracked(point: MarketValuePoint) -> MarketValueTrackedOut:
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        coverage = (
            Decimal(point.priced_print_count)
            / Decimal(point.total_physical_print_count)
            * 100
            if point.total_physical_print_count
            else None
        )
    return MarketValueTrackedOut(
        value_jpy=point.tracked_value_jpy,
        priced_print_count=point.priced_print_count,
        total_physical_print_count=point.total_physical_print_count,
        physical_coverage_pct=coverage,
        is_partial=point.priced_print_count < point.total_physical_print_count,
    )


def _publication_reason(point: MarketValuePoint) -> str:
    primary = (point.publication_reasons or "").split("|", 1)[0]
    known = {reason.value for reason in PublicationReason} - {"publishable"}
    # Unknown stored text must not become a public free-form/internal message.
    return primary if primary in known else "invalid_chain_evidence"


def _step_reason(prior: MarketValuePoint, point: MarketValuePoint) -> str | None:
    if (
        point.point_date - prior.point_date != timedelta(days=1)
        or point.prior_point_date != prior.point_date
        or point.step_days != 1
    ):
        return "insufficient_window_continuity"
    if point.step_publication_eligible is not True:
        return _publication_reason(point)
    if point.segment_number != prior.segment_number:
        return "segment_break"
    if (
        point.publication_reasons != "publishable"
        or point.methodology_version != prior.methodology_version
        or point.performance_factor <= 0
        or prior.performance_factor <= 0
        or not point.prior_comparable_value_jpy
        or point.prior_comparable_value_jpy < 0
        or not point.current_comparable_value_jpy
        or point.current_comparable_value_jpy < 0
        or point.step_ratio is None
        or point.step_ratio <= 0
    ):
        return "invalid_chain_evidence"
    return None


def _movement(
    points: list[MarketValuePoint], window: MarketValueWindow
) -> MarketValueMovementOut:
    end = points[-1].point_date
    days = WINDOW_DAYS[window]
    start = end - timedelta(days=days) if days is not None else points[0].point_date
    span = [point for point in points if start <= point.point_date <= end]
    reason = None
    fraction = pct = None
    if (
        len(span) < 2
        or span[0].point_date != start
        or len(span) != (end - start).days + 1
    ):
        reason = "insufficient_window_continuity"
    else:
        numerator = denominator = 1
        for prior, point in zip(span, span[1:]):
            reason = _step_reason(prior, point)
            if reason:
                break
            # The persisted comparable integer P/Q pairs are the chain's
            # evidence. Match A2's exact rational multiplication and single
            # Decimal conversion; never divide literal tracked basket sums.
            numerator *= point.current_comparable_value_jpy
            denominator *= point.prior_comparable_value_jpy
        if reason is None:
            with localcontext() as context:
                context.prec = CALCULATION_DECIMAL_PRECISION
                fraction = Decimal(numerator) / Decimal(denominator) - 1
                pct = fraction * 100
    return MarketValueMovementOut(
        window=window,
        available=reason is None,
        from_date=start,
        to_date=end,
        fraction=fraction,
        pct=pct,
        reason=reason or "publishable",
    )


def _series(points: list[MarketValuePoint]) -> list[MarketValueSeriesPointOut]:
    result = []
    anchor = None
    continuous = True
    for index, point in enumerate(points):
        reason = (
            "publishable"
            if point.step_publication_eligible is True
            else (
                "initial_point"
                if point.prior_point_date is None
                else _publication_reason(point)
            )
        )
        if anchor is not None and _step_reason(points[index - 1], point):
            continuous = False
        valid = (
            point.tracked_value_jpy is not None
            and point.performance_factor > 0
            and (
                point.step_publication_eligible is True
                or point.prior_point_date is None
            )
        )
        if anchor is None and valid:
            anchor = point
        performance = None
        if anchor is not None and valid and continuous:
            with localcontext() as context:
                context.prec = CALCULATION_DECIMAL_PRECISION
                performance = (
                    point.performance_factor / anchor.performance_factor - 1
                ) * 100
        result.append(
            MarketValueSeriesPointOut(
                date=point.point_date,
                tracked_value_jpy=point.tracked_value_jpy,
                priced_print_count=point.priced_print_count,
                total_physical_print_count=point.total_physical_print_count,
                performance_pct=performance,
                step_publication_eligible=point.step_publication_eligible,
                publication_reason=reason,
            )
        )
    return result


def get_market_value(
    db: Session,
    *,
    release_product_id: int | None = None,
    window: MarketValueWindow = "7d"
) -> MarketValueOut:
    if window not in WINDOW_DAYS:
        raise ValueError("unsupported Market Value window")
    with db.no_autoflush:
        release = None
        if release_product_id is not None:
            release = db.get(ReleaseProduct, release_product_id)
            if release is None:
                raise UnknownMarketValueReleaseError("release_product_not_found")
        overall_date = _latest_date(db, None)
        as_of = (
            overall_date if release is None else _latest_date(db, release_product_id)
        )
        query = select(MarketValuePoint).where(
            *_scope(release_product_id), MarketValuePoint.point_date <= as_of
        )
        days = WINDOW_DAYS[window]
        if days is not None:
            query = query.where(
                MarketValuePoint.point_date >= as_of - timedelta(days=days)
            )
        points = list(db.scalars(query.order_by(MarketValuePoint.point_date)).all())
        return MarketValueOut(
            scope_kind="overall" if release is None else "release",
            release_product_id=release_product_id,
            release_code=release.official_code if release else None,
            release_name=release.display_name if release else None,
            methodology_version=METHODOLOGY_VERSION,
            as_of=as_of,
            tracked_value=_tracked(points[-1]),
            movement=_movement(points, window),
            series=_series(points),
        )


def list_market_value_releases(db: Session) -> MarketValueReleasesOut:
    with db.no_autoflush:
        _latest_date(
            db, None
        )  # An unseeded Overall model is unavailable, not an empty success.
        # Bounded to 31 stored points per release, regardless of archive age.
        # Missing dates still fail the exact-date span check in _movement.
        ranked = (
            select(
                MarketValuePoint,
                func.row_number()
                .over(
                    partition_by=MarketValuePoint.release_product_id,
                    order_by=MarketValuePoint.point_date.desc(),
                )
                .label("position"),
            )
            .where(
                MarketValuePoint.scope_kind == "release",
                MarketValuePoint.methodology_version == METHODOLOGY_VERSION,
            )
            .subquery()
        )
        point = aliased(MarketValuePoint, ranked)
        rows = db.execute(
            select(ReleaseProduct, point)
            .join(point, point.release_product_id == ReleaseProduct.id)
            .where(
                ranked.c.position <= 31,
                ReleaseProduct.source_catalogue == "bandai_jp",
                ReleaseProduct.official_code.is_not(None),
                ReleaseProduct.verification_status == "verified",
            )
            .order_by(*public_release_ordering(), point.point_date)
        ).all()
        grouped = defaultdict(list)
        releases = {}
        for release, stored in rows:
            releases[release.id] = release
            grouped[release.id].append(stored)
        items = []
        for release_id, points in grouped.items():
            latest = points[-1]
            if latest.total_physical_print_count == 0:
                continue
            release = releases[release_id]
            items.append(
                MarketValueReleaseOut(
                    release_product_id=release_id,
                    release_code=release.official_code,
                    release_name=release.display_name,
                    as_of=latest.point_date,
                    methodology_version=METHODOLOGY_VERSION,
                    tracked_value=_tracked(latest),
                    seven_day=MarketValueMovementSummaryOut(
                        **_movement(points, "7d").model_dump()
                    ),
                    thirty_day=MarketValueMovementSummaryOut(
                        **_movement(points, "30d").model_dump()
                    ),
                )
            )
        return MarketValueReleasesOut(items=items, ordering_basis=ORDERING_BASIS)
