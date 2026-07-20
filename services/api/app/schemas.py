from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import PaginationMeta


class CollectorTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    color: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class CollectorTagCreateIn(BaseModel):
    name: str = Field(min_length=1)
    color: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorTagUpdateIn(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CollectorGroupCreateIn(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorGroupUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


# --- collector notes -----------------------------------------------------


class CollectorNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note_type: str
    card_id: int | None
    collection_item_id: int | None
    wishlist_item_id: int | None
    grading_submission_id: int | None
    market_signal_event_id: int | None
    market_report_id: int | None
    title: str | None
    body: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class CollectorNoteListOut(BaseModel):
    items: list[CollectorNoteOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectorNoteCreateIn(BaseModel):
    note_type: str = "general"
    card_id: int | None = None
    collection_item_id: int | None = None
    wishlist_item_id: int | None = None
    grading_submission_id: int | None = None
    market_signal_event_id: int | None = None
    market_report_id: int | None = None
    title: str | None = None
    body: str = Field(min_length=1)
    pinned: bool = False

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("body must not be blank")
        return cleaned


class CollectorNoteUpdateIn(BaseModel):
    note_type: str | None = None
    card_id: int | None = None
    collection_item_id: int | None = None
    wishlist_item_id: int | None = None
    grading_submission_id: int | None = None
    market_signal_event_id: int | None = None
    market_report_id: int | None = None
    title: str | None = None
    body: str | None = None
    pinned: bool | None = None

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("body must not be blank")
        return cleaned


# --- collector activity timeline -----------------------------------------


class CollectorActivityEventOut(BaseModel):
    id: int
    event_type: str
    event_source: str
    card_id: int | None
    card_code: str | None = None
    name_en: str | None = None
    name_jp: str | None = None
    collection_item_id: int | None
    wishlist_item_id: int | None
    grading_submission_id: int | None
    market_signal_event_id: int | None
    market_report_id: int | None
    market_workflow_run_id: int | None
    title: str
    message: str | None
    created_at: datetime
    payload: dict[str, Any] | None = None


class CollectorActivityListSummaryOut(BaseModel):
    total_events: int
    by_source: dict[str, int]
    by_type: dict[str, int]


class CollectorActivityListOut(BaseModel):
    summary: CollectorActivityListSummaryOut
    events: list[CollectorActivityEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectorActivitySummaryOut(BaseModel):
    today_count: int
    last_7d_count: int
    last_30d_count: int
    by_source: dict[str, int]
    recent_events: list[CollectorActivityEventOut]


class RecentActivityWidgetOut(BaseModel):
    events: list[CollectorActivityEventOut]


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
    tags: list[CollectorTagOut] = []
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
    pagination: PaginationMeta


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
    pagination: PaginationMeta


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
    pagination: PaginationMeta


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
    pagination: PaginationMeta


class SourceCardMappingUpdateIn(BaseModel):
    source_url: str | None = None
    source_card_id: str | None = None
    manual_verified: bool | None = None
    is_active: bool | None = None
    review_status: str | None = None
    review_notes: str | None = None


GradingSubmissionStatus = Literal[
    "planned", "preparing", "submitted", "grading", "shipped_back", "received", "cancelled"
]


class GradingSubmissionOut(BaseModel):
    id: int
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    quantity: int
    grading_company: str
    submission_name: str | None
    submission_status: str
    declared_value_jpy: int | None
    grading_fee_jpy: int | None
    shipping_fee_jpy: int | None
    insurance_fee_jpy: int | None
    other_fee_jpy: int | None
    total_cost_jpy: int | None
    submitted_at: date | None
    received_at: date | None
    expected_return_date: date | None
    tracking_number: str | None
    final_grade: str | None
    cert_number: str | None
    graded_value_jpy: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class GradingSubmissionCreateIn(BaseModel):
    collection_item_id: int
    grading_company: str = Field(min_length=1)
    submission_name: str | None = None
    submission_status: GradingSubmissionStatus = "planned"
    declared_value_jpy: int | None = Field(default=None, ge=0)
    grading_fee_jpy: int | None = Field(default=None, ge=0)
    shipping_fee_jpy: int | None = Field(default=None, ge=0)
    insurance_fee_jpy: int | None = Field(default=None, ge=0)
    other_fee_jpy: int | None = Field(default=None, ge=0)
    submitted_at: date | None = None
    received_at: date | None = None
    expected_return_date: date | None = None
    tracking_number: str | None = None
    final_grade: str | None = None
    cert_number: str | None = None
    graded_value_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("grading_company")
    @classmethod
    def _company_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("grading_company must not be blank")
        return cleaned


class GradingSubmissionUpdateIn(BaseModel):
    collection_item_id: int | None = None
    grading_company: str | None = None
    submission_name: str | None = None
    submission_status: GradingSubmissionStatus | None = None
    declared_value_jpy: int | None = Field(default=None, ge=0)
    grading_fee_jpy: int | None = Field(default=None, ge=0)
    shipping_fee_jpy: int | None = Field(default=None, ge=0)
    insurance_fee_jpy: int | None = Field(default=None, ge=0)
    other_fee_jpy: int | None = Field(default=None, ge=0)
    submitted_at: date | None = None
    received_at: date | None = None
    expected_return_date: date | None = None
    tracking_number: str | None = None
    final_grade: str | None = None
    cert_number: str | None = None
    graded_value_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("grading_company")
    @classmethod
    def _company_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("grading_company must not be blank")
        return cleaned


class GradingSubmissionListOut(BaseModel):
    items: list[GradingSubmissionOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class GradingSummaryOut(BaseModel):
    total_submissions: int
    by_status: dict[str, int]
    total_declared_value_jpy: int
    total_grading_cost_jpy: int
    total_graded_value_jpy: int
    total_unrealized_gain_after_grading_jpy: int
    average_grade: float | None
    items_waiting_return: int


class GradingInfoOut(BaseModel):
    has_grading_submission: bool
    latest_status: str | None
    grading_company: str | None
    final_grade: str | None
    total_grading_cost_jpy: int | None
    graded_value_jpy: int | None


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
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading_submissions: list[GradingSubmissionOut] = []
    latest_grading_status: str | None = None
    created_at: datetime
    updated_at: datetime


class CollectionItemListOut(BaseModel):
    items: list[CollectionItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


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


class CollectionImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class CollectionImportPreviewRowOut(BaseModel):
    row_number: int
    card_code: str
    matched_card_id: int
    action: str
    quantity: int
    status: str
    tags: list[str] = []
    groups: list[str] = []


class CollectionImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    created: int
    updated: int
    skipped: int


class CollectionImportResponseOut(BaseModel):
    dry_run: bool
    mode: str
    summary: CollectionImportSummaryOut
    errors: list[CollectionImportRowErrorOut]
    preview: list[CollectionImportPreviewRowOut]
    tags_created: list[str] = []
    groups_created: list[str] = []


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


ValuationMode = Literal["raw_market", "graded_adjusted"]


class GradedAdjustedValuationOut(BaseModel):
    value_jpy: int | None
    basis: str | None
    grading_submission_id: int | None
    grading_company: str | None
    final_grade: str | None
    graded_value_jpy: int | None
    raw_fallback_basis: str | None
    pnl_jpy: int | None
    pnl_pct: float | None


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
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading: GradingInfoOut
    graded_adjusted: GradedAdjustedValuationOut


class BestWorstPerformerOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    pnl_jpy: int
    pnl_pct: float | None
    basis: str


class RetailLiquidationGapOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    gap_jpy: int
    gap_pct: float | None


class HighestValueItemOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    value_jpy: int
    basis: str


class PortfolioValuationInsightsOut(BaseModel):
    best_performing_item: BestWorstPerformerOut | None
    worst_performing_item: BestWorstPerformerOut | None
    largest_retail_liquidation_gap: RetailLiquidationGapOut | None
    highest_value_item: HighestValueItemOut | None


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
    insights: PortfolioValuationInsightsOut
    valuation_mode: ValuationMode
    graded_adjusted_value_jpy: int
    pnl_vs_graded_adjusted_jpy: int
    pnl_vs_graded_adjusted_pct: float
    items_using_graded_value: int
    items_using_raw_fallback: int
    items_missing_graded_adjusted_value: int


class PortfolioValuationOut(BaseModel):
    summary: PortfolioValuationSummaryOut
    items: list[PortfolioValuationItemOut]


class PortfolioValuationSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int | None
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_retail_jpy: int | None
    pnl_vs_liquidation_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    items_missing_yuyutei_sell: int
    items_missing_yuyutei_buy: int
    items_missing_snkrdunk_floor: int
    items_missing_cost_basis: int
    cards_above_target_sell: int
    graded_adjusted_value_jpy: int | None
    pnl_vs_graded_adjusted_jpy: int | None
    items_using_graded_value: int | None
    items_using_raw_fallback: int | None
    items_missing_graded_adjusted_value: int | None


class CollectionAnalyticsSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    raw_market_floor_value_jpy: int
    graded_adjusted_value_jpy: int
    unrealized_pnl_jpy: int
    unrealized_pnl_pct: float
    items_missing_cost_basis: int
    items_missing_market_price: int
    owned_unique_cards: int
    wishlist_unique_cards: int
    grading_active_count: int


class CollectionAnalyticsBreakdownItemOut(BaseModel):
    key: str
    label: str
    item_count: int
    quantity: int
    cost_basis_jpy: int
    value_jpy: int
    pnl_jpy: int
    pnl_pct: float | None
    portfolio_weight_pct: float


class CollectionAnalyticsBreakdownsOut(BaseModel):
    by_set: list[CollectionAnalyticsBreakdownItemOut]
    by_rarity: list[CollectionAnalyticsBreakdownItemOut]
    by_variant: list[CollectionAnalyticsBreakdownItemOut]
    by_language: list[CollectionAnalyticsBreakdownItemOut]
    by_status: list[CollectionAnalyticsBreakdownItemOut]
    by_tag: list[CollectionAnalyticsBreakdownItemOut]
    by_group: list[CollectionAnalyticsBreakdownItemOut]
    by_grading_status: list[CollectionAnalyticsBreakdownItemOut]


class CollectionAnalyticsTopCardOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    quantity: int
    value_jpy: int
    portfolio_weight_pct: float


class CollectionAnalyticsConcentrationOut(BaseModel):
    top_5_cards_by_value: list[CollectionAnalyticsTopCardOut]
    top_10_cards_value_pct: float
    largest_single_card_value_pct: float
    largest_set_exposure: CollectionAnalyticsBreakdownItemOut | None
    largest_rarity_exposure: CollectionAnalyticsBreakdownItemOut | None


class CollectionAnalyticsHighestCostBasisItemOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    purchase_price_jpy: int | None
    quantity: int
    cost_basis_jpy: int
    status: str


class CollectionAnalyticsCostBasisOut(BaseModel):
    items_with_cost_basis: int
    items_without_cost_basis: int
    average_cost_basis_jpy: int
    median_cost_basis_jpy: int
    highest_cost_basis_items: list[CollectionAnalyticsHighestCostBasisItemOut]


class CollectionAnalyticsValuationQualityOut(BaseModel):
    items_with_yuyutei_sell: int
    items_with_yuyutei_buy: int
    items_with_snkrdunk_floor: int
    items_using_graded_value: int
    items_using_raw_fallback: int
    coverage_pct: float


class CollectionAnalyticsOut(BaseModel):
    summary: CollectionAnalyticsSummaryOut
    breakdowns: CollectionAnalyticsBreakdownsOut
    concentration: CollectionAnalyticsConcentrationOut
    cost_basis: CollectionAnalyticsCostBasisOut
    valuation_quality: CollectionAnalyticsValuationQualityOut


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


class MarketSignalLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class MarketSignalMetricsOut(BaseModel):
    change_pct: float | None
    spread_pct: float | None
    gap_pct: float | None
    gap_jpy: int | None


class MarketSignalOut(BaseModel):
    signal_type: str
    severity: str
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    owned_quantity: int
    collection_item_id: int | None = None
    latest_prices: MarketSignalLatestPricesOut
    metrics: MarketSignalMetricsOut
    message: str
    suggested_action: str


class MarketSignalsSummaryOut(BaseModel):
    total_signals: int
    by_signal_type: dict[str, int]
    owned_signal_count: int
    market_signal_count: int
    data_quality_signal_count: int


class MarketSignalsResponseOut(BaseModel):
    summary: MarketSignalsSummaryOut
    signals: list[MarketSignalOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketSignalEventOut(BaseModel):
    id: int
    signal_type: str
    status: str
    severity: str
    suggested_action: str | None
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    collection_item_id: int | None
    owned_quantity: int
    message: str | None
    notes: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int
    last_payload: dict[str, Any] | None
    dismissed_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MarketSignalEventsSummaryOut(BaseModel):
    total_events: int
    open_events: int
    watching_events: int
    dismissed_events: int
    resolved_events: int
    by_signal_type: dict[str, int]
    by_suggested_action: dict[str, int]


class MarketSignalEventListOut(BaseModel):
    summary: MarketSignalEventsSummaryOut
    events: list[MarketSignalEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketSignalEventUpdateIn(BaseModel):
    status: str | None = None
    notes: str | None = None


class OpportunitiesSummaryOut(BaseModel):
    total_opportunities: int
    average_score: float
    highest_score: int
    by_category: dict[str, int]
    wishlist_target_hit_count: int = 0


class OpportunityOut(BaseModel):
    score: int
    category: str
    event_id: int
    signal_type: str
    status: str
    severity: str
    suggested_action: str | None
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    owned_quantity: int
    message: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int
    score_reasons: list[str]
    last_payload: dict[str, Any] | None
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading: GradingInfoOut
    wishlist_item_id: int | None = None
    wishlist_priority: str | None = None
    wishlist_target_buy_price_jpy: int | None = None
    wishlist_target_hit: bool = False


class OpportunitiesResponseOut(BaseModel):
    summary: OpportunitiesSummaryOut
    opportunities: list[OpportunityOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketReportPortfolioSnapshotOut(BaseModel):
    total_cost_basis_jpy: int | None
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None
    items_missing_cost_basis: int
    items_missing_prices: int
    graded_adjusted_value_jpy: int | None


class MarketReportOpportunitySummaryOut(BaseModel):
    total_opportunities: int
    highest_score: int | None
    average_score: float | None
    by_category: dict[str, int]
    wishlist_target_hit_count: int = 0


class MarketReportTopOpportunitiesOut(BaseModel):
    top_5: list[OpportunityOut]
    top_buy: OpportunityOut | None
    top_sell: OpportunityOut | None
    top_momentum: OpportunityOut | None
    top_drop: OpportunityOut | None
    top_owned: OpportunityOut | None
    top_data_quality: OpportunityOut | None


class MarketReportCollectionQualityOut(BaseModel):
    missing_purchase_price_count: int
    missing_condition_count: int
    missing_target_sell_count: int
    total_quality_issues: int


class MarketReportSignalEventSummaryOut(BaseModel):
    open_events: int
    watching_events: int
    dismissed_events: int
    resolved_events: int
    most_common_signal_type: str | None
    most_common_suggested_action: str | None


class MarketReportSummaryOut(BaseModel):
    total_opportunities: int
    highest_score: int | None
    average_score: float | None


class MarketReportPayloadOut(BaseModel):
    summary: MarketReportSummaryOut
    portfolio_snapshot: MarketReportPortfolioSnapshotOut
    opportunity_summary: MarketReportOpportunitySummaryOut
    top_opportunities: MarketReportTopOpportunitiesOut
    collection_quality: MarketReportCollectionQualityOut
    signal_event_summary: MarketReportSignalEventSummaryOut
    deterministic_summary_lines: list[str]


class MarketIntelligenceReportOut(BaseModel):
    id: int
    created_at: datetime
    report_date: date
    summary: MarketReportSummaryOut
    portfolio_snapshot: MarketReportPortfolioSnapshotOut
    opportunity_summary: MarketReportOpportunitySummaryOut
    top_opportunities: MarketReportTopOpportunitiesOut
    collection_quality: MarketReportCollectionQualityOut
    signal_event_summary: MarketReportSignalEventSummaryOut
    deterministic_summary_lines: list[str]
    payload: dict[str, Any]


class MarketIntelligenceReportSummaryOut(BaseModel):
    id: int
    created_at: datetime
    report_date: date
    total_opportunities: int
    highest_score: int | None
    average_score: float | None
    buy_opportunities_count: int
    sell_opportunities_count: int
    momentum_count: int
    drop_count: int
    data_quality_count: int
    owned_count: int
    portfolio_market_floor_value_jpy: int | None
    portfolio_retail_value_jpy: int | None
    portfolio_liquidation_value_jpy: int | None
    portfolio_pnl_vs_market_floor_jpy: int | None


class MarketIntelligenceReportListOut(BaseModel):
    reports: list[MarketIntelligenceReportSummaryOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class BackupValidateResponseOut(BaseModel):
    valid: bool
    backup_version: int | None
    summary: dict[str, int]
    warnings: list[str]
    errors: list[str]


class BackupRestoreResponseOut(BaseModel):
    dry_run: bool
    mode: str
    valid: bool
    backup_version: int | None
    summary: dict[str, dict[str, int]]
    warnings: list[str]
    errors: list[str]
    preview: dict[str, dict[str, int]]


class AdminRefreshPricesRequest(BaseModel):
    source: str = "all"
    limit: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class AdminRefreshPricesResponse(BaseModel):
    run_id: int | None
    job_id: str | None
    status: str | None
    warnings: list[str] = []


class AdminSnapshotPortfolioResponse(BaseModel):
    snapshot_id: int


class AdminSnapshotMarketSignalsResponse(BaseModel):
    created_count: int
    updated_count: int
    resolved_count: int


class AdminGenerateMarketReportResponse(BaseModel):
    report_id: int


class AdminFullMarketRefreshRequest(BaseModel):
    source: str = "all"
    limit: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class AdminMarketSignalSnapshotCounts(BaseModel):
    created: int
    updated: int
    resolved: int


class AdminFullMarketRefreshResponse(BaseModel):
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_signal_snapshot: AdminMarketSignalSnapshotCounts
    market_report_id: int | None
    dry_run: bool
    warnings: list[str] = []


class AdminSendMarketReportDigestRequest(BaseModel):
    dry_run: bool = False
    force: bool = False


class AdminSendMarketReportDigestResponse(BaseModel):
    report_id: int | None
    status: str | None
    sent: bool
    skipped_reason: str | None
    message_preview: str | None


class MarketWorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    source: str
    limit: int | None
    send_telegram: bool
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_report_id: int | None
    signal_events_created: int
    signal_events_updated: int
    signal_events_resolved: int
    telegram_digest_status: str | None
    warnings: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class MarketWorkflowRunListOut(BaseModel):
    items: list[MarketWorkflowRunOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class AdminRunMarketWorkflowRequest(BaseModel):
    source: str = "yuyutei"
    limit: int | None = Field(default=None, ge=1)
    send_telegram: bool = False
    dry_run: bool = False


class AdminRunMarketWorkflowResponse(BaseModel):
    market_workflow_run_id: int | None
    status: str | None
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_signal_snapshot: AdminMarketSignalSnapshotCounts
    market_report_id: int | None
    telegram_digest_status: str | None
    warnings: list[str] = []


# --- Wishlist / acquisition tracker -----------------------------------------

WishlistPriority = Literal["low", "medium", "high", "grail"]
WishlistStatus = Literal["watching", "target_hit", "purchased", "passed", "removed"]


class WishlistLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class WishlistItemOut(BaseModel):
    id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    priority: str
    status: str
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_condition: str | None
    preferred_source: str | None
    desired_quantity: int
    acquired_quantity: int
    acquired_collection_item_id: int | None
    notes: str | None
    owned_quantity: int
    latest_prices: WishlistLatestPricesOut
    preferred_current_price_jpy: int | None
    preferred_current_price_source: str | None
    target_hit: bool
    gap_to_target_jpy: int | None
    gap_to_target_pct: float | None
    tags: list[CollectorTagOut] = []
    created_at: datetime
    updated_at: datetime


class WishlistItemListOut(BaseModel):
    items: list[WishlistItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class WishlistItemCreateIn(BaseModel):
    card_id: int
    priority: WishlistPriority = "medium"
    target_buy_price_jpy: int | None = Field(default=None, ge=0)
    max_buy_price_jpy: int | None = Field(default=None, ge=0)
    preferred_condition: str | None = None
    preferred_source: str | None = None
    desired_quantity: int = Field(default=1, ge=1)
    notes: str | None = None


class WishlistItemUpdateIn(BaseModel):
    priority: WishlistPriority | None = None
    status: WishlistStatus | None = None
    target_buy_price_jpy: int | None = Field(default=None, ge=0)
    max_buy_price_jpy: int | None = Field(default=None, ge=0)
    preferred_condition: str | None = None
    preferred_source: str | None = None
    desired_quantity: int | None = Field(default=None, ge=1)
    notes: str | None = None


class WishlistMarkPurchasedIn(BaseModel):
    collection_item_id: int
    acquired_quantity: int = Field(default=1, ge=1)


class WishlistConvertToCollectionIn(BaseModel):
    quantity: int = Field(default=1, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    status: CollectionItemStatus = "hold"
    notes: str | None = None


class WishlistConvertToCollectionOut(BaseModel):
    wishlist_item: WishlistItemOut
    collection_item: CollectionItemOut


class WishlistSummaryOut(BaseModel):
    total_wishlist_items: int
    watching: int
    target_hit: int
    purchased: int
    passed: int
    removed: int
    grail_count: int
    high_priority_count: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int
    items_owned_already: int
    items_with_target_hit: int


class WishlistAnalyticsSummaryOut(BaseModel):
    total_items: int
    watching_count: int
    target_hit_count: int
    purchased_count: int
    passed_count: int
    grail_count: int
    high_priority_count: int
    owned_already_count: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int
    total_current_price_jpy: int
    budget_gap_to_target_jpy: int
    budget_gap_to_max_jpy: int
    average_target_price_jpy: int
    median_target_price_jpy: int


class WishlistAnalyticsBreakdownItemOut(BaseModel):
    key: str
    label: str
    item_count: int
    desired_quantity: int
    target_budget_jpy: int
    max_budget_jpy: int
    current_price_jpy: int
    target_hit_count: int
    owned_count: int
    budget_weight_pct: float


class WishlistAnalyticsBreakdownsOut(BaseModel):
    by_priority: list[WishlistAnalyticsBreakdownItemOut]
    by_status: list[WishlistAnalyticsBreakdownItemOut]
    by_set: list[WishlistAnalyticsBreakdownItemOut]
    by_rarity: list[WishlistAnalyticsBreakdownItemOut]
    by_preferred_source: list[WishlistAnalyticsBreakdownItemOut]
    by_preferred_condition: list[WishlistAnalyticsBreakdownItemOut]


class WishlistAnalyticsTargetItemOut(BaseModel):
    wishlist_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    priority: str
    status: str
    desired_quantity: int
    owned_quantity: int
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_current_price_jpy: int | None
    preferred_current_price_source: str | None
    target_hit: bool
    gap_to_target_jpy: int | None
    gap_to_target_pct: float | None


class WishlistAnalyticsBudgetPlanOut(BaseModel):
    grail_targets: list[WishlistAnalyticsTargetItemOut]
    high_priority_targets: list[WishlistAnalyticsTargetItemOut]
    best_gap_to_target: list[WishlistAnalyticsTargetItemOut]
    largest_budget_items: list[WishlistAnalyticsTargetItemOut]
    already_owned: list[WishlistAnalyticsTargetItemOut]


class WishlistAnalyticsPriceCoverageOut(BaseModel):
    items_with_current_price: int
    items_missing_current_price: int
    coverage_pct: float


class WishlistAnalyticsOut(BaseModel):
    summary: WishlistAnalyticsSummaryOut
    breakdowns: WishlistAnalyticsBreakdownsOut
    target_hits: list[WishlistAnalyticsTargetItemOut]
    budget_plan: WishlistAnalyticsBudgetPlanOut
    price_coverage: WishlistAnalyticsPriceCoverageOut


SellDecisionAction = Literal["review_sell", "hold", "grade_first", "missing_data", "monitor"]


class SellDecisionSummaryOut(BaseModel):
    total_candidates: int
    review_sell_count: int
    hold_count: int
    grade_first_count: int
    missing_data_count: int
    monitor_count: int
    total_potential_sale_value_jpy: int
    total_unrealized_pnl_jpy: int
    average_score: float


class SellDecisionLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class SellDecisionMarketContextOut(BaseModel):
    yuyutei_spread_pct: float | None
    snkrdunk_vs_yuyutei_sell_gap_pct: float | None
    related_opportunity_score: int | None
    related_signal_types: list[str]


class SellDecisionGradingOut(BaseModel):
    has_active_grading: bool
    latest_status: str | None
    final_grade: str | None
    graded_value_jpy: int | None


class SellDecisionWishlistOverlapOut(BaseModel):
    is_on_wishlist: bool
    priority: str | None
    status: str | None


class SellDecisionCandidateOut(BaseModel):
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
    status: str
    condition_label: str | None
    score: int
    recommended_action: SellDecisionAction
    current_value_jpy: int | None
    current_value_basis: str | None
    cost_basis_jpy: int | None
    unrealized_pnl_jpy: int | None
    unrealized_pnl_pct: float | None
    target_sell_price_jpy: int | None
    above_target_sell: bool
    latest_prices: SellDecisionLatestPricesOut
    market_context: SellDecisionMarketContextOut
    grading: SellDecisionGradingOut
    wishlist_overlap: SellDecisionWishlistOverlapOut
    tags: list[str]
    groups: list[str]
    score_reasons: list[str]
    warnings: list[str]


class SellDecisionSupportOut(BaseModel):
    summary: SellDecisionSummaryOut
    candidates: list[SellDecisionCandidateOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class WishlistImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class WishlistImportPreviewRowOut(BaseModel):
    row_number: int
    card_code: str
    matched_card_id: int
    action: str
    priority: str
    status: str


class WishlistImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    created: int
    updated: int
    skipped: int


class WishlistImportResponseOut(BaseModel):
    dry_run: bool
    mode: str
    summary: WishlistImportSummaryOut
    errors: list[WishlistImportRowErrorOut]
    preview: list[WishlistImportPreviewRowOut]


# --- Dashboard personalization -----------------------------------------

DashboardTimeframe = Literal["7d", "30d", "90d", "all"]


class DashboardPreferencesOut(BaseModel):
    layout: list[str]
    hidden_widgets: list[str]
    pinned_cards: list[int]
    default_timeframe: str
    show_raw_market_value: bool
    show_graded_adjusted_value: bool
    show_wishlist_budget: bool
    show_grading_costs: bool


class DashboardPreferencesUpdateIn(BaseModel):
    layout: list[str] | None = None
    hidden_widgets: list[str] | None = None
    pinned_cards: list[int] | None = None
    default_timeframe: DashboardTimeframe | None = None
    show_raw_market_value: bool | None = None
    show_graded_adjusted_value: bool | None = None
    show_wishlist_budget: bool | None = None
    show_grading_costs: bool | None = None


class PortfolioSummaryWidgetOut(BaseModel):
    total_cost_basis_jpy: int | None
    market_floor_value_jpy: int | None
    graded_adjusted_value_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None
    pnl_vs_graded_adjusted_jpy: int | None
    pnl_vs_graded_adjusted_pct: float | None


class PortfolioChartPointOut(BaseModel):
    created_at: datetime
    market_floor_value_jpy: int | None
    graded_adjusted_value_jpy: int | None


class PortfolioChartWidgetOut(BaseModel):
    timeframe: str
    points: list[PortfolioChartPointOut]


class WishlistTargetsWidgetOut(BaseModel):
    items: list[WishlistItemOut]
    total_target_hit: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int


class TopOpportunitiesWidgetOut(BaseModel):
    opportunities: list[OpportunityOut]


class GradingStatusWidgetOut(BaseModel):
    total_submissions: int
    submitted_or_grading_count: int
    received_count: int
    total_grading_cost_jpy: int


class MarketReportWidgetOut(BaseModel):
    report_id: int | None
    report_date: date | None
    total_opportunities: int | None
    highest_score: int | None
    deterministic_summary_lines: list[str]


class CollectionQualityWidgetOut(BaseModel):
    missing_purchase_price_count: int
    missing_condition_count: int
    missing_target_sell_count: int


class RecentSignalEventsWidgetOut(BaseModel):
    events: list[MarketSignalEventOut]


class DataFreshnessWidgetOut(BaseModel):
    latest_refresh_at: datetime | None
    latest_refresh_status: str | None
    missing_recent_price_count: int
    stale_mapping_price_count: int


class BackupStatusWidgetOut(BaseModel):
    tracked: bool
    last_backup_at: datetime | None = None
    message: str | None = None


class WorkflowStatusWidgetOut(BaseModel):
    run_id: int | None
    status: str | None
    market_report_id: int | None
    telegram_digest_status: str | None
    finished_at: datetime | None
    error_count_24h: int = 0
    warning_count_24h: int = 0


class DashboardWidgetsOut(BaseModel):
    portfolio_summary: PortfolioSummaryWidgetOut
    portfolio_chart: PortfolioChartWidgetOut
    wishlist_targets: WishlistTargetsWidgetOut
    top_opportunities: TopOpportunitiesWidgetOut
    grading_status: GradingStatusWidgetOut
    market_report: MarketReportWidgetOut
    collection_quality: CollectionQualityWidgetOut
    recent_signal_events: RecentSignalEventsWidgetOut
    data_freshness: DataFreshnessWidgetOut
    backup_status: BackupStatusWidgetOut
    workflow_status: WorkflowStatusWidgetOut
    recent_activity: RecentActivityWidgetOut


class DashboardOverviewOut(BaseModel):
    preferences: DashboardPreferencesOut
    widgets: DashboardWidgetsOut


# --- search --------------------------------------------------------------


class SearchResultOut(BaseModel):
    type: str
    id: int
    score: int
    title: str
    subtitle: str
    matched_fields: list[str]
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchSummaryOut(BaseModel):
    total_results: int
    by_type: dict[str, int]


class SearchResponseOut(BaseModel):
    query: str
    summary: SearchSummaryOut
    results: list[SearchResultOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class SearchSuggestionOut(BaseModel):
    label: str
    type: str
    url: str


class SearchSuggestionsResponseOut(BaseModel):
    suggestions: list[SearchSuggestionOut]


# --- system check ----------------------------------------------------------


class SystemCheckResultOut(BaseModel):
    name: str
    status: str
    severity: str
    message: str


class SystemCheckSummaryOut(BaseModel):
    checks_total: int
    checks_passed: int
    warnings: int
    critical: int


class SystemCheckResponseOut(BaseModel):
    status: str
    summary: SystemCheckSummaryOut
    checks: list[SystemCheckResultOut]


# --- env check ---------------------------------------------------------


class EnvCheckResultOut(BaseModel):
    name: str
    status: str
    severity: str
    message: str


class EnvCheckResponseOut(BaseModel):
    status: str
    app_env: str
    checks: list[EnvCheckResultOut]
    warnings: list[str]
    errors: list[str]


# --- db backups ---------------------------------------------------------


class DbBackupFileOut(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


class DbBackupListOut(BaseModel):
    backup_dir: str
    backups: list[DbBackupFileOut]
    limit: int
    offset: int
    pagination: PaginationMeta


# --- app logs / observability -------------------------------------------


class AppLogEventOut(BaseModel):
    id: int
    created_at: datetime
    level: str
    service: str
    event_type: str
    message: str
    context: dict[str, Any] | None
    traceback: str | None
    related_run_id: int | None
    related_entity_type: str | None
    related_entity_id: int | None


class AppLogSummaryOut(BaseModel):
    total_logs: int
    error_count: int
    warning_count: int
    critical_count: int
    by_service: dict[str, int]
    by_event_type: dict[str, int]


class AppLogListOut(BaseModel):
    summary: AppLogSummaryOut
    logs: list[AppLogEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class AppLogPruneRequestIn(BaseModel):
    older_than_days: int = 30
    dry_run: bool = True
    confirm: str | None = None


class AppLogPruneResponseOut(BaseModel):
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int


class ObservabilityLast24hOut(BaseModel):
    critical: int
    error: int
    warning: int
    info: int


class ObservabilitySummaryOut(BaseModel):
    status: str
    last_24h: ObservabilityLast24hOut
    latest_error: AppLogEventOut | None
    latest_market_workflow_run: dict[str, Any] | None
    latest_price_refresh_run: dict[str, Any] | None
    latest_backup: dict[str, Any] | None
    latest_system_check_status: str | None


# --- rate limiting --------------------------------------------------------


class RateLimitWindowOut(BaseModel):
    group: str
    limit: int
    window_seconds: int
    active_keys: int


class RateLimitStatusOut(BaseModel):
    enabled: bool
    windows: list[RateLimitWindowOut]


# --- version / release status -------------------------------------------


class VersionOut(BaseModel):
    app: str
    version: str
    git_commit: str
    build_time: str
    app_env: str


class ReleaseReadinessOut(BaseModel):
    system_check_status: str
    critical_logs_last_24h: int
    latest_backup_available: bool


class ReleaseStatusOut(BaseModel):
    version: str
    git_commit: str
    build_time: str
    app_env: str
    latest_market_workflow_run: dict[str, Any] | None
    latest_system_check: SystemCheckResponseOut
    latest_backup: dict[str, Any] | None
    latest_error: AppLogEventOut | None
    release_readiness: ReleaseReadinessOut


# --- db index audit / performance -------------------------------------


class DbIndexCheckOut(BaseModel):
    table: str
    index: str
    status: str
    severity: str
    message: str


class DbIndexAuditSummaryOut(BaseModel):
    total_checks: int
    passed: int
    warnings: int
    critical: int


class DbIndexAuditResponseOut(BaseModel):
    summary: DbIndexAuditSummaryOut
    checks: list[DbIndexCheckOut]


class SlowRequestOut(BaseModel):
    created_at: datetime
    message: str
    context: dict[str, Any] | None


class PerformanceDatabaseCountsOut(BaseModel):
    price_observations_count: int
    raw_snapshots_count: int
    market_signal_events_count: int
    collector_activity_events_count: int
    app_log_events_count: int


class PerformanceIndexAuditSummaryOut(BaseModel):
    warnings: int
    critical: int


class LargestResponseOut(BaseModel):
    created_at: datetime
    method: str | None
    path: str | None
    size_bytes: int | None


class PerformanceSummaryOut(BaseModel):
    status: str
    database: PerformanceDatabaseCountsOut
    latest_slow_requests: list[SlowRequestOut]
    index_audit: PerformanceIndexAuditSummaryOut
    response_size_warnings_last_24h: int = 0
    slow_requests_last_24h: int = 0
    largest_recent_responses: list[LargestResponseOut] = []
    active_job_locks: int = 0
    expired_job_locks: int = 0
    cache_enabled: bool = True
    cache_backend: str = "none"
    cache_keys: int | None = None
    file_jobs_by_status: dict[str, int] = {}
    stale_running_file_jobs: int = 0


# --- job locks -------------------------------------------------------------


class JobLockOut(BaseModel):
    lock_name: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime
    status: str
    metadata: dict[str, Any] | None


class JobLockListOut(BaseModel):
    locks: list[JobLockOut]


class JobLockCleanupResponseOut(BaseModel):
    cleaned_up_count: int


class JobLockForceReleaseRequestIn(BaseModel):
    confirm: str | None = None


class JobLockForceReleaseResponseOut(BaseModel):
    released: bool
    lock_name: str


# --- data retention / pruning -------------------------------------------


class DataRetentionPolicyOut(BaseModel):
    table: str
    retention_days: int
    mode: str
    protected_records: str
    enabled: bool


class DataRetentionPolicyResponseOut(BaseModel):
    policies: list[DataRetentionPolicyOut]


class DataRetentionPruneRequestIn(BaseModel):
    dry_run: bool = True
    tables: list[str] | None = None
    confirm: str | None = None


class DataRetentionPruneResultOut(BaseModel):
    table: str
    retention_days: int | None
    rows_would_delete: int
    rows_deleted: int
    status: str
    warning: str | None


class DataRetentionPruneSummaryOut(BaseModel):
    tables_checked: int
    total_rows_would_delete: int
    total_rows_deleted: int
    warnings: int


class DataRetentionPruneResponseOut(BaseModel):
    dry_run: bool
    summary: DataRetentionPruneSummaryOut
    results: list[DataRetentionPruneResultOut]


# --- cache ---------------------------------------------------------------


class CacheStatsOut(BaseModel):
    keys: int
    hits: int
    misses: int


class CacheTtlOut(BaseModel):
    dashboard: int
    market: int
    collection: int


class CacheStatusOut(BaseModel):
    enabled: bool
    backend: str
    stats: CacheStatsOut
    ttl: CacheTtlOut


class CacheClearRequestIn(BaseModel):
    prefix: str | None = None
    confirm: str | None = None


class CacheClearResponseOut(BaseModel):
    success: bool
    prefix: str | None
    deleted_count: int | None


# --- file jobs -------------------------------------------------------------


class FileJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    original_filename: str | None
    output_filename: str | None
    content_type: str | None
    dry_run: bool
    mode: str | None
    progress_current: int
    progress_total: int | None
    download_ready: bool
    summary: dict[str, Any] | None
    errors: Any | None
    warnings: Any | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FileJobListOut(BaseModel):
    jobs: list[FileJobOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class FileJobCreatedOut(BaseModel):
    file_job_id: int
    status: str


class FileJobCancelResponseOut(BaseModel):
    id: int
    status: str


class BackupExportJobRequestIn(BaseModel):
    include_prices: bool = False
    include_raw_snapshots: bool = False
    include_refresh_runs: bool = False
    include_logs: bool = False


class CollectionExportJobRequestIn(BaseModel):
    filters: dict[str, Any] | None = None


class WishlistExportJobRequestIn(BaseModel):
    filters: dict[str, Any] | None = None


class FileJobCleanupRequestIn(BaseModel):
    older_than_days: int = 7
    dry_run: bool = True
    confirm: str | None = None


class FileJobCleanupResponseOut(BaseModel):
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int
