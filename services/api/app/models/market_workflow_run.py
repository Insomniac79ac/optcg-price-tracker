from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MarketWorkflowRun(Base):
    __tablename__ = "market_workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial_success', 'failed')",
            name="ck_market_workflow_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default="running", index=True
    )
    source: Mapped[str] = mapped_column(String(16))
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_telegram: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    price_refresh_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_refresh_runs.id", ondelete="SET NULL"), nullable=True
    )
    portfolio_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_valuation_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    market_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="SET NULL"), nullable=True
    )
    signal_events_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    signal_events_updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    signal_events_resolved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    telegram_digest_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    warnings_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
