from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalyticsDigestReport(Base):
    __tablename__ = "analytics_digest_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    valuation_mode: Mapped[str] = mapped_column(String(32), index=True)

    collection_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graded_adjusted_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    portfolio_risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    wishlist_target_hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    buy_review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sell_review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    grading_roi_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    digest_payload_json: Mapped[dict] = mapped_column(JSON)
