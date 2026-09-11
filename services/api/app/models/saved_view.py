from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SAVED_VIEW_SCOPES = ("collector", "admin", "analytics", "market")
SAVED_VIEW_DENSITIES = ("compact", "comfortable")


class SavedView(Base):
    """Personal preset. NULL owners preserve inaccessible legacy rows."""

    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("user_id", "route_path", "view_type", "name", name="uq_saved_views_owner_route_type_name"),
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

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
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
