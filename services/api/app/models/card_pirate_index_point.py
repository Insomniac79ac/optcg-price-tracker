"""One persisted daily point of the Card Pirate Index.

The Card Pirate Index is the overall One Piece card-market series described in
`docs/card_pirate_index.md`, which is the methodology of record and the sole
authority for everything below. This module is the *storage* for that series
and nothing else: it contains no estimator, no chaining logic and no job. The
frozen v1 methodology (METHODOLOGY_VERSION = 1, BASE_VALUE = 1000,
MIN_CONSTITUENTS = 30, an unconditional +/-ln(1.25) per-print daily cap, and
the arithmetic mean of capped log returns) lives in that document and, when
step 4 of its rollout lands, in app.services.card_pirate_index.

WHY THIS TABLE EXISTS AT ALL
-----------------------------
The same argument market_index_snapshot.py already makes, one layer up. A
read-time index would let a later tweak to the cap or to MIN_CONSTITUENTS
silently rewrite every level Atlas has ever charted, including the one in a
screenshot a collector took last month. Persisting the aggregate makes each
published point immutable evidence of what the index actually said that day.

WHY THIS TABLE IS NOT market_index_snapshots, AND MAY BE REPLAYED
------------------------------------------------------------------
The sibling table forbids backfill because a past Market Index is not
computable - _compute_index_fields applies freshness windows relative to the
`now` it is handed. This table has no such dependency: its inputs are the
immutable, already-archived market_index_snapshots.index_value_jpy values, so
a point is a pure, deterministic, idempotent function of rows that can never
change. That is why a deterministic replay to seed 2026-09-03 onward is
legitimate here and prohibited there, and why the future job can carry a
--verify mode that recomputes the archive and diffs it against stored points.
See docs/card_pirate_index.md section 8.2.

APPEND-ONLY, AND WHAT THAT DOES AND DOES NOT GUARANTEE
--------------------------------------------------------
There is deliberately no UPDATE path for this table anywhere in the codebase,
matching MarketIndexSnapshot. A re-run of a day is a no-op via ON CONFLICT DO
NOTHING on the natural key, never a correction.

The carry (see below) is a self-reference, so the honest statement of its
integrity is worth making precisely:

  * The normal insert path can only carry from a point that ALREADY EXISTS -
    the foreign key is immediate and not deferrable, so a forward reference is
    rejected outright rather than left dangling.
  * Combined with "no UPDATE writer", that makes the carry chain acyclic by
    construction: a fresh INSERT can only point backwards.
  * It is NOT a schema-level guarantee. A hand-written UPDATE can still build
    a two-row cycle; this was measured, and it succeeded. No trigger is added
    to prevent it, because a trigger would be defending against a writer that
    does not exist while adding a permanent cost to one that does.
  * The future --verify replay is the backstop: it must reject a cycle and any
    carry whose target date is not strictly earlier than the carrying row's.

Postgres will of course still permit a hand-written UPDATE - the guarantee is
a code-level convention plus the absence of any writer that could violate it,
exactly as this table's sibling already concedes for itself.

POINT IDS ARE INTERNAL
-----------------------
`id` and `carried_from_point_id` are surrogate keys and MUST NOT become part
of the API contract. They are not stable across a drop-and-replay rebuild
(measured: the same three logical points came back as 7, 8, 9 instead of
1, 2, 3), while the natural key is. Two rules follow, and both are binding on
the code that has yet to be written: the public payload exposes the carry as
`carried_from_point_date`, resolved by join, and --verify compares the carry's
RESOLVED NATURAL KEY rather than the raw integer. See section 8.6 of the
methodology document.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The scope grammar. 'overall' + '' is the only scope written today; 'set' and
# 'rarity' are the section 14 extension point, and exist here so a sub-index
# needs no migration - only a GROUP BY on a constituent attribute.
SCOPE_KINDS = ("overall", "set", "rarity")

# Why a point carries no value. Both are computed states, not errors.
UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS = "insufficient_constituents"
UNPUBLISHABLE_MIXED_VERSION_DAY = "mixed_version_day"

# The base level of an *initial* segment, frozen at methodology v1. A carried
# segment does not use this - it starts at whatever the previous segment
# finished on, which is the whole point of section 5.
BASE_VALUE = 1000


class CardPirateIndexPoint(Base):
    __tablename__ = "card_pirate_index_points"
    __table_args__ = (
        # --- identity ---------------------------------------------------
        #
        # One point per scope per day per methodology version - the identity
        # the future job's ON CONFLICT DO NOTHING keys on, and the read path's
        # index (scope first, point_date last for the range scan).
        #
        # index_version is DELIBERATELY NOT a key column. Two rows for one day
        # under two index_versions is an error, not a legal pair of rows: a day
        # belongs to exactly one segment. Leaving index_version out makes that
        # unrepresentable instead of merely discouraged.
        UniqueConstraint(
            "scope_kind",
            "scope_key",
            "methodology_version",
            "point_date",
            name="uq_cpi_points_point",
        ),
        # EXISTS SOLELY AS THE FOREIGN KEY TARGET BELOW, and is redundant for
        # reads - `id` alone is already unique. It is the price of enforcing
        # the carry's same-scope and identical-level rules in the database
        # rather than in application code, and it is worth paying: the
        # alternative is a trigger or an unenforced convention.
        #
        # admin_db_index_audit will flag this as unused. That is expected, and
        # this comment is the answer.
        UniqueConstraint(
            "id",
            "scope_kind",
            "scope_key",
            "index_value",
            name="uq_cpi_points_carry_target",
        ),
        # --- the segment carry ------------------------------------------
        #
        # Composite on purpose. ONE constraint proves three things at once:
        # the target exists, it is in the SAME scope, and its index_value is
        # IDENTICAL to this row's. That is the entire "carried base level must
        # equal the referenced point's level" rule, declared rather than
        # checked in Python.
        #
        # MATCH SIMPLE (the default) skips the whole constraint when ANY
        # referencing column is NULL. That is exactly the behaviour wanted for
        # carried_from_point_id IS NULL, and it is safe here only because
        # ck_cpi_points_base_has_value and ck_cpi_points_carry_requires_base
        # together make index_value NOT NULL whenever the carry is set. The
        # two must be read together; neither is sufficient alone. MATCH FULL
        # would be WRONG: it rejects any partially-NULL tuple, and every
        # ordinary row has NOT NULL scope columns beside a NULL carry.
        #
        # ON UPDATE RESTRICT makes a carried-from point's published level
        # immutable at the database level, not merely by convention - the one
        # place the append-only contract is actually enforced rather than
        # assumed. ON DELETE RESTRICT means the chain cannot be silently
        # truncated, matching MarketIndexSnapshot's RESTRICT on card_print_id.
        ForeignKeyConstraint(
            ["carried_from_point_id", "scope_kind", "scope_key", "index_value"],
            [
                "card_pirate_index_points.id",
                "card_pirate_index_points.scope_kind",
                "card_pirate_index_points.scope_key",
                "card_pirate_index_points.index_value",
            ],
            name="fk_cpi_points_carried_from",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        # Only a base row opens a segment, so only a base row can carry.
        CheckConstraint(
            "carried_from_point_id IS NULL OR is_base",
            name="ck_cpi_points_carry_requires_base",
        ),
        # A row cannot be its own carry source. The foreign key alone would
        # HAPPILY accept it - a row referencing itself satisfies the FK - so
        # this is the constraint that actually forbids it.
        CheckConstraint(
            "carried_from_point_id IS NULL OR carried_from_point_id <> id",
            name="ck_cpi_points_carry_not_self",
        ),
        # An initial base - and only an initial base - starts at BASE_VALUE.
        # A carried base starts wherever the previous segment finished, so it
        # is exempt by the carried_from_point_id IS NOT NULL branch.
        CheckConstraint(
            "NOT is_base OR carried_from_point_id IS NOT NULL OR index_value = 1000",
            name="ck_cpi_points_initial_base_is_base_value",
        ),
        # --- scope ------------------------------------------------------
        CheckConstraint(
            "scope_kind IN ('overall', 'set', 'rarity')",
            name="ck_cpi_points_scope_kind",
        ),
        # Both-directions equality, not a one-way implication: an 'overall'
        # row with a key, and a 'set' row without one, are both rejected.
        CheckConstraint(
            "(scope_kind = 'overall') = (scope_key = '')",
            name="ck_cpi_points_scope_key_pairing",
        ),
        # --- publishability ---------------------------------------------
        #
        # index_value is NULL if and only if the day could not be published.
        # Same both-directions form as the sibling table's value-presence
        # check, for the same reason.
        CheckConstraint(
            "(index_value IS NULL) = (unpublishable_reason IS NOT NULL)",
            name="ck_cpi_points_value_presence",
        ),
        # A base row is a level carry (or the initial 1000): it always has a
        # value. This is also what closes the MATCH SIMPLE hole above.
        CheckConstraint(
            "NOT is_base OR index_value IS NOT NULL",
            name="ck_cpi_points_base_has_value",
        ),
        # A boundary has no calculated return. Section 5.1 rule 5, verbatim.
        CheckConstraint(
            "NOT is_base OR (chain_link_log_return IS NULL"
            " AND prior_point_date IS NULL"
            " AND step_days IS NULL"
            " AND constituent_count = 0)",
            name="ck_cpi_points_base_has_no_step",
        ),
        # A published non-base point came from a step, and a step has a prior
        # point. An unpublishable one is exempt: it may have failed before a
        # prior point was resolved.
        CheckConstraint(
            "is_base OR index_value IS NULL OR prior_point_date IS NOT NULL",
            name="ck_cpi_points_step_requires_prior",
        ),
        CheckConstraint(
            "step_days IS NULL OR step_days >= 1",
            name="ck_cpi_points_step_days_positive",
        ),
        # --- breadth ----------------------------------------------------
        #
        # Constituents are the prints that produced a return this step;
        # eligible prints are those merely valued on point_date. Entrants and
        # leavers move the second without moving the first, which is the whole
        # chain-link property (section 3.1).
        CheckConstraint(
            "constituent_count <= eligible_print_count",
            name="ck_cpi_points_constituents_le_eligible",
        ),
        # Breadth is present exactly when a constituent set existed. Base
        # rows, mixed-version days and empty steps all have
        # constituent_count = 0 and NULL breadth; an insufficient_constituents
        # day still reports its n, because n < 30 is a real measurement.
        CheckConstraint(
            "(movers_up IS NULL) = (constituent_count = 0)",
            name="ck_cpi_points_breadth_presence",
        ),
        # The four breadth counters are one fact in four columns, so they are
        # present together or absent together. WITHOUT THIS, movers_up = 1
        # beside a NULL movers_down makes the sum below evaluate to NULL - and
        # a CHECK passes on NULL. The hole is real; this closes it.
        CheckConstraint(
            "(movers_down IS NULL) = (movers_up IS NULL)"
            " AND (movers_flat IS NULL) = (movers_up IS NULL)"
            " AND (capped_count IS NULL) = (movers_up IS NULL)",
            name="ck_cpi_points_movers_pairing",
        ),
        CheckConstraint(
            "movers_up IS NULL"
            " OR movers_up + movers_down + movers_flat = constituent_count",
            name="ck_cpi_points_movers_sum",
        ),
        # Capping never changes a return's sign, so a capped constituent is
        # still counted as a mover - it can never exceed the panel.
        CheckConstraint(
            "capped_count IS NULL OR capped_count <= constituent_count",
            name="ck_cpi_points_capped_le_constituents",
        ),
        CheckConstraint(
            "constituent_count >= 0 AND eligible_print_count >= 0"
            " AND (movers_up IS NULL OR (movers_up >= 0 AND movers_down >= 0"
            " AND movers_flat >= 0 AND capped_count >= 0))",
            name="ck_cpi_points_counts_non_negative",
        ),
    )

    # Surrogate, and internal. See the module docstring: not stable across a
    # rebuild, never part of the API contract.
    id: Mapped[int] = mapped_column(primary_key=True)

    # The section 14 extension point, present from day one so a set- or
    # rarity-level sub-index needs no migration. 'overall' + '' today.
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Three versions, three owners (section 5). methodology_version is this
    # index's own and is copied from the constant AS IT WAS AT CALCULATION
    # TIME - exactly as snapshot_market_index.build_snapshot_row copies
    # index_version from the emitted payload rather than re-reading the
    # constant, so a later release cannot relabel an old point. The other two
    # are copied from the constituents, never set by this index.
    methodology_version: Mapped[int] = mapped_column(Integer, nullable=False)
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)

    point_date: Mapped[date] = mapped_column(Date, nullable=False)

    # NULL is a real, meaningful result (the day could not be published), not
    # missing data - see ck_cpi_points_value_presence. Numeric, not float:
    # the level is chain-linked over hundreds of steps and a binary float
    # would drift.
    index_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    # --- segment identity and the continuous-level carry (section 5) ---
    #
    # The visible level does NOT reset to 1000 at a version change. A boundary
    # closes the old segment and opens a new one whose base level equals the
    # previous segment's final published level.
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # The one column that represents the carry. NULL on an initial base and on
    # every ordinary row; on a carried base it names the exact prior point
    # whose published index_value was carried in.
    #
    # There is deliberately NO segment_base_kind column: the initial/carried
    # distinction is `carried_from_point_id IS NULL` and storing it twice would
    # create a column that can contradict its own source of truth. There is
    # likewise no carried_from_point_date column - that is one join away - and
    # no segment_base_value, because index_value on the base row IS the
    # carried level and the foreign key already proves it equals the source's.
    carried_from_point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- the step that produced this point ---
    #
    # prior_point_date is the prior AVAILABLE SNAPSHOT DAY, never the prior
    # calendar day. A missed cron run produces a real multi-day return with
    # step_days > 1, honestly labelled - that is not forward-fill, and no
    # value is invented.
    prior_point_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    step_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The step's mean capped log return. Log rather than percentage because
    # log returns are additive, so a chain-linked level is exp(sum of steps)
    # and rounding cannot accumulate directionally across hundreds of steps.
    chain_link_log_return: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 12), nullable=True
    )

    # --- breadth, so a flat day is legible rather than suspicious ---
    #
    # A genuinely quiet market day is real information, and the methodology
    # deliberately does NOT gate on a minimum number of movers. These columns
    # are what let a surface say "296 of 296 cards unchanged" out loud instead
    # of drawing a flat line with no explanation.
    constituent_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_print_count: Mapped[int] = mapped_column(Integer, nullable=False)
    movers_up: Mapped[int | None] = mapped_column(Integer, nullable=True)
    movers_down: Mapped[int | None] = mapped_column(Integer, nullable=True)
    movers_flat: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # How many constituents hit the +/-ln(1.25) daily cap. NOT
    # "winsorized_count": v1 rejects percentile winsorization outright (with
    # 230 zeros and one mover the empirical p99 is itself zero, so winsorizing
    # would clip away the only signal), and a column name implying otherwise
    # would misdescribe the methodology.
    capped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    unpublishable_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # The instant the point was calculated, and the instant the row landed.
    # Neither is reproducible by replay, so --verify must not compare them.
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
