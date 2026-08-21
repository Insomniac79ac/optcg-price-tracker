"""Append-only daily record of the exact-print Market Index *as actually
calculated at that point in time*.

Why this table exists
----------------------
app.services.market_index / print_market_index are compute-on-read: every
index value is re-derived from price_observations on each call (see
market_index's "Compute-on-read, not persisted"). That keeps the calculation
honest about current evidence, but it also means a later change to
INDEX_VERSION, to a SOURCE_SEMANTICS rule, or to a freshness threshold
silently rewrites every value Atlas has ever displayed. This table is the
opposite guarantee: one immutable row per (print, UTC day) recording the
number Atlas showed, the ruleset versions that produced it, and the source
evidence it was derived from.

Append-only, by contract
-------------------------
There is deliberately no UPDATE path anywhere in the codebase for this table
(see app.snapshot_market_index, which inserts with ON CONFLICT DO NOTHING and
never upserts). A re-run on the same UTC day is a no-op, never a correction:
the first snapshot of a day is the one Atlas stands behind. Postgres will of
course still permit a hand-written UPDATE - the guarantee here is a code-level
convention plus the absence of any writer that could violate it, not a
database privilege.

No backfill
------------
Rows are only ever written forward, for the current UTC day. Reconstructing a
past date is not merely discouraged, it is not computable: _compute_index_fields
applies YUYUTEI_SELL_MAX_AGE_DAYS/SNKRDUNK_FLOOR_MAX_AGE_DAYS relative to the
`now` it is handed, and SOURCE_SEMANTICS_VERSION has never been bumped, so
there is no historical ruleset to replay a past day under. A "reconstructed"
row would therefore claim Atlas showed a value it demonstrably never showed.
The first snapshot_date is the implementation date and that is the correct,
honest start of the series.

Why provenance is JSON and not child rows
-------------------------------------------
The whole point of the row is that a later methodology change cannot rewrite
it. A normalized contributions table would invite exactly the migration that
breaks that guarantee - the day someone adds a NOT NULL column with a
backfilled default, historical contributions silently acquire a value Atlas
never computed. Everything that is filtered or charted is a real scalar column
below; `provenance` is a write-once archive, never a query target. See
docs/market_index_history_audit_2026-08-21 for the full comparison.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

COVERAGE_STATUSES = ("full", "limited", "none")
CONFIDENCE_LEVELS = ("high", "medium", "low")


class MarketIndexSnapshot(Base):
    __tablename__ = "market_index_snapshots"
    __table_args__ = (
        # One snapshot per print per UTC day - the idempotency identity the
        # snapshot job's ON CONFLICT DO NOTHING keys on (see
        # app.snapshot_market_index). Deliberately NOT a content hash: prices
        # here are frequently flat for days at a time (a staging print has
        # been the same two numbers every day since collection began), and a
        # content-keyed identity would collapse those genuinely distinct days
        # into one row, destroying exactly the history this table exists to
        # keep.
        UniqueConstraint(
            "card_print_id", "snapshot_date", name="uq_market_index_snapshots_print_date"
        ),
        # The read path: one print's index over time, newest or oldest first.
        # (card_print_id, calculated_at) rather than the unique constraint's
        # (card_print_id, snapshot_date) because calculated_at is the exact
        # instant and the column any future range query/chart will order by;
        # snapshot_date exists to define identity, not to be sorted on.
        Index(
            "ix_market_index_snapshots_print_calculated", "card_print_id", "calculated_at"
        ),
        CheckConstraint(
            "coverage_status IN ('full', 'limited', 'none')",
            name="ck_market_index_snapshots_coverage_status",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_market_index_snapshots_confidence",
        ),
        # index_value_jpy is NULL if and only if no source was eligible.
        # Written as an equality between two boolean expressions (not a pair
        # of one-way implications) so neither half can drift: a NULL value
        # with coverage 'limited', and a non-NULL value with coverage 'none',
        # are both rejected. Mirrors _compute_index_fields, where
        # index_value=None and coverage_status="none" are set together in the
        # same branch and can never disagree at the source.
        CheckConstraint(
            "(index_value_jpy IS NULL) = (coverage_status = 'none')",
            name="ck_market_index_snapshots_value_presence",
        ),
        # The two range endpoints are one value, split across two columns for
        # queryability - so they are present together or absent together,
        # never half a range. Same both-directions equality form as the value
        # presence check above, for the same reason: a one-way implication
        # would leave the other half unguarded. _compute_index_fields already
        # builds SourcePriceRangeOut with both endpoints or returns None, so
        # this pins an invariant the calculation already holds rather than
        # imposing a new one.
        CheckConstraint(
            "(source_price_range_low_jpy IS NULL) = "
            "(source_price_range_high_jpy IS NULL)",
            name="ck_market_index_snapshots_range_pairing",
        ),
        # Ordering, checked only when the pair is present (the NULL branch is
        # already fully owned by the pairing check above - restating it here
        # would give two constraints authority over the same condition). Low
        # is allowed to EQUAL high: two eligible sources agreeing exactly is a
        # real, measured zero spread, not a degenerate row, and
        # _compute_index_fields emits it as such.
        CheckConstraint(
            "source_price_range_low_jpy IS NULL "
            "OR source_price_range_low_jpy <= source_price_range_high_jpy",
            name="ck_market_index_snapshots_range_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # RESTRICT, matching how PriceObservation guards its own print lineage: a
    # print that has been snapshotted is a print whose history Atlas has
    # published, and deleting it out from under that history would leave the
    # series silently truncated rather than loudly blocked.
    card_print_id: Mapped[int] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # The exact instant the index was calculated, copied verbatim from the
    # MarketIndexOut payload. Every row written by one job run shares one
    # value - get_market_index_for_prints takes a single `now` for the whole
    # batch - so a day's snapshots are a coherent cross-section, not a smear
    # across the job's runtime.
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # calculated_at's UTC calendar date. Stored as its own column rather than
    # derived in a functional index so the unique constraint above is plain,
    # portable DDL that behaves identically on Postgres and on the SQLite the
    # test suite runs against.
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # NULL is a real, meaningful result (no eligible source), not missing
    # data - see ck_market_index_snapshots_value_presence.
    index_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)

    # SourcePriceRangeOut flattened into two columns rather than nested in
    # provenance: this is charted and filtered, and it is always either
    # exactly two integers or absent. Both NULL together whenever fewer than
    # two sources were eligible (there is no spread to report between one
    # value and itself).
    source_price_range_low_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_price_range_high_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The two rulesets that produced the value above, copied from the payload
    # as emitted rather than re-read from the constants at write time - the
    # snapshot records what the calculation actually reported, not what this
    # module believes the current version to be. Versioned independently
    # because the combination algorithm and the per-source rules change on
    # different cadences (see source_semantics' module docstring).
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Freshness bounds of the sources that ACTUALLY COUNTED toward
    # index_value_jpy - both derived from the eligible contributors only, so
    # the pair brackets the evidence behind the number rather than describing
    # observations that were excluded. Note this makes
    # freshest_eligible_source_at deliberately different from
    # MarketIndexOut.freshest_observation_at, which spans every source_value
    # including ineligible ones; see app.snapshot_market_index for the
    # derivation. Both NULL when nothing was eligible.
    freshest_eligible_source_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stalest_eligible_source_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Write-once archive of the Market Index evidence, shaped
    # {"source_values": [...], "auxiliary_values": [...]} - the serialized
    # MarketIndexSourceValueOut payloads exactly as the API emitted them.
    # Deliberately keeps ineligible and constrained values (a SNKRDUNK floor
    # at the platform minimum, a stale Yuyu-Tei sell): they are the reason a
    # historical index was `limited` rather than `full`, and dropping them
    # would leave a past coverage_status unexplainable. JSONB on Postgres for
    # the storage/indexing it allows a future reader; plain JSON on SQLite so
    # the test suite exercises the same column.
    provenance: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
