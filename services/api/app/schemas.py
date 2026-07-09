from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
