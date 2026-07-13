from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MAIN_DASHBOARD_KEY = "main_dashboard"


class DashboardPreference(Base):
    __tablename__ = "dashboard_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    preference_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    preference_value_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
