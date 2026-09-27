"""SELECT-only decompositions of persisted Market Value evidence.

Only the selected two snapshot dates (movers), or one persisted as_of date
(Most Valuable), are read. No replay, writer, current resolver or source I/O.
Catalogue labels are current; membership must match the frozen global A2
digest. Archive prices and persisted aggregate facts remain authoritative.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.market_value_ranking_schemas import (
    IntegrityReason,
    MarketValueIntegrityDetail,
    MarketValueMostValuableOut,
    MarketValueMoverOrder,
    MarketValueMoverOut,
    MarketValueMoversOut,
    MarketValuePanelOut,
    MarketValueValuablePrintOut,
)
from app.models.canonical_card import CanonicalCard
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.models.market_value_point import MarketValuePoint
from app.models.release_product import ReleaseProduct
from app.services.display_image import get_display_images_for_prints
from app.services.market_index_change import eligible_contributor_set
from app.services.market_value import (
    CALCULATION_DECIMAL_PRECISION,
    MarketValueDay,
    MarketValueObservation,
    MarketValueScope,
    MonetaryStep,
    compute_monetary_step,
    evaluate_market_value_publication,
)
from app.services.market_value_provenance import (
    ActivePrintIdentity,
    membership_revision,
    publication_reasons_text,
    version_pairs_text,
)
from app.services.market_value_read import (
    MarketValueUnavailableError,
    UnknownMarketValueReleaseError,
    _latest_date,
    _scope,
)


class MarketValueIntegrityError(RuntimeError):
    def __init__(self, reason: IntegrityReason):
        self.detail = MarketValueIntegrityDetail(reason=reason)
        super().__init__(reason)


def _selected_scope(db: Session, release_product_id: int | None):
    release = None
    if release_product_id is not None:
        release = db.get(ReleaseProduct, release_product_id)
        if release is None:
            raise UnknownMarketValueReleaseError("release_product_not_found")
    _latest_date(db, None)  # Same unseeded Overall guard as A4A.
    latest = db.scalar(
        select(MarketValuePoint)
        .where(*_scope(release_product_id))
        .order_by(MarketValuePoint.point_date.desc())
        .limit(1)
    )
    if latest is None:
        raise MarketValueUnavailableError("market_value_not_seeded")
    identity = dict(
        scope_kind=latest.scope_kind,
        release_product_id=release_product_id,
        release_code=release.official_code if release else None,
        release_name=release.display_name if release else None,
        methodology_version=latest.methodology_version,
    )
    return latest, identity


def _catalogue(db: Session, point: MarketValuePoint):
    # The initial replay's digest is GLOBAL, even for a release point. Do not
    # narrow it to the requested release, or accept today's reassignment.
    rows = db.execute(
        select(CardPrint, CanonicalCard, ReleaseProduct)
        .options(
            load_only(
                CardPrint.id,
                CardPrint.canonical_card_id,
                CardPrint.release_product_id,
                CardPrint.official_asset_variant,
                CardPrint.official_rarity,
                CardPrint.treatment,
                CardPrint.image_url,
            ),
            load_only(
                CanonicalCard.id,
                CanonicalCard.card_code,
                CanonicalCard.name_en,
                CanonicalCard.name_jp,
            ),
            load_only(
                ReleaseProduct.id,
                ReleaseProduct.official_code,
                ReleaseProduct.display_name,
            ),
        )
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .join(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == "jp",
            CardPrint.release_product_id.is_not(None),
        )
        .order_by(CardPrint.id)
    ).all()
    revision = membership_revision(
        ActivePrintIdentity(p.id, p.release_product_id) for p, _, _ in rows
    )
    if revision != point.membership_revision:
        raise MarketValueIntegrityError("membership_revision_mismatch")
    selected = {
        p.id: (p, card, release)
        for p, card, release in rows
        if point.release_product_id is None
        or p.release_product_id == point.release_product_id
    }
    if len(selected) != point.total_physical_print_count:
        raise MarketValueIntegrityError("membership_revision_mismatch")
    return selected


def _snapshots(db: Session, dates: tuple[date, ...], catalogue):
    return db.scalars(
        select(MarketIndexSnapshot)
        .options(
            load_only(
                MarketIndexSnapshot.card_print_id,
                MarketIndexSnapshot.snapshot_date,
                MarketIndexSnapshot.index_value_jpy,
                MarketIndexSnapshot.index_version,
                MarketIndexSnapshot.source_semantics_version,
                MarketIndexSnapshot.calculated_at,
                MarketIndexSnapshot.provenance,
            )
        )
        .where(
            MarketIndexSnapshot.snapshot_date.in_(dates),
            MarketIndexSnapshot.card_print_id.in_(catalogue),
        )
        .order_by(MarketIndexSnapshot.snapshot_date, MarketIndexSnapshot.card_print_id)
    ).all()


def _day(point_date: date, snapshots, catalogue, revision: str) -> MarketValueDay:
    observations = []
    for row in snapshots:
        if row.snapshot_date != point_date:
            continue
        provenance = row.provenance if isinstance(row.provenance, dict) else {}
        observations.append(
            MarketValueObservation(
                card_print_id=row.card_print_id,
                value_jpy=row.index_value_jpy,
                index_version=row.index_version,
                source_semantics_version=row.source_semantics_version,
                contributors=eligible_contributor_set(provenance.get("source_values")),
                release_product_id=catalogue[row.card_print_id][0].release_product_id,
            )
        )
    return MarketValueDay(point_date, tuple(observations), len(catalogue), revision)


def _validate_step(point: MarketValuePoint, step: MonetaryStep, scope):
    decision = evaluate_market_value_publication(step, scope=scope)
    expected = {
        "prior_point_date": step.prior_date,
        "point_date": step.current_date,
        "step_days": step.step_days,
        "tracked_value_jpy": step.current_tracked.value_jpy,
        "priced_print_count": step.current_tracked.priced_print_count,
        "total_physical_print_count": step.current_tracked.total_physical_print_count,
        "prior_tracked_value_jpy": step.prior_tracked.value_jpy,
        "prior_priced_print_count": step.prior_tracked.priced_print_count,
        "prior_total_physical_print_count": step.prior_tracked.total_physical_print_count,
        "comparable_print_count": step.comparable_print_count,
        "prior_comparable_value_jpy": step.comparable_prior_value_jpy,
        "current_comparable_value_jpy": step.comparable_current_value_jpy,
        "step_ratio": step.ratio,
        "step_publication_eligible": decision.publishable,
        "publication_reasons": publication_reasons_text(decision.reasons),
        "prior_version_pairs": version_pairs_text(step.prior_version_pairs),
        "current_version_pairs": version_pairs_text(step.current_version_pairs),
        "membership_revision": step.current_membership_revision,
    }
    if (
        not decision.publishable
        or step.prior_membership_revision != point.membership_revision
        or any(getattr(point, key) != value for key, value in expected.items())
    ):
        raise MarketValueIntegrityError("persisted_step_mismatch")


def _reconcile_panel(step: MonetaryStep) -> Decimal:
    """Exact integer reconciliation, then bounded 50-digit Decimal rounding.

    Each contribution is independently rounded by A2. Its sum need not equal
    the independently rounded aggregate's last digit. Bound only that rounding
    error by the sum of half-ULPs at A2 precision, not a price/percent epsilon.
    No returned contribution is adjusted to force a visual total.
    """
    rows = step.contributions
    prior = step.comparable_prior_value_jpy
    delta = step.comparable_current_value_jpy - prior
    if (
        prior <= 0
        or len(rows) != step.comparable_print_count
        or len({row.card_print_id for row in rows}) != len(rows)
        or sum(row.prior_value_jpy for row in rows) != prior
        or sum(row.current_value_jpy for row in rows)
        != step.comparable_current_value_jpy
        or sum(row.delta_jpy for row in rows) != delta
        or any(
            row.delta_jpy != row.current_value_jpy - row.prior_value_jpy for row in rows
        )
    ):
        raise MarketValueIntegrityError("panel_reconciliation_failed")
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        basket_pct = Decimal(100 * delta) / Decimal(prior)
        if any(
            row.percentage_point_contribution
            != Decimal(100 * row.delta_jpy) / Decimal(prior)
            for row in rows
        ):
            raise MarketValueIntegrityError("panel_reconciliation_failed")
    with localcontext() as context:
        # Integer JPY inputs are BIGINT; this also leaves ample guard digits
        # to sum a catalogue's independently rounded 50-digit contributions.
        context.prec = 2 * CALCULATION_DECIMAL_PRECISION + len(str(len(rows))) + 20
        values = [row.percentage_point_contribution for row in rows]
        tolerance = sum(
            (
                Decimal(1).scaleb(value.adjusted() - CALCULATION_DECIMAL_PRECISION + 1)
                / 2
            )
            for value in [*values, basket_pct]
            if value
        )
        if abs(sum(values, Decimal(0)) - basket_pct) > tolerance:
            raise MarketValueIntegrityError("panel_reconciliation_failed")
    return basket_pct


def _identities(db: Session, ids: list[int], catalogue):
    # Enrich only the returned page, with one stored-image query. The shared
    # helper falls back to canonical artwork / null; unexpected DB errors
    # propagate, as on /prints, rather than fabricating identity or prices.
    images = get_display_images_for_prints(db, [catalogue[pid][0] for pid in ids])
    result = {}
    for pid in ids:
        p, card, release = catalogue[pid]
        result[pid] = dict(
            card_print_id=pid,
            canonical_card_id=card.id,
            card_code=card.card_code,
            name=card.name_en or card.name_jp,
            rarity=p.official_rarity,
            treatment=p.treatment,
            official_asset_variant=p.official_asset_variant,
            release_product_id=release.id,
            release_code=release.official_code,
            release_name=release.display_name,
            display_image=images.get(pid),
        )
    return result


def get_market_value_movers(
    db: Session,
    *,
    release_product_id: int | None = None,
    order: MarketValueMoverOrder = "gainers",
    limit: int = 10,
) -> MarketValueMoversOut:
    with db.no_autoflush:
        latest, identity = _selected_scope(db, release_product_id)
        point = db.scalar(
            select(MarketValuePoint)
            .where(
                *_scope(release_product_id),
                MarketValuePoint.point_date <= latest.point_date,
                MarketValuePoint.step_publication_eligible.is_(True),
            )
            .order_by(MarketValuePoint.point_date.desc())
            .limit(1)
        )
        if point is None:
            return MarketValueMoversOut(
                **identity,
                available=False,
                reason="no_published_daily_step",
                scope_as_of=latest.point_date,
                step_date=None,
                prior_date=None,
                panel=MarketValuePanelOut(),
                order=order,
                total_ranked=0,
                returned=0,
                truncated=False,
                movers=[],
            )
        if point.prior_point_date is None:
            raise MarketValueIntegrityError("persisted_step_mismatch")
        catalogue = _catalogue(db, point)
        snapshots = _snapshots(
            db, (point.prior_point_date, point.point_date), catalogue
        )
        scope = (
            MarketValueScope.release(release_product_id)
            if release_product_id
            else MarketValueScope.overall()
        )
        try:
            step = compute_monetary_step(
                _day(
                    point.prior_point_date,
                    snapshots,
                    catalogue,
                    point.membership_revision,
                ),
                _day(point.point_date, snapshots, catalogue, point.membership_revision),
                scope=scope,
            )
        except ValueError as exc:
            raise MarketValueIntegrityError("persisted_step_mismatch") from exc
        _validate_step(point, step, scope)
        basket_pct = _reconcile_panel(step)
        if order == "gainers":
            ranked = sorted(
                (r for r in step.contributions if r.delta_jpy > 0),
                key=lambda r: (r.return_fraction.copy_negate(), r.card_print_id),
            )
        elif order == "losers":
            ranked = sorted(
                (r for r in step.contributions if r.delta_jpy < 0),
                key=lambda r: (r.return_fraction, r.card_print_id),
            )
        else:
            ranked = sorted(
                (r for r in step.contributions if r.delta_jpy),
                key=lambda r: (-abs(r.delta_jpy), r.card_print_id),
            )
        page = ranked[:limit]
        identities = _identities(db, [r.card_print_id for r in page], catalogue)
        with localcontext() as context:
            context.prec = CALCULATION_DECIMAL_PRECISION
            movers = [
                MarketValueMoverOut(
                    **identities[row.card_print_id],
                    prior_value_jpy=row.prior_value_jpy,
                    current_value_jpy=row.current_value_jpy,
                    delta_jpy=row.delta_jpy,
                    move_fraction=row.return_fraction,
                    move_pct=row.return_fraction * 100,
                    percentage_point_contribution=row.percentage_point_contribution,
                    direction="up" if row.delta_jpy > 0 else "down",
                    rank=rank,
                )
                for rank, row in enumerate(page, 1)
            ]
        return MarketValueMoversOut(
            **identity,
            available=True,
            reason="publishable",
            scope_as_of=latest.point_date,
            step_date=point.point_date,
            prior_date=point.prior_point_date,
            panel=MarketValuePanelOut(
                comparable_print_count=step.comparable_print_count,
                prior_value_jpy=step.comparable_prior_value_jpy,
                current_value_jpy=step.comparable_current_value_jpy,
                basket_delta_jpy=step.comparable_current_value_jpy
                - step.comparable_prior_value_jpy,
                basket_move_pct=basket_pct,
            ),
            order=order,
            total_ranked=len(ranked),
            returned=len(page),
            truncated=len(page) < len(ranked),
            movers=movers,
        )


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def get_market_value_most_valuable(
    db: Session,
    *,
    release_product_id: int | None = None,
    limit: int = 10,
    offset: int = 0,
) -> MarketValueMostValuableOut:
    with db.no_autoflush:
        point, identity = _selected_scope(db, release_product_id)
        catalogue = _catalogue(db, point)
        rows = [
            r
            for r in _snapshots(db, (point.point_date,), catalogue)
            if r.index_value_jpy is not None and r.index_value_jpy > 0
        ]
        if (
            len(rows) != point.priced_print_count
            or (sum(r.index_value_jpy for r in rows) if rows else None)
            != point.tracked_value_jpy
        ):
            raise MarketValueIntegrityError("tracked_value_mismatch")
        times = {_utc(r.calculated_at) for r in rows}
        if len(times) > 1 or any(t.date() != point.point_date for t in times):
            raise MarketValueIntegrityError("mixed_valuation_batch")
        if (
            version_pairs_text(
                (r.index_version, r.source_semantics_version) for r in rows
            )
            != point.current_version_pairs
        ):
            raise MarketValueIntegrityError("snapshot_version_mismatch")
        ranked = sorted(rows, key=lambda r: (-r.index_value_jpy, r.card_print_id))
        page = ranked[offset : offset + limit]
        identities = _identities(db, [r.card_print_id for r in page], catalogue)
        return MarketValueMostValuableOut(
            **identity,
            as_of=point.point_date,
            calculated_at=next(iter(times), None),
            total_eligible=len(ranked),
            limit=limit,
            offset=offset,
            items=[
                MarketValueValuablePrintOut(
                    **identities[r.card_print_id],
                    value_jpy=r.index_value_jpy,
                    calculated_at=_utc(r.calculated_at),
                )
                for r in page
            ],
        )
