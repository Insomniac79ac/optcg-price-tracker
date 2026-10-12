"""One verified R2 copy of one official card image version, per print.

Insert-only by contract: application code never updates or deletes a row. A
new Bandai image version (a new ``image_url``) gets a new row beside the old
one, and the object it names is content-addressed, so an old version's object
is never overwritten either.

Not imported by ``app.models``: collectors import that package, and this table
is API-side presentation state only. ``alembic/env.py`` and the read path
import this module explicitly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CardPrintImageAsset(Base):
    __tablename__ = "card_print_image_assets"
    __table_args__ = (
        UniqueConstraint("card_print_id", "source_url", name="uq_card_print_image_assets_print_source"),
        CheckConstraint("length(sha256) = 64", name="ck_card_print_image_assets_sha256"),
        CheckConstraint("byte_size > 0 AND width > 0 AND height > 0", name="ck_card_print_image_assets_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_print_id: Mapped[int] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # The exact official URL fetched, including Bandai's ?version suffix.
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_control: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(64), nullable=False)
    mirrored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
