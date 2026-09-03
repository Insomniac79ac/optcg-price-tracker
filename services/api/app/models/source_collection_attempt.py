from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# One durable row per (batch_run_id, source_card_mapping_id): what a collector
# was asked to do, and what became of it.
#
# WHY IT EXISTS. Collector events are stdout prints. The only durable writes a
# collection makes are RawSnapshot + PriceObservation, both on the success path
# only, so failure leaves no trace at all: on 2026-09-02 the three failures of
# the 214-mapping batch left 0 observations, 0 last_collection_attempted_at
# stamps and 0 app_log_events rows between them, and mapping 391's cause is now
# unknowable because Railway did not retain its lines. A row here is the
# smallest thing that would have answered it.
#
# WHAT IT MUST NEVER HOLD. No page HTML (raw_snapshots already stores 225 kB a
# row), no browser traces, no secrets, no copied log text. failure_reason is a
# bounded String, not Text, so that bound is the database's rule rather than a
# caller's good intentions.
#
# This table is WRITTEN by the collector services and READ by the API. It is
# not part of pricing: no Market Index input, no source-semantics value, and
# nothing here is consulted when an observation is created.

# The initial state, written for the whole selected population before any
# navigation happens - so the population survives a process that dies on its
# first mapping.
STATUS_SELECTED = "selected"
STATUS_WRITTEN = "written"
STATUS_VALIDATION_FAILED = "validation_failed"
STATUS_NO_EXTRACTION_ATTEMPTED = "no_extraction_attempted"
STATUS_OPERATIONAL_ERROR = "operational_error"
STATUS_MAPPING_LOAD_FAILED = "mapping_load_failed"
# Selected, never started: the batch aborted (source denial, watchdog) before
# reaching this mapping.
STATUS_SKIPPED = "skipped"

STATUSES = (
    STATUS_SELECTED,
    STATUS_WRITTEN,
    STATUS_VALIDATION_FAILED,
    STATUS_NO_EXTRACTION_ATTEMPTED,
    STATUS_OPERATIONAL_ERROR,
    STATUS_MAPPING_LOAD_FAILED,
    STATUS_SKIPPED,
)

# Where an attempt stopped, when it stopped badly. Mirrors the collector's own
# pipeline order and is what separates "the homepage never answered" (413) from
# "the price was refused" (351) once the logs are gone.
FAILURE_STAGES = (
    "load",
    "browser_launch",
    "homepage",
    "product",
    "extraction",
    "validation",
    "write",
)

_STATUS_CHECK = "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")"
_FAILURE_STAGE_CHECK = "failure_stage IS NULL OR failure_stage IN (" + ", ".join(
    f"'{s}'" for s in FAILURE_STAGES
) + ")"

MAX_FAILURE_REASON_LENGTH = 500


class SourceCollectionAttempt(Base):
    __tablename__ = "source_collection_attempts"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_source_collection_attempts_status"),
        CheckConstraint(
            _FAILURE_STAGE_CHECK, name="ck_source_collection_attempts_failure_stage"
        ),
        # finished_at is set EXACTLY WHEN the row is terminal - a biconditional,
        # not an implication. 'selected' is the only non-terminal status, so a
        # selected row must have no finish time and a terminal row must have
        # one. The weaker "status = 'selected' OR finished_at IS NOT NULL" it
        # replaces allowed a selected row stamped with a finish time, which the
        # lifecycle has no meaning for and which would make "is this attempt
        # still in flight?" unanswerable from the row alone.
        CheckConstraint(
            "(status = 'selected') = (finished_at IS NULL)",
            name="ck_source_collection_attempts_finished_iff_terminal",
        ),
        # Ordering when both ends are known. Deliberately NOT "finished implies
        # started": a mapping the batch selected and then skipped finishes
        # without ever starting, and asserting otherwise would make the correct
        # row unrepresentable.
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="ck_source_collection_attempts_finished_after_started",
        ),
        CheckConstraint(
            "selection_ordinal > 0",
            name="ck_source_collection_attempts_selection_ordinal_positive",
        ),
        CheckConstraint(
            "source_id > 0", name="ck_source_collection_attempts_source_id_positive"
        ),
        CheckConstraint(
            "source_card_mapping_id > 0",
            name="ck_source_collection_attempts_mapping_id_positive",
        ),
        UniqueConstraint(
            "batch_run_id",
            "source_card_mapping_id",
            name="uq_source_collection_attempts_batch_mapping",
        ),
        # One mapping per position per run. selection_ordinal exists so exact
        # batch order survives log loss; two mappings claiming position 7 would
        # destroy the fact it was added to preserve.
        UniqueConstraint(
            "batch_run_id",
            "selection_ordinal",
            name="uq_source_collection_attempts_batch_ordinal",
        ),
        Index("ix_source_collection_attempts_batch_run_id", "batch_run_id"),
        Index("ix_source_collection_attempts_source_id", "source_id"),
        # Recent history for one mapping. Ordered by selected_at because it is
        # NOT NULL and therefore covers rows that never started.
        Index(
            "ix_source_collection_attempts_mapping_recent",
            "source_card_mapping_id",
            text("selected_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # The collector's own per-run id, already present in every log line, so a
    # row here and a surviving log line can still be joined by hand.
    batch_run_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # Deliberately NOT foreign keys. This table has to outlive what it
    # describes, and the repo never hard-deletes either subject: mappings are
    # retired with is_active = False, admin_card_merge states it "never
    # hard-deletes a card, a source mapping, a price observation", and
    # data_retention prunes neither. A delete-coupled FK would buy nothing in
    # production while ensuring that a future hard delete takes the history
    # with it; and its insert-time half would silently LOSE a row (the recorder
    # swallows failures) exactly when the evidence is most wanted.
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_card_mapping_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # 1-based position within the selected population. NOT NULL: this table is
    # batch-scoped and record_selected_batch is its only INSERT, so a row cannot
    # exist without a position. The standalone --mapping-id CLI path is
    # deliberately unwired and writes nothing here.
    selection_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    # Entered the batch population. Always known.
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Processing actually began. NULL for a mapping that was selected and then
    # skipped - a real and common state, not missing data.
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), default=STATUS_SELECTED, server_default=STATUS_SELECTED, nullable=False
    )
    failure_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(
        String(MAX_FAILURE_REASON_LENGTH), nullable=True
    )

    # Kept as its own column although it is inferable from a reason string: it
    # is the fact that explains why OTHER mappings in the same run were
    # skipped, and reading that off free text would be guesswork.
    source_denied: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # SET NULL on delete: if an observation is ever pruned, the record
    # explaining how it came to exist must outlive it.
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id", ondelete="SET NULL"), nullable=True
    )
