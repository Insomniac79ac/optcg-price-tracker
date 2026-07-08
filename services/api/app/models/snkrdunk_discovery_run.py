from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUN_STATUSES = (
    "running",
    "completed",
    "completed_with_warnings",
    "blocked",
    "failed",
    "manual_import",
)


class SnkrdunkDiscoveryRun(Base):
    __tablename__ = "snkrdunk_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'blocked', "
            "'failed', 'manual_import')",
            name="ck_snkrdunk_discovery_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")
    seed_url: Mapped[str] = mapped_column(String(1024))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_matched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
