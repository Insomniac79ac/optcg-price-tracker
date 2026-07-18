from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LOCK_STATUSES = ("active", "released", "expired")


class JobLock(Base):
    """Mutual-exclusion lock for background jobs/admin actions that must
    never run concurrently (price refresh, market workflow, snapshot jobs,
    report generation, digest sending, retention pruning, backup restore) -
    see app.services.job_locks for acquire/release semantics and 'Worker job
    concurrency locking' in docs/operations.md.

    One row per lock_name (enforced by the unique index below); a lock is
    "held" by rewriting that same row (owner_id/acquired_at/expires_at/
    status) rather than inserting a new row per acquisition - the unique
    constraint on lock_name plus a compare-and-swap UPDATE is what makes
    acquisition atomic (see acquire_lock)."""

    __tablename__ = "job_locks"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'released', 'expired')", name="ck_job_locks_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lock_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(255), index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", index=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
