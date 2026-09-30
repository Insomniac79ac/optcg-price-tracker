"""Shared due work; only explicit opt-in collectors consume these tables."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SourceDispatchBudget(Base):
    __tablename__ = "source_dispatch_budgets"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_source_dispatch_budget_source"),
        CheckConstraint(
            "request_limit > 0 AND window_seconds > 0 AND used_requests >= 0 "
            "AND reserved_requests >= 0 AND claim_sequence >= 0",
            name="ck_source_dispatch_budget_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Charged requests include conservative crash charges; actual known cost
    # remains separately recorded on attempts.
    used_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_reason: Mapped[str | None] = mapped_column(String(100))
    claim_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FreshnessWork(Base):
    __tablename__ = "freshness_work"
    __table_args__ = (
        UniqueConstraint("work_key", name="uq_freshness_work_key"),
        UniqueConstraint(
            "source_id", "product_identity", name="uq_freshness_work_product"
        ),
        ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.source_id",
            ],
            name="fk_freshness_work_mapping_print",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(kind = 'refresh' AND source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL AND product_identity IS NOT NULL AND scope_key IS NULL) OR "
            "(kind = 'print_discovery' AND source_card_mapping_id IS NULL AND card_print_id IS NOT NULL AND product_identity IS NULL AND scope_key IS NULL) OR "
            "(kind IN ('discovery', 'validation') AND source_card_mapping_id IS NULL AND card_print_id IS NULL AND product_identity IS NULL AND scope_key IS NOT NULL)",
            name="ck_freshness_work_lineage",
        ),
        CheckConstraint(
            "lane IN ('high', 'ordinary', 'discovery', 'coverage')",
            name="ck_freshness_work_lane",
        ),
        CheckConstraint(
            "state IN ('pending', 'claimed', 'blocked')", name="ck_freshness_work_state"
        ),
        CheckConstraint(
            "(state = 'claimed' AND claim_token IS NOT NULL AND claimed_by IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND claim_expires_at > claimed_at) OR "
            "(state <> 'claimed' AND claim_token IS NULL AND claimed_by IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL)",
            name="ck_freshness_work_claim",
        ),
        CheckConstraint(
            "estimated_request_cost > 0 AND attempt_count >= 0 AND last_claim_sequence >= 0 "
            "AND priority BETWEEN 0 AND 100 AND execution_headroom_seconds > 0 AND execution_headroom_seconds < 14400",
            name="ck_freshness_work_bounds",
        ),
        Index(
            "ix_freshness_work_due", "source_id", "state", "lane", "next_due_at", "id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    product_identity: Mapped[str | None] = mapped_column(String(1024))
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer)
    card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="CASCADE")
    )
    scope_key: Mapped[str | None] = mapped_column(String(160))
    # Opaque, versioned adapter cursor (or pointer to its existing checkpoint).
    resume_cursor: Mapped[dict | None] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_headroom_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    high_interest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retry_not_before_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    lane: Mapped[str] = mapped_column(String(24), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_request_cost: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_claim_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successfully_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_failure: Mapped[str | None] = mapped_column(String(500))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outcome: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FreshnessPriceState(Base):
    __tablename__ = "freshness_price_states"
    __table_args__ = (
        CheckConstraint(
            "consecutive_failures IS NULL OR consecutive_failures BETWEEN 0 AND 8",
            name="ck_freshness_price_failure_streak",
        ),
        UniqueConstraint(
            "work_id", "price_category", name="uq_freshness_price_category"
        ),
        CheckConstraint(
            "availability IN ('unknown', 'listed', 'no_listing')",
            name="ck_freshness_price_availability",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("freshness_work.id", ondelete="CASCADE"), nullable=False
    )
    price_category: Mapped[str] = mapped_column(String(32), nullable=False)
    price_type: Mapped[str] = mapped_column(String(32), nullable=False)
    condition_label: Mapped[str | None] = mapped_column(String(64))
    # NULL is a legacy archive/row with no retry history. Saturates at the
    # shared policy ceiling; a different category's success never resets it.
    consecutive_failures: Mapped[int | None] = mapped_column(Integer)
    retry_not_before_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_successfully_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_valid_price_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id", ondelete="SET NULL")
    )
    availability: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown"
    )
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FreshnessAttempt(Base):
    __tablename__ = "freshness_attempts"
    __table_args__ = (
        UniqueConstraint("claim_token", name="uq_freshness_attempt_token"),
        UniqueConstraint("raw_snapshot_id", name="uq_freshness_attempt_capture"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('captured', 'no_listing', 'identity_refusal', 'transient_failure', 'source_denial', 'expired', 'discovery_progress', 'completed')",
            name="ck_freshness_attempt_outcome",
        ),
        CheckConstraint(
            "reserved_request_cost > 0 AND (actual_request_cost IS NULL OR actual_request_cost >= 0) "
            "AND (charged_request_cost IS NULL OR charged_request_cost >= 0)",
            name="ck_freshness_attempt_cost",
        ),
        CheckConstraint(
            "(outcome IS NULL AND finished_at IS NULL AND charged_request_cost IS NULL) OR "
            "(outcome IS NOT NULL AND finished_at IS NOT NULL AND charged_request_cost IS NOT NULL)",
            name="ck_freshness_attempt_terminal",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("freshness_work.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_token: Mapped[str] = mapped_column(String(36), nullable=False)
    claimed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))
    reserved_request_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    request_costs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actual_request_cost: Mapped[int | None] = mapped_column(Integer)
    charged_request_cost: Mapped[int | None] = mapped_column(Integer)
    category_outcomes: Mapped[dict | None] = mapped_column(JSON)
    result_digest: Mapped[str | None] = mapped_column(String(64))
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL")
    )
