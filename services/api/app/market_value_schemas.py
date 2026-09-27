"""Public persisted Market Value contracts; Decimal values serialize as strings."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.services.market_value import PublicationReason

MarketValueWindow = Literal["7d", "30d", "all"]
MovementReason = PublicationReason | Literal["segment_break", "invalid_chain_evidence"]


class MarketValueTrackedOut(BaseModel):
    """Literal partial JPY basket sum, independent of coverage-neutral movement."""

    value_jpy: int | None = Field(
        description="Literal sum of priced physical printings at as_of. Null when no prices; not market capitalization."
    )
    priced_print_count: int
    total_physical_print_count: int
    physical_coverage_pct: Decimal | None = Field(
        description="100 * priced / physical count; null for an empty population. Decimal string."
    )
    is_partial: bool = Field(
        description="True when some physical printings are unpriced."
    )


class MarketValueMovementSummaryOut(BaseModel):
    available: bool
    pct: Decimal | None = Field(
        description="Coverage-neutral persisted price movement in percent, as a Decimal string. Unavailable is null, never zero."
    )
    reason: MovementReason = Field(
        description="Stable publication or unavailability reason."
    )


class MarketValueMovementOut(MarketValueMovementSummaryOut):
    window: MarketValueWindow
    from_date: date
    to_date: date
    fraction: Decimal | None = Field(
        description="Coverage-neutral return fraction from persisted comparable P/Q evidence; null unless every daily step is valid."
    )


class MarketValueSeriesPointOut(BaseModel):
    date: date
    tracked_value_jpy: int | None = Field(
        description="Literal partial basket sum for this date; NOT a coverage-neutral historical value."
    )
    priced_print_count: int
    total_physical_print_count: int
    performance_pct: Decimal | None = Field(
        description="100 * (persisted performance_factor / first valid visible factor - 1). Decimal string; null on failed steps and outside the anchor's continuous segment."
    )
    step_publication_eligible: bool | None = Field(
        description="Persisted daily-step publication decision; null for the initial point, false for an unavailable step."
    )
    publication_reason: MovementReason | Literal["initial_point"]


class MarketValueOut(BaseModel):
    scope_kind: Literal["overall", "release"]
    release_product_id: int | None
    release_code: str | None
    release_name: str | None = Field(
        description="Authoritative ReleaseProduct display name; null for Overall."
    )
    methodology_version: int
    as_of: date = Field(
        description="Latest persisted UTC snapshot date in this scope. All windows end here; this is not a live price timestamp."
    )
    tracked_value: MarketValueTrackedOut
    movement: MarketValueMovementOut
    series: list[MarketValueSeriesPointOut]


class MarketValueReleaseOut(BaseModel):
    release_product_id: int
    release_code: str
    release_name: str
    as_of: date = Field(
        description="Latest persisted UTC snapshot date for this release, not today's live valuation."
    )
    tracked_value: MarketValueTrackedOut
    seven_day: MarketValueMovementSummaryOut
    thirty_day: MarketValueMovementSummaryOut
    methodology_version: int


class MarketValueReleasesOut(BaseModel):
    items: list[MarketValueReleaseOut] = Field(
        description="Every active coded JP release in the persisted read model, including sparse/no-price releases. Active means positive persisted physical count."
    )
    ordering_basis: Literal["released_on_desc_then_deterministic_fallback"]


class MarketValueErrorOut(BaseModel):
    detail: str
