"""Immutable evidence for a nonempty, atomically completed snapshot day."""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MarketIndexSnapshotCompletion(Base):
    __tablename__ = "market_index_snapshot_completions"
    __table_args__ = (
        UniqueConstraint("snapshot_date", name="uq_market_index_completion_date"),
        CheckConstraint(
            "expected_print_count > 0 AND snapshot_row_count = expected_print_count",
            name="ck_market_index_completion_counts",
        ),
        CheckConstraint(
            "index_version > 0 AND source_semantics_version > 0",
            name="ck_market_index_completion_versions",
        ),
        CheckConstraint(
            "digest_version = 1", name="ck_market_index_completion_digest_version"
        ),
        CheckConstraint(
            "length(selected_print_ids_digest) = 64 AND length(snapshot_content_digest) = 64",
            name="ck_market_index_completion_digest_length",
        ),
        CheckConstraint(
            "length(trim(run_id)) > 0", name="ck_market_index_completion_run_id"
        ),
        CheckConstraint(
            "receipt_kind = 'atomic'", name="ck_market_index_completion_kind"
        ),
        CheckConstraint(
            "completed_at >= calculated_at", name="ck_market_index_completion_time"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_print_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_print_ids_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    receipt_kind: Mapped[str] = mapped_column(String(16), nullable=False)
