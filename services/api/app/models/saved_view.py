from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SAVED_VIEW_SCOPES = ("collector", "admin", "analytics", "market")
SAVED_VIEW_DENSITIES = ("compact", "comfortable")


class SavedView(Base):
    """A single-user saved filter/sort/column preset for a dense list page
    (e.g. "Review Buy" on /analytics/buy-decisions). There is no user_id -
    this is one shared, global preset store (like dashboard_preferences),
    not per-account rows; the app has no multi-user accounts to scope by."""

    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("route_path", "view_type", "name", name="uq_saved_views_route_type_name"),
        CheckConstraint(
            "scope IN ('collector', 'admin', 'analytics', 'market')",
            name="ck_saved_views_scope",
        ),
        CheckConstraint(
            "density IN ('compact', 'comfortable')",
            name="ck_saved_views_density",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_path: Mapped[str] = mapped_column(String(255), index=True)
    view_type: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="collector", server_default="collector", index=True)

    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    columns_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    density: Mapped[str] = mapped_column(String(16), default="compact", server_default="compact")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
