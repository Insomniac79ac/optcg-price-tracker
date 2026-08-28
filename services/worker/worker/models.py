from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from worker.db import Base


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint(
            "card_code", "set_code", "rarity", "variant", "language",
            name="uq_cards_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64), index=True)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    rarity: Mapped[str] = mapped_column(String(32))
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8))
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    base_url: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceCardMapping(Base):
    __tablename__ = "source_card_mappings"
    __table_args__ = (
        UniqueConstraint("card_id", "source_id", name="uq_source_card_mappings_card_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # LEGACY COMPATIBILITY, NOT IDENTITY - card_print_id below is what
    # identifies the printing this mapping prices. Nullable since
    # c9f31e2a7d04: the legacy `cards` table names 21 of the catalogue's
    # 2,710 card codes, so a print-authoritative mapping may have no legacy
    # row to point at. Existing rows keep the value they have.
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # THE AUTHORITATIVE IDENTITY. The api's b858237e3706 and c9f31e2a7d04
    # migrations own the card_prints FK and the composite lineage
    # constraints, so this mirrors them as a plain nullable column rather
    # than redeclaring them here. Nullable only because pre-existing legacy
    # (card_id-only) mappings stay valid.
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_card_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    review_status: Mapped[str] = mapped_column(
        String(32), default="approved", server_default="approved"
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    http_status: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_content: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # LEGACY COMPATIBILITY, NOT IDENTITY - a priced observation is identified
    # by (source_card_mapping_id, card_print_id, source_id) below. Nullable
    # since c9f31e2a7d04; existing rows keep the value they have.
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    price_type: Mapped[str] = mapped_column(String(32))
    price_jpy: Mapped[int] = mapped_column(Integer)
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("snkrdunk_candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # THE AUTHORITATIVE LINEAGE, with source_id above. The api's
    # b858237e3706 and c9f31e2a7d04 migrations own the composite
    # (source_card_mapping_id, card_print_id, source_id) FK and the
    # paired-lineage check constraint, so these mirror them as plain nullable
    # columns rather than redeclaring them here. Nullable only because legacy
    # observations carry neither field.
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class SnkrdunkDiscoveryRun(Base):
    __tablename__ = "snkrdunk_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'blocked', "
            "'failed', 'manual_import')",
            name="ck_snkrdunk_discovery_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    seed_url: Mapped[str] = mapped_column(String(1024))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_matched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Compact, versioned resume state - see worker.jobs.snkrdunk_checkpoint.
    # Nullable so every row written before the column existed stays valid, and
    # so "this run stored no checkpoint" is distinguishable from "this run
    # stored empty progress".
    resume_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PriceRefreshRun(Base):
    __tablename__ = "price_refresh_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'failed')",
            name="ck_price_refresh_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    scraping_mode: Mapped[str] = mapped_column(String(16))
    source_filter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    limit_count: Mapped[int] = mapped_column(Integer)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mappings_checked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_parsed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_inserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_skipped_duplicate: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    mappings_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SnkrdunkCandidate(Base):
    """Mirrors app.models.snkrdunk_candidate.SnkrdunkCandidate table-for-
    table (see this file's own module docstring on why - the api and worker
    services share no code). Deliberately does not declare the api-only
    best_match_*/match_explanation_json/ambiguous_matches_json columns (see
    app.services.card_matching) - the worker never reads or writes them, and
    SQLAlchemy only ever selects the columns a model actually maps, so their
    presence in the real database is harmless here."""

    __tablename__ = "snkrdunk_candidates"
    __table_args__ = (
        CheckConstraint(
            "match_status IN ('unmatched', 'suggested', 'ambiguous', 'matched', 'rejected')",
            name="ck_snkrdunk_candidates_match_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("snkrdunk_discovery_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_card_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detected_set_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detected_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detected_variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_status: Mapped[str] = mapped_column(
        String(32), default="unmatched", server_default="unmatched", index=True
    )
    matched_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
    )
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('price_change_pct', 'yuyutei_buy_change_pct', "
            "'stock_status_change', 'refresh_failed', 'owned_card_above_target_sell', "
            "'owned_card_below_cost_basis', 'portfolio_value_change_pct')",
            name="ck_alert_rules_rule_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    name: Mapped[str] = mapped_column(String(255), unique=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    threshold_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('price_up', 'price_down', 'yuyutei_buy_up', 'stock_out', "
            "'refresh_failed', 'owned_card_above_target_sell', 'owned_card_below_cost_basis', "
            "'portfolio_value_up', 'portfolio_value_down')",
            name="ck_alert_events_event_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped_duplicate')",
            name="ck_alert_events_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id", ondelete="SET NULL"), nullable=True
    )
    refresh_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_refresh_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectionItem(Base):
    __tablename__ = "collection_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('hold', 'watch', 'sell', 'sold', 'grading')",
            name="ck_collection_items_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_sell_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="hold", server_default="hold", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PortfolioValuationSnapshot(Base):
    __tablename__ = "portfolio_valuation_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    total_items: Mapped[int] = mapped_column(Integer)
    total_quantity: Mapped[int] = mapped_column(Integer)
    total_cost_basis_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retail_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    liquidation_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_floor_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pnl_vs_retail_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pnl_vs_liquidation_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pnl_vs_market_floor_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_missing_yuyutei_sell: Mapped[int] = mapped_column(Integer)
    items_missing_yuyutei_buy: Mapped[int] = mapped_column(Integer)
    items_missing_snkrdunk_floor: Mapped[int] = mapped_column(Integer)
    items_missing_cost_basis: Mapped[int] = mapped_column(Integer)
    cards_above_target_sell: Mapped[int] = mapped_column(Integer)


class MarketIntelligenceReport(Base):
    __tablename__ = "market_intelligence_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    report_date: Mapped[date] = mapped_column(Date, index=True)

    total_opportunities: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    highest_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    buy_opportunities_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sell_opportunities_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    momentum_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    drop_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data_quality_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    owned_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    portfolio_market_floor_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_retail_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_liquidation_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_pnl_vs_market_floor_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    top_buy_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_sell_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_momentum_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_drop_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_owned_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_data_quality_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    report_payload_json: Mapped[dict] = mapped_column(JSON)


class MarketSignalEvent(Base):
    __tablename__ = "market_signal_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'watching', 'dismissed', 'resolved')",
            name="ck_market_signal_events_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collection_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_items.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(16), default="info", server_default="info")
    suggested_action: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    seen_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketReportDigestSend(Base):
    __tablename__ = "market_report_digest_sends"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "destination", name="uq_market_report_digest_sends_report_destination"
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')",
            name="ck_market_report_digest_sends_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(
        String(32), default="telegram", server_default="telegram"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MarketWorkflowRun(Base):
    __tablename__ = "market_workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial_success', 'failed')",
            name="ck_market_workflow_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default="running", index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_telegram: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    price_refresh_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_refresh_runs.id", ondelete="SET NULL"), nullable=True
    )
    portfolio_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_valuation_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    market_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="SET NULL"), nullable=True
    )
    signal_events_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    signal_events_updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    signal_events_resolved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    telegram_digest_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    warnings_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollectorActivityEvent(Base):
    """Mirrors app.models.collector_activity_event.CollectorActivityEvent on
    the api service - same table, same shape. Only read here by
    worker.data_retention (see that module and worker.celery_app's
    prune-data-retention beat task); nothing in the worker ever writes this
    table."""

    __tablename__ = "collector_activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_source: Mapped[str] = mapped_column(String(32), index=True)
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collection_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    wishlist_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grading_submission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_signal_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_signal_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    market_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="SET NULL"), nullable=True
    )
    market_workflow_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class JobLock(Base):
    """Mirrors app.models.job_lock.JobLock on the api service - same table,
    same shape. See worker.job_locks for acquire/release semantics used by
    worker.jobs.refresh_prices and worker.jobs.run_market_workflow (both the
    manual CLI and Celery-task/beat-scheduled entry points)."""

    __tablename__ = "job_locks"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'released', 'expired')", name="ck_job_locks_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lock_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", index=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppLogEvent(Base):
    """Mirrors app.models.app_log_event.AppLogEvent on the api service -
    same table, same shape. Written by worker.app_logging (best-effort
    structured log rows for GET /admin/logs, served by the api service off
    the same Postgres database)."""

    __tablename__ = "app_log_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error', 'critical')",
            name="ck_app_log_events_level",
        ),
        Index("ix_app_log_events_related_entity", "related_entity_type", "related_entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(16), index=True)
    service: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
