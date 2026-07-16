from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


class AppLogEvent(Base):
    """Structured production log/event row, written best-effort by
    app.services.app_logging (api) and worker.app_logging (worker) - see
    'Observability and logs' in docs/operations.md. Never stores secrets or
    request bodies; context_json/traceback are sanitized before saving."""

    __tablename__ = "app_log_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error', 'critical')",
            name="ck_app_log_events_level",
        ),
        Index("ix_app_log_events_related_entity", "related_entity_type", "related_entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(16), index=True)
    service: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
