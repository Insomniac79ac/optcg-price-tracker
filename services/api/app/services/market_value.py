"""Pure monetary basket engine for Atlas Market Value methodology v1.

The methodology authority is:

* ``docs/reports/public-ux-market-value-a0-2026-09-26.md``
* ``docs/reports/public-ux-market-value-a1-2026-09-26.md``

This module deliberately has no ORM, database session, clock, HTTP, job, or
source-fetch dependency.  It answers three separate questions:

1. What is the literal current JPY sum of the priced physical prints?
2. What changed among strictly comparable physical prints on two adjacent
   UTC dates?
3. Does that step, or every step in a 7D/30D window, pass the frozen
   publication gate?

Those questions stay separate so a new price can increase tracked value
without being mislabeled as appreciation, and a lost price can reduce the
tracked sum without being mislabeled as market decline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable

METHODOLOGY_VERSION = 1
SUPPORTED_WINDOW_DAYS = (7, 30)

RELEASE_LARGE_MIN_PHYSICAL = 30
RELEASE_LARGE_MIN_COMPARABLE = 30
RELEASE_LARGE_MIN_PHYSICAL_FRACTION = Decimal("0.40")
RELEASE_SMALL_MIN_PHYSICAL = 10
RELEASE_SMALL_MIN_PHYSICAL_FRACTION = Decimal("0.80")

OVERALL_MIN_COMPARABLE = 300
OVERALL_MIN_PHYSICAL_FRACTION = Decimal("0.10")
MIN_COMPARABLE_VALUE_FRACTION = Decimal("0.80")

ContributorKey = tuple[str, str]


class ScopeKind(str, Enum):
    OVERALL = "overall"
    RELEASE = "release_product"


class PublicationReason(str, Enum):
    PUBLISHABLE = "publishable"
    INSUFFICIENT_WINDOW_CONTINUITY = "insufficient_window_continuity"
    MEMBERSHIP_REVISION_CHANGED = "membership_revision_changed"
    MIXED_VERSION_DAY = "mixed_version_day"
    INDEX_VERSION_CHANGED = "index_version_changed"
    SOURCE_SEMANTICS_VERSION_CHANGED = "source_semantics_version_changed"
    INSUFFICIENT_COMPARABLE_PRINTS = "insufficient_comparable_prints"
    INSUFFICIENT_PHYSICAL_COVERAGE = "insufficient_physical_coverage"
    INSUFFICIENT_COMPARABLE_VALUE_COVERAGE = (
        "insufficient_comparable_value_coverage"
    )
    NON_POSITIVE_COMPARABLE_VALUE = "non_positive_comparable_value"


class TrackedValueStatus(str, Enum):
    NO_PRICES = "no_prices"
    PARTIAL = "partial"
    COMPLETE = "complete"


@dataclass(frozen=True)
class MarketValueScope:
    kind: ScopeKind
    release_product_id: int | None = None

    def __post_init__(self) -> None:
        if self.kind is ScopeKind.OVERALL and self.release_product_id is not None:
            raise ValueError("overall scope cannot carry a release_product_id")
        if self.kind is ScopeKind.RELEASE and (
            self.release_product_id is None or self.release_product_id <= 0
        ):
            raise ValueError("release scope requires a positive release_product_id")

    @classmethod
    def overall(cls) -> MarketValueScope:
        return cls(ScopeKind.OVERALL)

    @classmethod
    def release(cls, release_product_id: int) -> MarketValueScope:
        return cls(ScopeKind.RELEASE, release_product_id)


@dataclass(frozen=True)
class MarketValueObservation:
    """One archived or current physical-print valuation.

    ``contributors`` is the nonempty set of ``(source, reference_type)``
    identities that actually contributed to ``value_jpy``.  ``None`` means
    the archive cannot prove contributor identity.  An empty set means the
    payload proves that nothing contributed.  Neither is comparable.
    """

    card_print_id: int
    value_jpy: int | None
    index_version: int
    source_semantics_version: int
    contributors: frozenset[ContributorKey] | None
    release_product_id: int | None = None

    def __post_init__(self) -> None:
        if self.index_version <= 0:
            raise ValueError("index_version must be positive")
        if self.source_semantics_version <= 0:
            raise ValueError("source_semantics_version must be positive")
        if self.card_print_id <= 0:
            raise ValueError("card_print_id must be positive")
        if self.release_product_id is not None and self.release_product_id <= 0:
            raise ValueError("release_product_id must be positive when present")
        if self.contributors is not None:
            for contributor in self.contributors:
                if (
                    len(contributor) != 2
                    or not contributor[0]
                    or not contributor[1]
                ):
                    raise ValueError("contributors require nonempty source/type pairs")
            # A frozen dataclass is only genuinely immutable when its nested
            # collection is immutable too.  Normalize set-like callers to the
            # contract type at the boundary.
            object.__setattr__(self, "contributors", frozenset(self.contributors))

    @property
    def has_usable_value(self) -> bool:
        return self.value_jpy is not None and self.value_jpy > 0


@dataclass(frozen=True)
class MarketValueDay:
    point_date: date
    observations: tuple[MarketValueObservation, ...]
    total_physical_print_count: int
    membership_revision: str

    def __post_init__(self) -> None:
        if self.total_physical_print_count < 0:
            raise ValueError("total_physical_print_count cannot be negative")
        if not self.membership_revision.strip():
            raise ValueError("membership_revision cannot be blank")
        ordered = tuple(
            sorted(self.observations, key=lambda observation: observation.card_print_id)
        )
        object.__setattr__(self, "observations", ordered)
        print_ids = [observation.card_print_id for observation in ordered]
        if len(print_ids) != len(set(print_ids)):
            raise ValueError("a MarketValueDay cannot contain duplicate card_print_id rows")
        if len(print_ids) > self.total_physical_print_count:
            raise ValueError("observations cannot exceed the physical-print population")


@dataclass(frozen=True)
class TrackedValueResult:
    value_jpy: int | None
    priced_print_count: int
    total_physical_print_count: int
    physical_coverage_fraction: Decimal | None
    status: TrackedValueStatus
    is_partial: bool
    headline_eligible: bool

    @property
    def physical_coverage_pct(self) -> Decimal | None:
        if self.physical_coverage_fraction is None:
            return None
        return self.physical_coverage_fraction * Decimal(100)


@dataclass(frozen=True)
class MarketValueContribution:
    card_print_id: int
    prior_value_jpy: int
    current_value_jpy: int
    delta_jpy: int
    return_fraction: Decimal
    percentage_point_contribution: Decimal


@dataclass(frozen=True)
class MonetaryStep:
    prior_date: date
    current_date: date
    step_days: int
    prior_tracked: TrackedValueResult
    current_tracked: TrackedValueResult
    comparable_print_count: int
    comparable_prior_value_jpy: int
    comparable_current_value_jpy: int
    comparable_prior_value_fraction: Decimal | None
    comparable_current_value_fraction: Decimal | None
    ratio: Decimal | None
    return_fraction: Decimal | None
    contributions: tuple[MarketValueContribution, ...]
    exclusion_counts: tuple[tuple[str, int], ...]
    prior_version_pairs: frozenset[tuple[int, int]]
    current_version_pairs: frozenset[tuple[int, int]]
    prior_membership_revision: str
    current_membership_revision: str

    @property
    def return_pct(self) -> Decimal | None:
        if self.return_fraction is None:
            return None
        return self.return_fraction * Decimal(100)


@dataclass(frozen=True)
class PublicationDecision:
    publishable: bool
    reasons: tuple[PublicationReason, ...]
    required_comparable_prints_prior: int
    required_comparable_prints_current: int
    required_physical_fraction_prior: Decimal
    required_physical_fraction_current: Decimal
    required_comparable_value_fraction: Decimal

    @property
    def primary_reason(self) -> PublicationReason:
        return self.reasons[0]


@dataclass(frozen=True)
class MarketValueWindow:
    window_days: int
    from_date: date
    to_date: date
    available: bool
    movement_fraction: Decimal | None
    steps: tuple[MonetaryStep, ...]
    decisions: tuple[PublicationDecision, ...]
    reasons: tuple[PublicationReason, ...]
    min_comparable_print_count: int | None
    min_physical_coverage_fraction: Decimal | None
    min_comparable_value_fraction: Decimal | None

    @property
    def movement_pct(self) -> Decimal | None:
        if self.movement_fraction is None:
            return None
        return self.movement_fraction * Decimal(100)

    @property
    def primary_reason(self) -> PublicationReason:
        return self.reasons[0]


@dataclass(frozen=True)
class MarketValueReplayPoint:
    point_date: date
    tracked: TrackedValueResult
    segment_number: int
    performance_factor: Decimal
    step: MonetaryStep | None
    publication: PublicationDecision | None
    break_reason: PublicationReason | None


def _scoped_observations(
    day: MarketValueDay, scope: MarketValueScope
) -> tuple[MarketValueObservation, ...]:
    if scope.kind is ScopeKind.OVERALL:
        selected = day.observations
    else:
        selected = tuple(
            observation
            for observation in day.observations
            if observation.release_product_id == scope.release_product_id
        )
    return tuple(sorted(selected, key=lambda observation: observation.card_print_id))


def _release_requirements(total_physical_print_count: int) -> tuple[int, Decimal]:
    if total_physical_print_count >= RELEASE_LARGE_MIN_PHYSICAL:
        return (
            RELEASE_LARGE_MIN_COMPARABLE,
            RELEASE_LARGE_MIN_PHYSICAL_FRACTION,
        )
    # ceil(80% of N), without binary float.  N < 10 remains ineligible because
    # max(10, ...) cannot be reached by a population smaller than ten.
    eighty_percent_ceiling = (4 * total_physical_print_count + 4) // 5
    return (
        max(RELEASE_SMALL_MIN_PHYSICAL, eighty_percent_ceiling),
        RELEASE_SMALL_MIN_PHYSICAL_FRACTION,
    )


def _publication_requirements(
    scope: MarketValueScope, total_physical_print_count: int
) -> tuple[int, Decimal]:
    if scope.kind is ScopeKind.OVERALL:
        return OVERALL_MIN_COMPARABLE, OVERALL_MIN_PHYSICAL_FRACTION
    return _release_requirements(total_physical_print_count)


def current_tracked_value(
    observations: Iterable[MarketValueObservation],
    *,
    total_physical_print_count: int,
    scope: MarketValueScope,
) -> TrackedValueResult:
    """Literal JPY sum, without chain linking or completeness claims."""
    if total_physical_print_count < 0:
        raise ValueError("total_physical_print_count cannot be negative")

    ordered = sorted(observations, key=lambda observation: observation.card_print_id)
    print_ids = [observation.card_print_id for observation in ordered]
    if len(print_ids) != len(set(print_ids)):
        raise ValueError("tracked value cannot contain duplicate card_print_id rows")
    if len(print_ids) > total_physical_print_count:
        raise ValueError("observations cannot exceed the physical-print population")
    usable = [observation for observation in ordered if observation.has_usable_value]
    priced_count = len(usable)
    value_jpy = sum(observation.value_jpy for observation in usable) if usable else None
    coverage = (
        Decimal(priced_count) / Decimal(total_physical_print_count)
        if total_physical_print_count > 0
        else None
    )
    if priced_count == 0:
        status = TrackedValueStatus.NO_PRICES
    elif priced_count == total_physical_print_count:
        status = TrackedValueStatus.COMPLETE
    else:
        status = TrackedValueStatus.PARTIAL

    required_count, required_fraction = _publication_requirements(
        scope, total_physical_print_count
    )
    headline_eligible = priced_count >= required_count and (
        coverage is not None and coverage >= required_fraction
    )
    # A tracked Overall headline is allowed with any nonempty panel, but it
    # remains explicitly partial and must carry its coverage.  The stronger
    # Overall threshold governs movement, not whether the literal sum exists.
    if scope.kind is ScopeKind.OVERALL:
        headline_eligible = priced_count > 0

    return TrackedValueResult(
        value_jpy=value_jpy,
        priced_print_count=priced_count,
        total_physical_print_count=total_physical_print_count,
        physical_coverage_fraction=coverage,
        status=status,
        is_partial=priced_count < total_physical_print_count,
        headline_eligible=headline_eligible,
    )


def _observation_map(
    day: MarketValueDay, scope: MarketValueScope
) -> dict[int, MarketValueObservation]:
    return {
        observation.card_print_id: observation
        for observation in _scoped_observations(day, scope)
    }


def _version_pairs(
    observations: Iterable[MarketValueObservation],
) -> frozenset[tuple[int, int]]:
    return frozenset(
        (observation.index_version, observation.source_semantics_version)
        for observation in observations
        if observation.has_usable_value
    )


def _comparability_reason(
    prior: MarketValueObservation | None,
    current: MarketValueObservation | None,
    *,
    scope: MarketValueScope,
) -> str | None:
    if prior is None:
        return "entrant"
    if current is None:
        return "leaver"
    if not prior.has_usable_value and current.has_usable_value:
        return "entrant"
    if prior.has_usable_value and not current.has_usable_value:
        return "leaver"
    if not prior.has_usable_value or not current.has_usable_value:
        return "unusable_value"
    if (
        scope.kind is ScopeKind.RELEASE
        and prior.release_product_id != current.release_product_id
    ):
        return "release_membership_changed"
    if prior.index_version != current.index_version:
        return "index_version_changed"
    if prior.source_semantics_version != current.source_semantics_version:
        return "source_semantics_version_changed"
    if not prior.contributors or not current.contributors:
        return "contributor_set_unavailable"
    if prior.contributors != current.contributors:
        return "contributor_set_changed"
    return None


def compute_monetary_step(
    prior: MarketValueDay,
    current: MarketValueDay,
    *,
    scope: MarketValueScope,
) -> MonetaryStep:
    """Compute ``P``, ``Q``, ``R=Q/P`` and per-print impact.

    Publication eligibility is intentionally evaluated by
    :func:`evaluate_market_value_publication`, not here.
    """
    prior_rows = _observation_map(prior, scope)
    current_rows = _observation_map(current, scope)
    prior_tracked = current_tracked_value(
        prior_rows.values(),
        total_physical_print_count=prior.total_physical_print_count,
        scope=scope,
    )
    current_tracked = current_tracked_value(
        current_rows.values(),
        total_physical_print_count=current.total_physical_print_count,
        scope=scope,
    )

    comparable: list[tuple[MarketValueObservation, MarketValueObservation]] = []
    exclusions: dict[str, int] = {}
    for print_id in sorted(set(prior_rows) | set(current_rows)):
        before = prior_rows.get(print_id)
        after = current_rows.get(print_id)
        reason = _comparability_reason(before, after, scope=scope)
        if reason is not None:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            continue
        assert before is not None and after is not None
        comparable.append((before, after))

    comparable_prior = sum(row.value_jpy for row, _ in comparable)
    comparable_current = sum(row.value_jpy for _, row in comparable)
    ratio = (
        Decimal(comparable_current) / Decimal(comparable_prior)
        if comparable_prior > 0
        else None
    )
    return_fraction = ratio - Decimal(1) if ratio is not None else None

    contributions = tuple(
        MarketValueContribution(
            card_print_id=before.card_print_id,
            prior_value_jpy=before.value_jpy,
            current_value_jpy=after.value_jpy,
            delta_jpy=after.value_jpy - before.value_jpy,
            return_fraction=(Decimal(after.value_jpy) / Decimal(before.value_jpy))
            - Decimal(1),
            percentage_point_contribution=(
                Decimal(100)
                * Decimal(after.value_jpy - before.value_jpy)
                / Decimal(comparable_prior)
            ),
        )
        for before, after in comparable
    ) if comparable_prior > 0 else ()

    prior_sum = prior_tracked.value_jpy
    current_sum = current_tracked.value_jpy
    return MonetaryStep(
        prior_date=prior.point_date,
        current_date=current.point_date,
        step_days=(current.point_date - prior.point_date).days,
        prior_tracked=prior_tracked,
        current_tracked=current_tracked,
        comparable_print_count=len(comparable),
        comparable_prior_value_jpy=comparable_prior,
        comparable_current_value_jpy=comparable_current,
        comparable_prior_value_fraction=(
            Decimal(comparable_prior) / Decimal(prior_sum)
            if prior_sum is not None and prior_sum > 0
            else None
        ),
        comparable_current_value_fraction=(
            Decimal(comparable_current) / Decimal(current_sum)
            if current_sum is not None and current_sum > 0
            else None
        ),
        ratio=ratio,
        return_fraction=return_fraction,
        contributions=contributions,
        exclusion_counts=tuple(sorted(exclusions.items())),
        prior_version_pairs=_version_pairs(prior_rows.values()),
        current_version_pairs=_version_pairs(current_rows.values()),
        prior_membership_revision=prior.membership_revision,
        current_membership_revision=current.membership_revision,
    )


def _append_once(
    reasons: list[PublicationReason], reason: PublicationReason
) -> None:
    if reason not in reasons:
        reasons.append(reason)


def evaluate_market_value_publication(
    step: MonetaryStep,
    *,
    scope: MarketValueScope,
) -> PublicationDecision:
    """Apply A1's publication gate without changing step arithmetic."""
    prior_required_count, prior_required_fraction = _publication_requirements(
        scope, step.prior_tracked.total_physical_print_count
    )
    current_required_count, current_required_fraction = _publication_requirements(
        scope, step.current_tracked.total_physical_print_count
    )
    reasons: list[PublicationReason] = []

    if step.step_days != 1:
        _append_once(reasons, PublicationReason.INSUFFICIENT_WINDOW_CONTINUITY)
    # A release assignment correction changes that release's basket and must
    # start a new segment.  The same correction does not change Overall
    # physical-print identity, so Overall remains comparable when its panel
    # passes every other guard.  Callers supply the membership revision for
    # the selected scope (active/verified identity for Overall; that identity
    # plus release assignment for a release).
    if (
        scope.kind is ScopeKind.RELEASE
        and step.prior_membership_revision != step.current_membership_revision
    ):
        _append_once(reasons, PublicationReason.MEMBERSHIP_REVISION_CHANGED)

    if len(step.prior_version_pairs) > 1 or len(step.current_version_pairs) > 1:
        _append_once(reasons, PublicationReason.MIXED_VERSION_DAY)
    elif len(step.prior_version_pairs) == 1 and len(step.current_version_pairs) == 1:
        prior_version = next(iter(step.prior_version_pairs))
        current_version = next(iter(step.current_version_pairs))
        if prior_version[0] != current_version[0]:
            _append_once(reasons, PublicationReason.INDEX_VERSION_CHANGED)
        if prior_version[1] != current_version[1]:
            _append_once(
                reasons, PublicationReason.SOURCE_SEMANTICS_VERSION_CHANGED
            )

    if step.comparable_prior_value_jpy <= 0 or step.ratio is None:
        _append_once(reasons, PublicationReason.NON_POSITIVE_COMPARABLE_VALUE)
    if step.comparable_print_count < max(
        prior_required_count, current_required_count
    ):
        _append_once(reasons, PublicationReason.INSUFFICIENT_COMPARABLE_PRINTS)

    prior_total = step.prior_tracked.total_physical_print_count
    current_total = step.current_tracked.total_physical_print_count
    prior_physical_fraction = (
        Decimal(step.comparable_print_count) / Decimal(prior_total)
        if prior_total > 0
        else None
    )
    current_physical_fraction = (
        Decimal(step.comparable_print_count) / Decimal(current_total)
        if current_total > 0
        else None
    )
    if (
        prior_physical_fraction is None
        or current_physical_fraction is None
        or prior_physical_fraction < prior_required_fraction
        or current_physical_fraction < current_required_fraction
    ):
        _append_once(reasons, PublicationReason.INSUFFICIENT_PHYSICAL_COVERAGE)

    if (
        step.comparable_prior_value_fraction is None
        or step.comparable_current_value_fraction is None
        or step.comparable_prior_value_fraction < MIN_COMPARABLE_VALUE_FRACTION
        or step.comparable_current_value_fraction < MIN_COMPARABLE_VALUE_FRACTION
    ):
        _append_once(
            reasons, PublicationReason.INSUFFICIENT_COMPARABLE_VALUE_COVERAGE
        )

    if not reasons:
        reasons.append(PublicationReason.PUBLISHABLE)
    return PublicationDecision(
        publishable=reasons == [PublicationReason.PUBLISHABLE],
        reasons=tuple(reasons),
        required_comparable_prints_prior=prior_required_count,
        required_comparable_prints_current=current_required_count,
        required_physical_fraction_prior=prior_required_fraction,
        required_physical_fraction_current=current_required_fraction,
        required_comparable_value_fraction=MIN_COMPARABLE_VALUE_FRACTION,
    )


