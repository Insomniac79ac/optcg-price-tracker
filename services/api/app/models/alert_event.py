from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EVENT_TYPES = (
    "price_up",
    "price_down",
    "yuyutei_buy_up",
    "stock_out",
    "refresh_failed",
    "owned_card_above_target_sell",
    "owned_card_below_cost_basis",
    "portfolio_value_up",
    "portfolio_value_down",
)

EVENT_STATUSES = ("pending", "sent", "failed", "skipped_duplicate")


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
