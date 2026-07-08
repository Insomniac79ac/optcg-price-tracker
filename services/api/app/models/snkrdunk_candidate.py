from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MATCH_STATUSES = ("pending", "auto_matched", "needs_review", "rejected")


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
