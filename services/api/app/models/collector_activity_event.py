from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EVENT_SOURCES = (
    "collection",
    "wishlist",
    "grading",
    "market_signal",
    "market_report",
    "backup",
    "workflow",
    "note",
)


class CollectorActivityEvent(Base):
    """An append-only, read-only log entry recorded whenever something
    notable happens elsewhere in the app (collection/wishlist/grading
    changes, market signal or report activity, backup/restore, workflow
    runs, or a note being created). All link columns are nullable and SET
    NULL on delete - the event is a historical record and must survive the
    thing it references being removed."""

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