def _minimum_decimal(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def evaluate_market_value_window(
    days: Iterable[MarketValueDay],
    *,
    scope: MarketValueScope,
    window_days: int,
    end_date: date | None = None,
) -> MarketValueWindow:
    """Evaluate every daily step in an exact 7D or 30D UTC window."""
    if window_days not in SUPPORTED_WINDOW_DAYS:
        raise ValueError(f"window_days must be one of {SUPPORTED_WINDOW_DAYS}")
    ordered = sorted(days, key=lambda day: day.point_date)
    if not ordered and end_date is None:
        raise ValueError("end_date is required when no days are supplied")
    by_date = {day.point_date: day for day in ordered}
    if len(by_date) != len(ordered):
        raise ValueError("market-value history cannot contain duplicate dates")

    resolved_end = end_date or ordered[-1].point_date
    resolved_start = resolved_end - timedelta(days=window_days)
    expected_dates = [
        resolved_start + timedelta(days=offset)
        for offset in range(window_days + 1)
    ]
    if any(day not in by_date for day in expected_dates):
        return MarketValueWindow(
            window_days=window_days,
            from_date=resolved_start,
            to_date=resolved_end,
            available=False,
            movement_fraction=None,
            steps=(),
            decisions=(),
            reasons=(PublicationReason.INSUFFICIENT_WINDOW_CONTINUITY,),
            min_comparable_print_count=None,
            min_physical_coverage_fraction=None,
            min_comparable_value_fraction=None,
        )

    steps = tuple(
        compute_monetary_step(
            by_date[expected_dates[offset - 1]],
            by_date[expected_dates[offset]],
            scope=scope,
        )
        for offset in range(1, len(expected_dates))
    )
    decisions = tuple(
        evaluate_market_value_publication(step, scope=scope) for step in steps
    )
    reasons: list[PublicationReason] = []
    for decision in decisions:
        if decision.publishable:
            continue
        for reason in decision.reasons:
            _append_once(reasons, reason)

    movement = None
    if not reasons:
        factor = Decimal(1)
        for step in steps:
            assert step.ratio is not None
            factor *= step.ratio
        movement = factor - Decimal(1)
        reasons.append(PublicationReason.PUBLISHABLE)

    physical_fractions: list[Decimal | None] = []
    value_fractions: list[Decimal | None] = []
    for step in steps:
        for tracked in (step.prior_tracked, step.current_tracked):
            total = tracked.total_physical_print_count
            physical_fractions.append(
                Decimal(step.comparable_print_count) / Decimal(total)
                if total > 0
                else None
            )
        value_fractions.extend(
            (
                step.comparable_prior_value_fraction,
                step.comparable_current_value_fraction,
            )
        )
    return MarketValueWindow(
        window_days=window_days,
        from_date=resolved_start,
        to_date=resolved_end,
        available=movement is not None,
        movement_fraction=movement,
        steps=steps,
        decisions=decisions,
        reasons=tuple(reasons),
        min_comparable_print_count=min(
            (step.comparable_print_count for step in steps), default=None
        ),
        min_physical_coverage_fraction=_minimum_decimal(physical_fractions),
        min_comparable_value_fraction=_minimum_decimal(value_fractions),
    )


def replay_market_value(
    days: Iterable[MarketValueDay], *, scope: MarketValueScope
) -> tuple[MarketValueReplayPoint, ...]:
    """Build deterministic in-memory segments; never persist or fill a date."""
    ordered = sorted(days, key=lambda day: day.point_date)
    if len({day.point_date for day in ordered}) != len(ordered):
        raise ValueError("market-value history cannot contain duplicate dates")
    points: list[MarketValueReplayPoint] = []
    segment = 0
    factor = Decimal(1)
    for index, day in enumerate(ordered):
        tracked = current_tracked_value(
            _scoped_observations(day, scope),
            total_physical_print_count=day.total_physical_print_count,
            scope=scope,
        )
        if index == 0:
            points.append(
                MarketValueReplayPoint(
                    point_date=day.point_date,
                    tracked=tracked,
                    segment_number=segment,
                    performance_factor=factor,
                    step=None,
                    publication=None,
                    break_reason=None,
                )
            )
            continue

        step = compute_monetary_step(ordered[index - 1], day, scope=scope)
        publication = evaluate_market_value_publication(step, scope=scope)
        if publication.publishable:
            assert step.ratio is not None
            factor *= step.ratio
            break_reason = None
        else:
            segment += 1
            factor = Decimal(1)
            break_reason = publication.primary_reason
        points.append(
            MarketValueReplayPoint(
                point_date=day.point_date,
                tracked=tracked,
                segment_number=segment,
                performance_factor=factor,
                step=step,
                publication=publication,
                break_reason=break_reason,
            )
        )
    return tuple(points)


__all__ = [
    "METHODOLOGY_VERSION",
    "MIN_COMPARABLE_VALUE_FRACTION",
    "MarketValueContribution",
    "MarketValueDay",
    "MarketValueObservation",
    "MarketValueReplayPoint",
    "MarketValueScope",
    "MarketValueWindow",
    "MonetaryStep",
    "PublicationDecision",
    "PublicationReason",
    "ScopeKind",
    "TrackedValueResult",
    "TrackedValueStatus",
    "compute_monetary_step",
    "current_tracked_value",
    "evaluate_market_value_publication",
    "evaluate_market_value_window",
    "replay_market_value",
]
