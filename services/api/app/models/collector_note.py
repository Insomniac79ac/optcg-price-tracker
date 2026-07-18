from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

NOTE_TYPES = (
    "general",
    "collection",
    "wishlist",
    "grading",
    "market_signal",
    "opportunity",
    "card",
    "backup",
    "report",
)


class CollectorNote(Base):
    """A free-text note the collector attaches to themselves or to one other
    record (card, collection item, wishlist item, grading submission, market
    signal event, or market report). All link columns are nullable and
    SET NULL on delete - a note is a standalone record of what the collector
    was thinking, so it must survive the thing it was about being removed."""

    __tablename__ = "collector_notes"
    __table_args__ = (
        CheckConstraint(
            "note_type IN ('general', 'collection', 'wishlist', 'grading', "
            "'market_signal', 'opportunity', 'card', 'backup', 'report')",
            name="ck_collector_notes_note_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    note_type: Mapped[str] = mapped_column(
        String(32), default="general", server_default="general", index=True
    )
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collection_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    wishlist_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("wishlist_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    grading_submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("grading_submissions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    market_signal_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_signal_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    market_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
