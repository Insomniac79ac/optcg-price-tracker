from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

REVIEW_STATUSES = ("approved", "needs_review", "rejected")


class SourceCardMapping(Base):
    __tablename__ = "source_card_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "source_url", name="uq_source_card_mappings_source_url"),
        Index("ix_source_card_mappings_card_id_source_id", "card_id", "source_id"),
        CheckConstraint(
            "review_status IN ('approved', 'needs_review', 'rejected')",
            name="ck_source_card_mappings_review_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_card_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    review_status: Mapped[str] = mapped_column(
        String(32), default="approved", server_default="approved", index=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
