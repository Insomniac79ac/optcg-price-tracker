from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ImportValidationReport(Base):
    """A stored record of one POST /admin/import-validation/{import_type}
    call - see app.services.import_validation. Never written by anything
    other than that validation endpoint; this table is purely a read-side
    history of past validation runs (GET .../reports|reports/{id}), so an
    admin can tell whether a given upload was ever validated clean before a
    real import ran against it."""

    __tablename__ = "import_validation_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    import_type: Mapped[str] = mapped_column(String(32), index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, index=True)
    strict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warning_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    report_payload_json: Mapped[dict] = mapped_column(JSON)
