from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RULE_TYPES = (
    "price_change_pct",
    "yuyutei_buy_change_pct",
    "stock_status_change",
    "refresh_failed",
    "owned_card_above_target_sell",
    "owned_card_below_cost_basis",
    "portfolio_value_change_pct",
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
