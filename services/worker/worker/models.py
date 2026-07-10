from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
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
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
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
    __tablename__ = "snkrdunk_candidates"
    __table_args__ = (
        CheckConstraint(
            "match_status IN ('pending', 'auto_matched', 'needs_review', 'rejected')",
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
        String(32), default="pending", server_default="pending", index=True
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
            "'stock_status_change', 'refresh_failed')",
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
            "'refresh_failed')",
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
