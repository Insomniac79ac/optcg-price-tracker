"""Public daily monetary attribution and snapshot-aligned exact-print rankings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import DisplayImageOut

MarketValueMoverOrder = Literal["gainers", "losers", "impact"]
IntegrityReason = Literal[
    "membership_revision_mismatch",
    "persisted_step_mismatch",
    "panel_reconciliation_failed",
    "tracked_value_mismatch",
    "mixed_valuation_batch",
    "snapshot_version_mismatch",
]


class MarketValueIntegrityDetail(BaseModel):
    code: Literal["market_value_integrity_mismatch"] = "market_value_integrity_mismatch"
    reason: IntegrityReason


class MarketValueRankingErrorOut(BaseModel):
    detail: str | MarketValueIntegrityDetail


class MarketValueRankingScopeOut(BaseModel):
    scope_kind: Literal["overall", "release"]
    release_product_id: int | None
    release_code: str | None
    release_name: str | None
    methodology_version: int


class MarketValuePrintIdentityOut(BaseModel):
    card_print_id: int
    canonical_card_id: int
    card_code: str
    name: str
    rarity: str | None = Field(
        description="Exact print's official rarity; null if unknown."
    )
    treatment: str | None
    official_asset_variant: str
    release_product_id: int
    release_code: str | None
    release_name: str
    display_image: DisplayImageOut | None


class MarketValueMoverOut(MarketValuePrintIdentityOut):
    prior_value_jpy: int
    current_value_jpy: int
    delta_jpy: int = Field(
        description="Signed basket change in JPY, not CPI index points."
    )
    move_fraction: Decimal
    move_pct: Decimal = Field(
        description="100 * (current / prior - 1), Decimal string."
    )
    percentage_point_contribution: Decimal = Field(
        description="Signed daily impact: 100 * delta_jpy / full comparable panel prior JPY. Decimal string, no CPI cap or equal weighting."
    )
    direction: Literal["up", "down", "flat"]
    rank: int = Field(
        description="Deterministic full qualifying population rank before truncation."
    )


class MarketValuePanelOut(BaseModel):
    comparable_print_count: int | None = None
    prior_value_jpy: int | None = None
    current_value_jpy: int | None = None
    basket_delta_jpy: int | None = None
    basket_move_pct: Decimal | None = Field(
        default=None,
        description="100 * (Q - P) / P for one published daily comparable panel. Null when unavailable, never fabricated zero.",
    )


class MarketValueMoversOut(MarketValueRankingScopeOut):
    available: bool
    reason: Literal["publishable", "no_published_daily_step"]
    scope_as_of: date = Field(
        description="Latest persisted scope date, not a live quote date."
    )
    step_date: date | None = Field(
        description="Newest published daily step; may predate scope_as_of."
    )
    prior_date: date | None
    panel: MarketValuePanelOut
    order: MarketValueMoverOrder
    total_ranked: int
    returned: int
    truncated: bool
    movers: list[MarketValueMoverOut]


class MarketValueValuablePrintOut(MarketValuePrintIdentityOut):
    value_jpy: int = Field(
        description="Positive immutable snapshot JPY value at response as_of."
    )
    calculated_at: datetime


class MarketValueMostValuableOut(MarketValueRankingScopeOut):
    as_of: date = Field(
        description="Persisted headline valuation date. No newer live prices are used."
    )
    calculated_at: datetime | None = Field(
        description="One coherent UTC snapshot calculation instant for the entire eligible basket; null only if no priced prints."
    )
    total_eligible: int
    limit: int
    offset: int
    items: list[MarketValueValuablePrintOut]
