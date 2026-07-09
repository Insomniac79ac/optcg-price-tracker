from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUN_STATUSES = ("running", "completed", "completed_with_warnings", "failed")


class PriceRefreshRun(Base):
    __tablename__ = "price_refresh_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'failed')",
            name="ck_price_refresh_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    scraping_mode: Mapped[str] = mapped_column(String(16))
    source_filter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    limit_count: Mapped[int] = mapped_column(Integer)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mappings_checked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_parsed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_inserted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    observations_skipped_duplicate: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    mappings_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
