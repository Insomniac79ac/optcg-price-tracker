"""add source_collection_attempts

WHY A TABLE AND NOT MORE LOGGING. Every collector event is a stdout print
(yuyutei_collector.browser.log_event); nothing about an attempt is persisted.
The only durable writes a collection makes are RawSnapshot + PriceObservation,
and both happen exclusively on the success path. So the durable record is
success-only, and a mapping that FAILED is indistinguishable from one that was
never selected: on 2026-09-02 the three failures of the 214-mapping batch left
0 observations, 0 last_collection_attempted_at stamps and 0 app_log_events
rows between them. Mapping 391's cause is now permanently unknowable - its
Railway log lines were not retained and the database never held anything.

WHY NOT app_log_events. It is a human-facing operational log (~15 rows/day),
its reasons live in free text, its only mapping linkage is an untyped
related_entity_type/id pair, and its retention policy deletes rows at 60 days
- which is exactly the history a rare failure needs. 214 rows/day would also
be a ~14x increase, drowning the signal a person reads it for.

WHY SOURCE-NEUTRAL. The same question ("why did this mapping produce nothing
last night?") is already open for SNKRDUNK, which stamps
source_card_mappings.last_collection_attempted_at and therefore keeps only the
LATEST attempt, with no reason and no run identity. source_id is carried here
so one table answers it for every collector rather than growing a per-source
twin.

SELECTED_AT VERSUS STARTED_AT. These are different facts and the batch already
distinguishes them: batch.py logs the whole selected population up front, then
may abort mid-run and skip the remainder. A skipped mapping was genuinely
selected and genuinely never started, so started_at stays NULL for it. Writing
a started_at for such a row would invent an event that did not happen, which
is the same class of error this table exists to stop.

NOTHING HERE IS PRICING. No Market Index input, no source-semantics value, no
observation is created, modified or read by this migration. It adds one table
and touches no existing row.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e3f1a70d95"
down_revision: Union[str, Sequence[str], None] = "c4a7e9d15b83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# One vocabulary, enforced by Postgres rather than by convention. 'selected' is
# the initial state written before any work begins, so the population is
# durable even if the process dies before the first navigation.
STATUS_CHECK = (
    "status IN ('selected', 'written', 'validation_failed', "
    "'no_extraction_attempted', 'operational_error', 'mapping_load_failed', "
    "'skipped')"
)

# Where an attempt stopped, when it stopped badly. NULL for a row that has not
# failed (including one still in 'selected').
FAILURE_STAGE_CHECK = (
    "failure_stage IS NULL OR failure_stage IN ('load', 'browser_launch', "
    "'homepage', 'product', 'extraction', 'validation', 'write')"
)

# A row that reached a terminal status must say WHEN. 'selected' is the only
# non-terminal status (it covers both not-yet-started and in-flight), so it is
# the only one allowed to have no finished_at. This is what stops a skipped
# mapping being left permanently unfinished.
TERMINAL_IS_FINISHED_CHECK = "status = 'selected' OR finished_at IS NOT NULL"

# Ordering, when both ends are known. Deliberately NOT "finished implies
# started": a mapping the batch selected and then skipped finishes without ever
# starting, and asserting otherwise would make the correct row unrepresentable.
FINISHED_AFTER_STARTED_CHECK = (
    "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at"
)

# Ordinals are 1-based positions in the selected population. NULL means "not
# part of a selected population" (the single-mapping CLI path); 0 would be
# neither, and allowing it would let a missing value masquerade as a position.
SELECTION_ORDINAL_CHECK = "selection_ordinal IS NULL OR selection_ordinal > 0"


def upgrade() -> None:
    op.create_table(
        "source_collection_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        # Opaque per-run identifier the collector already generates and logs;
        # a plain indexed string, because there is no batch table to point at
        # and inventing one would be a second migration's worth of scope.
        sa.Column("batch_run_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_card_mapping_id", sa.Integer(), nullable=False),
        # 1-based position within the selected population, so execution order
        # survives even when most rows never ran. NULL when the attempt was not
        # part of a selected batch (the single-mapping CLI path has no ordinal,
        # and writing 0 there would let a missing value look like a position).
        sa.Column("selection_ordinal", sa.Integer(), nullable=True),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="selected",
            nullable=False,
        ),
        sa.Column("failure_stage", sa.String(length=32), nullable=True),
        # Bounded by the column type, not by caller discipline. Holds the
        # collector's own joined fail_reasons - never page HTML, never a
        # traceback, never log text.
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "source_denied",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("price_observation_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # NO foreign key on source_id / source_card_mapping_id, on purpose.
        #
        # This table's job is to outlive what it describes. The repo never hard
        # deletes either subject - admin_card_merge states "Never hard-deletes a
        # card, a source mapping, a price observation", mappings are retired
        # with is_active = False (source_mappings.py, admin_source_mapping_
        # quality.py, card_identity_merge.py), and data_retention prunes
        # raw_snapshots and price_observations but no mapping or source. So a
        # delete-coupled FK would buy nothing in production while guaranteeing
        # that the one day someone DOES hard-delete a mapping, six months of
        # execution history vanishes with it.
        #
        # The other half of the trade is insert-time validation, and here it is
        # actively harmful: the recorder swallows its own failures, so a
        # rejected row is silently LOST - precisely when something unusual is
        # happening and the evidence is most wanted. A plain id keeps the row.
        #
        # RESTRICT was the third option and is worse than both: it would let
        # telemetry block a legitimate delete, which is the same rule violation
        # from the opposite side.
        sa.CheckConstraint(
            "source_id > 0", name="ck_source_collection_attempts_source_id_positive"
        ),
        sa.CheckConstraint(
            "source_card_mapping_id > 0",
            name="ck_source_collection_attempts_mapping_id_positive",
        ),
        # The one reference that DOES keep a foreign key, because it is the one
        # subject the app really deletes: data_retention prunes
        # price_observations at 365 days. SET NULL so the record explaining an
        # observation outlives it, and so the column never points at a row that
        # is gone.
        sa.ForeignKeyConstraint(
            ["price_observation_id"], ["price_observations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(STATUS_CHECK, name="ck_source_collection_attempts_status"),
        sa.CheckConstraint(
            FAILURE_STAGE_CHECK, name="ck_source_collection_attempts_failure_stage"
        ),
        sa.CheckConstraint(
            TERMINAL_IS_FINISHED_CHECK,
            name="ck_source_collection_attempts_terminal_is_finished",
        ),
        sa.CheckConstraint(
            FINISHED_AFTER_STARTED_CHECK,
            name="ck_source_collection_attempts_finished_after_started",
        ),
        sa.CheckConstraint(
            SELECTION_ORDINAL_CHECK,
            name="ck_source_collection_attempts_selection_ordinal_positive",
        ),
        # One row per mapping per run. Makes the recorder's "update the row for
        # this (run, mapping)" safe by construction, and makes a double-write
        # a database error rather than a silently duplicated history.
        sa.UniqueConstraint(
            "batch_run_id",
            "source_card_mapping_id",
            name="uq_source_collection_attempts_batch_mapping",
        ),
        # And one mapping per position per run. selection_ordinal exists so
        # exact batch order survives log loss; two mappings claiming position 7
        # would destroy exactly the fact it was added to preserve. NULLs stay
        # distinct under the default NULLS DISTINCT, so any number of
        # populationless rows coexist.
        sa.UniqueConstraint(
            "batch_run_id",
            "selection_ordinal",
            name="uq_source_collection_attempts_batch_ordinal",
        ),
    )
    op.create_index(
        "ix_source_collection_attempts_batch_run_id",
        "source_collection_attempts",
        ["batch_run_id"],
    )
    op.create_index(
        "ix_source_collection_attempts_source_id",
        "source_collection_attempts",
        ["source_id"],
    )
    # The recent-history lookup: "the last N attempts for this mapping".
    # selected_at rather than started_at, because it is NOT NULL and therefore
    # orders every row including the ones that never started.
    op.create_index(
        "ix_source_collection_attempts_mapping_recent",
        "source_collection_attempts",
        ["source_card_mapping_id", sa.text("selected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_collection_attempts_mapping_recent",
        table_name="source_collection_attempts",
    )
    op.drop_index(
        "ix_source_collection_attempts_source_id",
        table_name="source_collection_attempts",
    )
    op.drop_index(
        "ix_source_collection_attempts_batch_run_id",
        table_name="source_collection_attempts",
    )
    op.drop_table("source_collection_attempts")
