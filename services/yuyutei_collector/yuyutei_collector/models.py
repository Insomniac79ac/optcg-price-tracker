"""Minimal ORM mappings onto tables owned by services/api/app/models - this
service only reads Card/Source/CardPrint/SourceCardMapping and writes
RawSnapshot/PriceObservation, so only the columns it actually touches are
declared here. Consistent with services/worker/worker/models.py, which
independently declares its own minimal subset of the same physical tables
rather than importing app.models directly - each Railway service ships its
own dependency-isolated image.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
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
    treatment: Mapped[str] = mapped_column(String(64))
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
