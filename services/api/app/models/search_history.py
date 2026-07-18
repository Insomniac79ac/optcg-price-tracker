from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SearchHistory(Base):
    """One row per successful GET /search call - a lightweight log used to
    surface "recently searched" suggestions, not a source of truth for
    anything else. Never written to on an empty/invalid (400) query."""

    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(255), index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
