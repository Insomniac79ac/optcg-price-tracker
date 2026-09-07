"""add card_pirate_index_points

The persistence foundation for the Card Pirate Index, the overall One Piece
card-market series frozen in docs/card_pirate_index.md. ONE ADDITIVE TABLE.
No existing table, column, constraint or index is touched, and this revision
writes zero rows.

NOTHING HERE IS PRICING. market_index.INDEX_VERSION stays 3 and
source_semantics.SOURCE_SEMANTICS_VERSION stays 2. No Market Index value, no
source-semantics rule and no price observation is created, modified or read.
market_index_snapshots in particular is untouched: its append-only, no-backfill
contract is unchanged, and this table only ever READS from it - later, from a
job that does not exist yet.

WHY THE DOWNGRADE IS SAFE HERE AND IS NOT SAFE FOR THE SIBLING TABLE
----------------------------------------------------------------------
Dropping market_index_snapshots would destroy history that cannot be
reconstructed: a past Market Index is not computable, because
_compute_index_fields applies freshness windows relative to the `now` it is
handed. Dropping THIS table loses nothing permanently. Every point is a pure,
deterministic function of the immutable index_value_jpy values already
archived in market_index_snapshots, so the whole series can be recomputed by
the future job's replay mode. That is a real and reassuring difference, and it
is why the downgrade below is a plain drop_table with no warning attached.

The same property is what makes a deterministic replay to seed 2026-09-03
onward LEGITIMATE rather than a backfill. A future reader who sees a
--replay-from flag and reaches for market_index_snapshots' "No backfill"
docstring should stop here: the prohibition there rests on a dependency this
table does not have.

THE CARRY, AND WHY IT IS A COMPOSITE FOREIGN KEY
--------------------------------------------------
A methodology/index/source-semantics boundary never chains a constituent
return across itself. It closes the old segment and opens a new one whose base
level EQUALS the previous segment's final published level, recorded by
carried_from_point_id. Two rules have to hold for that reference: the target
must be in the same scope, and its index_value must be identical.

Both are enforced by one composite self-referential foreign key over
(carried_from_point_id, scope_kind, scope_key, index_value), which is why
uq_cpi_points_carry_target exists - a foreign key needs a unique index on its
target columns. That extra unique index is redundant for reads (id alone is
already unique) and admin_db_index_audit will flag it; it is the deliberate
price of enforcing the carry in the database instead of in application code.

NO TRIGGER. A hand-written UPDATE could still build a carry cycle, and this
revision does not defend against that. The normal insert path cannot: the
foreign key is immediate and non-deferrable, so a carried base can only
reference a row that already exists, and there is no UPDATE writer anywhere in
the codebase. Cycle detection belongs to the future --verify replay, which
must reject a cycle and any carry whose target date is not strictly earlier
than the carrying row's. Adding a trigger now would defend against a writer
that does not exist while taxing one that does.

INSERTION ORDER IS A REQUIREMENT. Because the foreign key is immediate, points
must be written in ascending point_date order within a scope. A partial replay
that starts after its own carry target fails closed and loudly, which is the
desired behaviour.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d2f47a6b31"
down_revision: Union[str, Sequence[str], None] = "b8e3f1a70d95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "card_pirate_index_points"

# Only a base row opens a segment, so only a base row can carry a level in.
CARRY_REQUIRES_BASE_CHECK = "carried_from_point_id IS NULL OR is_base"

# The foreign key alone would happily accept a row referencing itself - a
# self-reference satisfies it - so this is the constraint that forbids it.
CARRY_NOT_SELF_CHECK = (
    "carried_from_point_id IS NULL OR carried_from_point_id <> id"
)

# An initial base, and only an initial base, starts at BASE_VALUE = 1000. A
# carried base starts wherever the previous segment finished and is exempt via
# the carried_from_point_id IS NOT NULL branch.
INITIAL_BASE_IS_BASE_VALUE_CHECK = (
    "NOT is_base OR carried_from_point_id IS NOT NULL OR index_value = 1000"
)

SCOPE_KIND_CHECK = "scope_kind IN ('overall', 'set', 'rarity')"

# Both-directions equality rather than a one-way implication, matching the
# style market_index_snapshots already uses: an 'overall' row carrying a key,
# and a 'set' row without one, are both rejected.
SCOPE_KEY_PAIRING_CHECK = "(scope_kind = 'overall') = (scope_key = '')"

# index_value is NULL if and only if the day could not be published.
VALUE_PRESENCE_CHECK = "(index_value IS NULL) = (unpublishable_reason IS NOT NULL)"

# A base row is a level carry (or the initial 1000), so it always has a value.
# This ALSO closes the MATCH SIMPLE hole in the foreign key: MATCH SIMPLE skips
# the entire constraint when any referencing column is NULL, so a carried base
# with a NULL index_value would slip past the key unchecked. It cannot get that
# far, because this check rejects it first. The two must be read together.
BASE_HAS_VALUE_CHECK = "NOT is_base OR index_value IS NOT NULL"

# A boundary has no calculated return.
BASE_HAS_NO_STEP_CHECK = (
    "NOT is_base OR (chain_link_log_return IS NULL"
    " AND prior_point_date IS NULL"
    " AND step_days IS NULL"
    " AND constituent_count = 0)"
)

# A published non-base point came from a step, and a step has a prior point.
# An unpublishable one is exempt - it may have failed before a prior point was
# resolved at all.
STEP_REQUIRES_PRIOR_CHECK = (
    "is_base OR index_value IS NULL OR prior_point_date IS NOT NULL"
)

# A step spans at least one day. A missed cron run makes a real multi-day
# return with step_days > 1; it is never forward-fill.
STEP_DAYS_POSITIVE_CHECK = "step_days IS NULL OR step_days >= 1"

# Constituents are the prints that produced a RETURN this step; eligible
# prints are merely those valued on point_date. Entrants and leavers move the
# second without moving the first.
CONSTITUENTS_LE_ELIGIBLE_CHECK = "constituent_count <= eligible_print_count"

# Breadth is present exactly when a constituent set existed. Base rows,
# mixed-version days and empty steps all have constituent_count = 0 and NULL
# breadth; an insufficient_constituents day still reports its n, because
# n < MIN_CONSTITUENTS is a real measurement rather than an absence.
BREADTH_PRESENCE_CHECK = "(movers_up IS NULL) = (constituent_count = 0)"

# The four breadth counters are one fact spread over four columns, so they are
# present together or absent together. WITHOUT THIS, movers_up = 1 beside a
# NULL movers_down makes MOVERS_SUM_CHECK evaluate to NULL - and a CHECK
# PASSES on NULL. The hole is real, and this is what closes it.
MOVERS_PAIRING_CHECK = (
    "(movers_down IS NULL) = (movers_up IS NULL)"
    " AND (movers_flat IS NULL) = (movers_up IS NULL)"
    " AND (capped_count IS NULL) = (movers_up IS NULL)"
)

MOVERS_SUM_CHECK = (
    "movers_up IS NULL OR movers_up + movers_down + movers_flat = constituent_count"
)

# Capping never changes a return's sign, so a capped constituent is still
# counted among the movers and can never exceed the panel.
CAPPED_LE_CONSTITUENTS_CHECK = (
    "capped_count IS NULL OR capped_count <= constituent_count"
)

COUNTS_NON_NEGATIVE_CHECK = (
    "constituent_count >= 0 AND eligible_print_count >= 0"
    " AND (movers_up IS NULL OR (movers_up >= 0 AND movers_down >= 0"
    " AND movers_flat >= 0 AND capped_count >= 0))"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        # Surrogate, and INTERNAL. Point ids are not stable across a
        # drop-and-replay rebuild while the natural key is, so they must never
        # become part of the API contract: the payload exposes the carry as a
        # date resolved by join, never as an id.
        sa.Column("id", sa.Integer(), nullable=False),
        # The sub-index extension point, present from day one so a set- or
        # rarity-level series needs no second migration. 'overall' + '' is the
        # only scope written today.
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        # Three versions, three owners. methodology_version is this index's
        # own; the other two are copied from the constituents as they were at
        # calculation time, never re-read from the constants later, so a
        # future release cannot relabel an old point.
        sa.Column("methodology_version", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("source_semantics_version", sa.Integer(), nullable=False),
        sa.Column("point_date", sa.Date(), nullable=False),
        # NULL is a real, meaningful result (the day could not be published),
        # not missing data. Numeric rather than float: the level is
        # chain-linked over hundreds of steps and a binary float would drift.
        sa.Column("index_value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("is_base", sa.Boolean(), nullable=False),
        # The single column representing the carry. NULL on an initial base
        # and on every ordinary row. There is deliberately no
        # segment_base_kind column (the distinction IS this column's
        # nullability), no carried_from_point_date (one join away) and no
        # segment_base_value (index_value on the base row IS the carried
        # level, and the foreign key proves it equals the source's).
        sa.Column("carried_from_point_id", sa.Integer(), nullable=True),
        # The prior AVAILABLE SNAPSHOT DAY, never the prior calendar day.
        sa.Column("prior_point_date", sa.Date(), nullable=True),
        sa.Column("step_days", sa.Integer(), nullable=True),
        # The step's mean capped log return. Log rather than percentage
        # because log returns are additive, so the chain-linked level is
        # exp(sum of steps) and rounding cannot accumulate directionally.
        sa.Column(
            "chain_link_log_return", sa.Numeric(precision=18, scale=12), nullable=True
        ),
        sa.Column("constituent_count", sa.Integer(), nullable=False),
        sa.Column("eligible_print_count", sa.Integer(), nullable=False),
        sa.Column("movers_up", sa.Integer(), nullable=True),
        sa.Column("movers_down", sa.Integer(), nullable=True),
        sa.Column("movers_flat", sa.Integer(), nullable=True),
        # NOT "winsorized_count". v1 rejects percentile winsorization
        # outright, and a column name implying otherwise would misdescribe the
        # methodology in the one place a future reader will trust.
        sa.Column("capped_count", sa.Integer(), nullable=True),
        sa.Column("unpublishable_reason", sa.String(length=32), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # One point per scope per day per methodology version - the identity
        # the future job's ON CONFLICT DO NOTHING keys on, and the read path's
        # index: scope first, point_date last for the range scan.
        #
        # index_version is DELIBERATELY NOT a key column. Two rows for one day
        # under two index_versions is an error, not a legal pair of rows - a
        # day belongs to exactly one segment - and leaving it out of the key
        # makes that unrepresentable rather than merely discouraged.
        sa.UniqueConstraint(
            "scope_kind",
            "scope_key",
            "methodology_version",
            "point_date",
            name="uq_cpi_points_point",
        ),
        # Exists SOLELY as the foreign key's target. See the module docstring.
        sa.UniqueConstraint(
            "id", "scope_kind", "scope_key", "index_value",
            name="uq_cpi_points_carry_target",
        ),
        # One constraint proves three things: the target exists, it is in the
        # SAME scope, and its index_value is IDENTICAL to this row's.
        #
        # ON UPDATE RESTRICT makes a carried-from point's published level
        # immutable at the database level rather than only by convention - the
        # one place the append-only contract is actually enforced. ON DELETE
        # RESTRICT means the chain cannot be silently truncated, matching
        # market_index_snapshots' RESTRICT on card_print_id.
        sa.ForeignKeyConstraint(
            ["carried_from_point_id", "scope_kind", "scope_key", "index_value"],
            [
                f"{TABLE}.id",
                f"{TABLE}.scope_kind",
                f"{TABLE}.scope_key",
                f"{TABLE}.index_value",
            ],
            name="fk_cpi_points_carried_from",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            CARRY_REQUIRES_BASE_CHECK, name="ck_cpi_points_carry_requires_base"
        ),
        sa.CheckConstraint(CARRY_NOT_SELF_CHECK, name="ck_cpi_points_carry_not_self"),
        sa.CheckConstraint(
            INITIAL_BASE_IS_BASE_VALUE_CHECK,
            name="ck_cpi_points_initial_base_is_base_value",
        ),
        sa.CheckConstraint(SCOPE_KIND_CHECK, name="ck_cpi_points_scope_kind"),
        sa.CheckConstraint(
            SCOPE_KEY_PAIRING_CHECK, name="ck_cpi_points_scope_key_pairing"
        ),
        sa.CheckConstraint(VALUE_PRESENCE_CHECK, name="ck_cpi_points_value_presence"),
        sa.CheckConstraint(BASE_HAS_VALUE_CHECK, name="ck_cpi_points_base_has_value"),
        sa.CheckConstraint(
            BASE_HAS_NO_STEP_CHECK, name="ck_cpi_points_base_has_no_step"
        ),
        sa.CheckConstraint(
            STEP_REQUIRES_PRIOR_CHECK, name="ck_cpi_points_step_requires_prior"
        ),
        sa.CheckConstraint(
            STEP_DAYS_POSITIVE_CHECK, name="ck_cpi_points_step_days_positive"
        ),
        sa.CheckConstraint(
            CONSTITUENTS_LE_ELIGIBLE_CHECK,
            name="ck_cpi_points_constituents_le_eligible",
        ),
        sa.CheckConstraint(
            BREADTH_PRESENCE_CHECK, name="ck_cpi_points_breadth_presence"
        ),
        sa.CheckConstraint(MOVERS_PAIRING_CHECK, name="ck_cpi_points_movers_pairing"),
        sa.CheckConstraint(MOVERS_SUM_CHECK, name="ck_cpi_points_movers_sum"),
        sa.CheckConstraint(
            CAPPED_LE_CONSTITUENTS_CHECK, name="ck_cpi_points_capped_le_constituents"
        ),
        sa.CheckConstraint(
            COUNTS_NON_NEGATIVE_CHECK, name="ck_cpi_points_counts_non_negative"
        ),
    )
    # NO further indexes, on purpose. uq_cpi_points_point IS the read path -
    # scope, then methodology_version, then point_date last for the range
    # scan - and admin_db_index_audit exists to flag indexes nothing uses.


def downgrade() -> None:
    # A plain drop. Unlike market_index_snapshots, this loss is fully
    # recoverable: every point is a deterministic function of index_value_jpy
    # values that are still archived, so the future job's replay rebuilds the
    # whole series. See the module docstring.
    op.drop_table(TABLE)
