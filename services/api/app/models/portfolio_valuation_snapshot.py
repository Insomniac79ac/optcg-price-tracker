from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


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
    graded_adjusted_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pnl_vs_graded_adjusted_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_using_graded_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_using_raw_fallback: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_missing_graded_adjusted_value: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
