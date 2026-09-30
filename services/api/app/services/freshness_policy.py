"""Versioned current-price deadlines; pure and independent of source/grade."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, ClassVar, Iterable

POLICY_VERSION = "current-price-v1"
# Shared with the PostgreSQL selector and the offline capacity simulation.
LANE_CYCLE = (
    "high",
    "ordinary",
    "high",
    "discovery",
    "high",
    "ordinary",
    "high",
    "coverage",
)
UTCClock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FreshnessPolicy:
    # Changing targets requires a new policy version, never a capacity override.
    standard_target: ClassVar[timedelta] = timedelta(hours=24)
    high_interest_target: ClassVar[timedelta] = timedelta(hours=4)
    version: ClassVar[str] = POLICY_VERSION
    headroom: timedelta = timedelta(hours=1)

    def __post_init__(self) -> None:
        if not timedelta(0) < self.headroom < self.high_interest_target:
            raise ValueError("headroom must be positive and shorter than four hours")
        if self.headroom.total_seconds() != int(self.headroom.total_seconds()):
            raise ValueError("headroom must be a whole number of seconds")

    def target(self, *, high_interest: bool) -> timedelta:
        return self.high_interest_target if high_interest else self.standard_target

    def expiry(self, observed_at: datetime, *, high_interest: bool) -> datetime:
        return require_utc(observed_at) + self.target(high_interest=high_interest)

    def next_due(
        self,
        observed_at: datetime | None,
        *,
        high_interest: bool,
        clock: UTCClock = utc_now,
    ) -> datetime:
        if observed_at is None:
            return require_utc(clock())
        return self.expiry(observed_at, high_interest=high_interest) - self.headroom

    def verdict(
        self,
        observed_at: datetime | None,
        *,
        high_interest: bool,
        historical: bool = False,
        clock: UTCClock = utc_now,
    ) -> str:
        now = require_utc(clock())
        if historical:
            return "historical"
        if observed_at is None or require_utc(observed_at) > now:
            return "unknown"
        return (
            "fresh"
            if now < self.expiry(observed_at, high_interest=high_interest)
            else "stale"
        )

    def is_fresh(
        self,
        observed_at: datetime | None,
        *,
        high_interest: bool,
        clock: UTCClock = utc_now,
    ) -> bool:
        return (
            self.verdict(observed_at, high_interest=high_interest, clock=clock)
            == "fresh"
        )


@dataclass(frozen=True)
class DerivedFreshness:
    status: str  # fresh, stale, unknown, historical
    oldest_input_at: datetime | None
    contributing_count: int
    expected_count: int

    @property
    def coverage_complete(self) -> bool:
        return self.contributing_count == self.expected_count


def derived_freshness(
    contributing_observed_at: Iterable[datetime | None],
    *,
    expected_count: int,
    high_interest: bool,
    historical: bool = False,
    policy: FreshnessPolicy = FreshnessPolicy(),
    clock: UTCClock = utc_now,
) -> DerivedFreshness:
    """Only actual contributing observations count; calculation time is irrelevant.

    None means unknown lineage for an actual contributor. Missing contributors
    belong in expected_count and affect coverage independently of freshness.
    """
    inputs = list(contributing_observed_at)
    if expected_count < len(inputs) or expected_count < 0:
        raise ValueError("expected_count cannot be smaller than contributors")
    now = require_utc(clock())
    known = [require_utc(t) for t in inputs if t is not None]
    oldest = min(known) if known else None
    if historical:
        status = "historical"
    elif len(known) != len(inputs) or not known or any(t > now for t in known):
        status = "unknown"
    else:
        status = policy.verdict(oldest, high_interest=high_interest, clock=lambda: now)
    return DerivedFreshness(
        status, None if status == "unknown" else oldest, len(inputs), expected_count
    )
