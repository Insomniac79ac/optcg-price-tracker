"""Internal encoding lineage; both raw bodies remain protected from retention."""

from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class RawSnapshotDictionary(Base):
    __tablename__ = "raw_snapshot_dictionaries"
    __table_args__ = (
        Index("ix_raw_dictionary_base", "base_snapshot_id"),
        Index("ix_raw_dictionary_created", "created_at"),
        CheckConstraint("base_snapshot_id < id", name="ck_raw_dictionary_older_base"),
        CheckConstraint(
            "original_bytes BETWEEN 1 AND 8388608 AND encoded_bytes > 0",
            name="ck_raw_dictionary_bounds",
        ),
    )
    id: Mapped[int] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="RESTRICT"),
        primary_key=True,
        autoincrement=False,
    )
    base_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="RESTRICT"),
    )
    original_sha256: Mapped[str] = mapped_column(String(64))
    base_sha256: Mapped[str] = mapped_column(String(64))
    original_bytes: Mapped[int] = mapped_column(Integer)
    encoded_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expanded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
