from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    image_url: str | None
    created_at: datetime
    updated_at: datetime


class PriceObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_id: int
    source_id: int
    source: str
    observed_at: datetime
    price_type: str
    price_jpy: int
    condition_label: str | None
    stock_status: str | None
    listing_count: int | None
    raw_snapshot_id: int | None


class SnkrdunkCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discovery_run_id: int | None
    source_url: str
    title: str | None
    price_jpy: int | None
    image_url: str | None
    listing_count: int | None
    condition_label: str | None
    normalized_title: str | None
    detected_card_code: str | None
    detected_set_code: str | None
    detected_rarity: str | None
    detected_variant: str | None
    match_status: str
    matched_card_id: int | None
    match_confidence: float | None
    created_at: datetime
    updated_at: datetime
    matched_card: CardOut | None = None


class SnkrdunkCandidateListOut(BaseModel):
    items: list[SnkrdunkCandidateOut]
    total: int
    limit: int
    offset: int


class SnkrdunkCandidateMatchIn(BaseModel):
    card_id: int
    manual_verified: bool = True


class MarketPriceOut(BaseModel):
    source: str
    price_type: str
    price_jpy: int
    observed_at: datetime
    condition_label: str | None
    stock_status: str | None
    listing_count: int | None


class MarketSignalsOut(BaseModel):
    change_24h_pct: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None
    yuyutei_spread_jpy: int | None
    snkrdunk_floor_vs_yuyutei_buy_jpy: int | None


class MarketMoverOut(BaseModel):
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    latest_prices: list[MarketPriceOut]
    signals: MarketSignalsOut


class PriceRefreshRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    scraping_mode: str
    source_filter: str | None
    limit_count: int
    dry_run: bool
    mappings_checked: int
    snapshots_created: int
    observations_parsed: int
    observations_inserted: int
    observations_skipped_duplicate: int
    mappings_failed: int
    error_message: str | None


class PriceRefreshRunListOut(BaseModel):
    items: list[PriceRefreshRunOut]
    total: int
    limit: int
    offset: int


class AlertEventOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    card_id: int | None
    card_code: str | None
    card_name: str | None
    source_name: str | None
    price_observation_id: int | None
    refresh_run_id: int | None
    title: str
    message: str
    dedupe_key: str
    sent_at: datetime | None
    status: str
    error_message: str | None


class AlertEventListOut(BaseModel):
    items: list[AlertEventOut]
    total: int
    limit: int
    offset: int


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    rule_type: str
    source_name: str | None
    price_type: str | None
    threshold_pct: float | None
    is_active: bool


class AlertRuleUpdateIn(BaseModel):
    is_active: bool | None = None
    threshold_pct: float | None = None


class SourceCardMappingOut(BaseModel):
    id: int
    card_id: int
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    source_name: str | None
    source_url: str | None
    source_card_id: str
    manual_verified: bool
    match_confidence: float | None
    is_active: bool
    review_status: str
    review_notes: str | None
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None


class SourceCardMappingListOut(BaseModel):
    items: list[SourceCardMappingOut]
    total: int
    limit: int
    offset: int


class SourceCardMappingUpdateIn(BaseModel):
    source_url: str | None = None
    source_card_id: str | None = None
    manual_verified: bool | None = None
    is_active: bool | None = None
    review_status: str | None = None
    review_notes: str | None = None


CollectionItemStatus = Literal["hold", "watch", "sell", "sold", "grading"]


class CollectionItemOut(BaseModel):
    id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    quantity: int
    condition_label: str | None
    purchase_price_jpy: int | None
    purchase_date: date | None
    purchase_source: str | None
    target_sell_price_jpy: int | None
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CollectionItemListOut(BaseModel):
    items: list[CollectionItemOut]
    total: int
    limit: int
    offset: int


class CollectionItemCreateIn(BaseModel):
    card_id: int
    quantity: int = Field(default=1, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: CollectionItemStatus = "hold"


class CollectionItemUpdateIn(BaseModel):
    card_id: int | None = None
    quantity: int | None = Field(default=None, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: CollectionItemStatus | None = None


class CollectionSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    items_with_purchase_price: int
    items_missing_purchase_price: int
    items_by_status: dict[str, int]


class YuyuteiPriceSnapshotOut(BaseModel):
    price_jpy: int
    observed_at: datetime


class SnkrdunkFloorSnapshotOut(BaseModel):
    price_jpy: int
    observed_at: datetime
    listing_count: int | None
    condition_label: str | None


class ValuationLatestPricesOut(BaseModel):
    yuyutei_sell: YuyuteiPriceSnapshotOut | None
    yuyutei_buy: YuyuteiPriceSnapshotOut | None
    snkrdunk_floor: SnkrdunkFloorSnapshotOut | None


class ValuationDetailOut(BaseModel):
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_retail_jpy: int | None
    pnl_vs_retail_pct: float | None
    pnl_vs_liquidation_jpy: int | None
    pnl_vs_liquidation_pct: float | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None


class ValuationFlagsOut(BaseModel):
    missing_yuyutei_sell: bool
    missing_yuyutei_buy: bool
    missing_snkrdunk_floor: bool
    missing_cost_basis: bool
    above_target_sell: bool


class PortfolioValuationItemOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    quantity: int
    condition_label: str | None
    purchase_price_jpy: int | None
    cost_basis_jpy: int | None
    target_sell_price_jpy: int | None
    latest_prices: ValuationLatestPricesOut
    valuations: ValuationDetailOut
    flags: ValuationFlagsOut


class PortfolioValuationSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    retail_value_jpy: int
    liquidation_value_jpy: int
    market_floor_value_jpy: int
    pnl_vs_retail_jpy: int
    pnl_vs_retail_pct: float
    pnl_vs_liquidation_jpy: int
    pnl_vs_liquidation_pct: float
    pnl_vs_market_floor_jpy: int
    pnl_vs_market_floor_pct: float
    items_missing_yuyutei_sell: int
    items_missing_yuyutei_buy: int
    items_missing_snkrdunk_floor: int
    items_missing_cost_basis: int
    cards_above_target_sell: int


class PortfolioValuationOut(BaseModel):
    summary: PortfolioValuationSummaryOut
    items: list[PortfolioValuationItemOut]


class CardAuditIssueOut(BaseModel):
    issue_type: str
    severity: str
    card_ids: list[int]
    card_code: str | None = None
    message: str
    suggested_action: str
    details: dict[str, Any] | None = None


class CardAuditSummaryOut(BaseModel):
    total_cards: int
    total_issues: int
    critical_issues: int
    warning_issues: int


class CardAuditReportOut(BaseModel):
    summary: CardAuditSummaryOut
    issues: list[CardAuditIssueOut]
