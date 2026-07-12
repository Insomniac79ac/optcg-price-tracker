from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DIGEST_SEND_STATUSES = ("pending", "sent", "skipped", "failed")


class MarketReportDigestSend(Base):
    __tablename__ = "market_report_digest_sends"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "destination", name="uq_market_report_digest_sends_report_destination"
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')",
            name="ck_market_report_digest_sends_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("market_intelligence_reports.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(
        String(32), default="telegram", server_default="telegram"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
