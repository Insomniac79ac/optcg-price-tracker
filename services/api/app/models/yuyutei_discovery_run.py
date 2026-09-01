from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# running: the run is in flight (or died without ever finishing - a row left
#   in this state is a crashed run, not a successful one).
# completed: every requested slug was enumerated and persisted.
# denied: the source answered 401/403/405/429/451/503, or served a challenge.
#   The run stopped at that point and was never retried - see
#   yuyutei_collector.discovery_probe._DENIAL_STATUSES for the posture.
# failed: an internal error. error_message carries it.
#
# Deliberately NOT the snkrdunk_discovery_runs vocabulary: that one carries
# 'manual_import' and 'blocked' states belonging to a CSV import path and an
# approval workflow this pipeline does not have.
RUN_STATUSES = ("running", "completed", "denied", "failed")


class YuyuteiDiscoveryRun(Base):
    """One bounded enumeration of Yuyu-Tei category listing pages.

    A run records what was ASKED for and what was actually SEEN, so a later
    reader can tell a set that genuinely holds 80 products from a set whose
    enumeration was cut short by a budget or a denial. Every counter here is
    measured during the run; none is configured or expected in advance.

    This table is written by services/yuyutei_collector only. The API owns the
    schema and reads it; it never triggers discovery.
    """

    __tablename__ = "yuyutei_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'denied', 'failed')",
            name="ck_yuyutei_discovery_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", server_default="running")

    # The slugs the operator explicitly asked for. Discovery never infers this
    # list from a source index, so it is a faithful record of the request.
    # MutableList mirrors canonical_cards.colors: a plain JSON column would not
    # notice an in-place .append() and would silently emit no UPDATE.
    requested_set_slugs: Mapped[list | None] = mapped_column(
        MutableList.as_mutable(JSON), nullable=True
    )

    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Distinct (series, product_id) products kept after foreign-series
    # filtering - i.e. what discovery actually considered, not raw anchors.
    products_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidates_written: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    foreign_series_filtered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_products: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unparseable_codes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Why enumeration stopped, when it stopped for a reason worth recording
    # (budget reached, page limit reached, source denial). NULL means it ran to
    # the natural end of every requested slug.
    stopped_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-slug measurements, keyed by slug. The run-level counters above are
    # sums; this is where a reader sees that op13 hit its cap while eb01 did
    # not. Written once at the end of a run and never queried against, so it
    # is stored as an archive rather than promoted to columns - same posture as
    # market_index_snapshots.provenance.
    per_slug_metrics_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )
