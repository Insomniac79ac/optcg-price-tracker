"""Minimal ORM mappings onto tables owned by services/api/app/models - this
service only reads Card/CanonicalCard/Source/CardPrint/SourceCardMapping and
writes RawSnapshot/PriceObservation plus the Yuyu-Tei discovery tables, so
only the columns it actually touches are declared here. Consistent with services/worker/worker/models.py, which
independently declares its own minimal subset of the same physical tables
rather than importing app.models directly - each Railway service ships its
own dependency-isolated image.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from yuyutei_collector.db import Base


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))


class CardPrint(Base):
    """Read-only lookup - this service never creates or verifies prints
    (see services/api/app/models/card_print.py, which owns that)."""

    __tablename__ = "card_prints"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_card_id: Mapped[int] = mapped_column(Integer)
    # Optional at the runtime type layer so a future NULL loads instead of
    # tripping the mapper. The API owns the column and it is still NOT NULL
    # in the database - this mirror emits no DDL.
    treatment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(16))
    # Default matches the real table's server_default="true" (see
    # services/api/app/models/card_print.py) - existing fixtures across this
    # service's tests that construct a CardPrint without passing is_active
    # explicitly (predating this column's addition here) keep working
    # unchanged, exactly as they would against the real schema.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceCardMapping(Base):
    __tablename__ = "source_card_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_card_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean)
    review_status: Mapped[str] = mapped_column(String(32))


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    source_url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    http_status: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "card_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.card_id",
                "source_card_mappings.source_id",
            ],
            ondelete="RESTRICT",
            name="fk_price_observations_mapping_print_card_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    price_type: Mapped[str] = mapped_column(String(32))
    price_jpy: Mapped[int] = mapped_column(Integer)
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CanonicalCard(Base):
    """Read-only lookup for exact-print classification. The card_code column
    carries a UNIQUE constraint in the real schema
    (uq_canonical_cards_card_code); discovery still checks for a second row
    rather than assuming it, and fails closed if one appears."""

    __tablename__ = "canonical_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64))


class YuyuteiDiscoveryRun(Base):
    """Mirror of app.models.yuyutei_discovery_run - same physical table. This
    service writes it; the API owns the schema and emits the DDL."""

    __tablename__ = "yuyutei_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'denied', 'failed')",
            name="ck_yuyutei_discovery_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    requested_set_slugs: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True
    )
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    products_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_written: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    foreign_series_filtered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_products: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unparseable_codes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stopped_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    per_slug_metrics_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )


class YuyuteiCandidate(Base):
    """Mirror of app.models.yuyutei_candidate - same physical table.

    The constraints are restated here rather than omitted so this service's
    own SQLite-backed tests exercise the real invariants: composite identity,
    the closed match vocabulary, and the rule that only print_matched may
    carry a print id."""

    __tablename__ = "yuyutei_candidates"
    __table_args__ = (
        UniqueConstraint("set_slug", "product_id", name="uq_yuyutei_candidates_set_slug_product"),
        CheckConstraint(
            "match_status IN ('unmatched', 'family_matched', 'print_matched', "
            "'identity_conflict')",
            name="ck_yuyutei_candidates_match_status",
        ),
        CheckConstraint(
            "matched_card_print_id IS NULL OR match_status = 'print_matched'",
            name="ck_yuyutei_candidates_print_requires_print_matched",
        ),
        CheckConstraint(
            "availability IS NULL OR availability IN ('in_stock', 'out_of_stock', "
            "'unknown_present_marker')",
            name="ck_yuyutei_candidates_availability",
        ),
        CheckConstraint(
            "price_jpy IS NULL OR price_jpy > 0",
            name="ck_yuyutei_candidates_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("yuyutei_discovery_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    set_slug: Mapped[str] = mapped_column(String(32), index=True)
    product_id: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(String(1024))
    detected_card_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detected_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_listing_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_status: Mapped[str] = mapped_column(
        String(32), default="unmatched", server_default="unmatched", index=True
    )
    matched_card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="SET NULL"), nullable=True
    )
    match_explanation_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
