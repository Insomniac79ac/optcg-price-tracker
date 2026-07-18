from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

GRADING_SUBMISSION_STATUSES = (
    "planned",
    "preparing",
    "submitted",
    "grading",
    "shipped_back",
    "received",
    "cancelled",
)


class GradingSubmission(Base):
    __tablename__ = "grading_submissions"
    __table_args__ = (
        CheckConstraint(
            "submission_status IN ('planned', 'preparing', 'submitted', 'grading', "
            "'shipped_back', 'received', 'cancelled')",
            name="ck_grading_submissions_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_items.id", ondelete="CASCADE"), index=True
    )
    grading_company: Mapped[str] = mapped_column(String(32), index=True)
    submission_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submission_status: Mapped[str] = mapped_column(
        String(32), default="planned", server_default="planned", index=True
    )
    declared_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grading_fee_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_fee_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insurance_fee_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    other_fee_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    final_grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cert_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    graded_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
