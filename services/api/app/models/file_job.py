from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

FILE_JOB_TYPES = (
    "collection_import",
    "wishlist_import",
    "collection_export",
    "wishlist_export",
    "backup_export",
    "backup_validate",
    "backup_restore",
)

FILE_JOB_STATUSES = ("queued", "running", "success", "failed", "cancelled")


class FileJob(Base):
    """Tracks one background import/export/backup operation processed out of
    the request/response cycle - see 'Large import/export jobs' in
    docs/operations.md, GET/POST /file-jobs*, and app.services.file_jobs.

    user_id scopes a job to the user who created it (collection_import/
    export, wishlist_import/export, via the existing per-user bearer-token
    auth) - not part of the original spec's field list, but added because
    without it any signed-in user could list/download/cancel any other
    user's (or the admin's) file job by id; see app.api.file_jobs's
    access-control dependency. It's null for admin-only job types
    (backup_export/validate/restore), which only an X-Admin-Token request
    can create or see.
    """

    __tablename__ = "file_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('collection_import', 'wishlist_import', 'collection_export', "
            "'wishlist_export', 'backup_export', 'backup_validate', 'backup_restore')",
            name="ck_file_jobs_job_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed', 'cancelled')",
            name="ck_file_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    errors_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
