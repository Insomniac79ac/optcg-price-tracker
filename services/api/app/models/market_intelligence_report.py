from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MarketIntelligenceReport(Base):
    __tablename__ = "market_intelligence_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    report_date: Mapped[date] = mapped_column(Date, index=True)

    total_opportunities: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    highest_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    buy_opportunities_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sell_opportunities_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    momentum_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    drop_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data_quality_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    owned_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    portfolio_market_floor_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_retail_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_liquidation_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_pnl_vs_market_floor_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    top_buy_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_sell_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_momentum_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_drop_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_owned_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_data_quality_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    report_payload_json: Mapped[dict] = mapped_column(JSON)
