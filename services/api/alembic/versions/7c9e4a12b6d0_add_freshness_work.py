"""Add dormant freshness work, evidence and source admission.

Revision ID: 7c9e4a12b6d0
Revises: e6a8b0c3d5f7
No backfill, scheduler activation or change to existing pricing tables.
"""

from alembic import op
import sqlalchemy as sa

revision = "7c9e4a12b6d0"
down_revision = "e6a8b0c3d5f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_dispatch_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("request_limit", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_requests", sa.Integer(), nullable=False),
        sa.Column("reserved_requests", sa.Integer(), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.String(length=100), nullable=True),
        sa.Column("claim_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "request_limit > 0 AND window_seconds > 0 AND used_requests >= 0 AND reserved_requests >= 0 AND claim_sequence >= 0",
            name="ck_source_dispatch_budget_nonnegative",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_source_dispatch_budget_source"),
    )
    op.create_table(
        "freshness_work",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("product_identity", sa.String(length=1024), nullable=True),
        sa.Column("source_card_mapping_id", sa.Integer(), nullable=True),
        sa.Column("card_print_id", sa.Integer(), nullable=True),
        sa.Column("scope_key", sa.String(length=160), nullable=True),
        sa.Column("resume_cursor", sa.JSON(), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("execution_headroom_seconds", sa.Integer(), nullable=False),
        sa.Column("high_interest", sa.Boolean(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_not_before_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lane", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("estimated_request_cost", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_claim_sequence", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_successfully_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_failure", sa.String(length=500), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'refresh' AND source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL AND product_identity IS NOT NULL AND scope_key IS NULL) OR (kind = 'print_discovery' AND source_card_mapping_id IS NULL AND card_print_id IS NOT NULL AND product_identity IS NULL AND scope_key IS NULL) OR (kind IN ('discovery', 'validation') AND source_card_mapping_id IS NULL AND card_print_id IS NULL AND product_identity IS NULL AND scope_key IS NOT NULL)",
            name="ck_freshness_work_lineage",
        ),
        sa.CheckConstraint(
            "(state = 'claimed' AND claim_token IS NOT NULL AND claimed_by IS NOT NULL AND claimed_at IS NOT NULL AND claim_expires_at IS NOT NULL AND claim_expires_at > claimed_at) OR (state <> 'claimed' AND claim_token IS NULL AND claimed_by IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL)",
            name="ck_freshness_work_claim",
        ),
        sa.CheckConstraint(
            "lane IN ('high', 'ordinary', 'discovery', 'coverage')",
            name="ck_freshness_work_lane",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'blocked')", name="ck_freshness_work_state"
        ),
        sa.CheckConstraint(
            "estimated_request_cost > 0 AND attempt_count >= 0 AND last_claim_sequence >= 0 AND priority BETWEEN 0 AND 100 AND execution_headroom_seconds > 0 AND execution_headroom_seconds < 14400",
            name="ck_freshness_work_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["card_print_id"], ["card_prints.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.source_id",
            ],
            name="fk_freshness_work_mapping_print",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "product_identity", name="uq_freshness_work_product"
        ),
        sa.UniqueConstraint("work_key", name="uq_freshness_work_key"),
    )
    op.create_index(
        "ix_freshness_work_due",
        "freshness_work",
        ["source_id", "state", "lane", "next_due_at", "id"],
        unique=False,
    )
    op.create_table(
        "freshness_price_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("price_category", sa.String(length=32), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("condition_label", sa.String(length=64), nullable=True),
        sa.Column(
            "last_successfully_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_valid_price_observed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_observation_id", sa.Integer(), nullable=True),
        sa.Column("availability", sa.String(length=16), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "availability IN ('unknown', 'listed', 'no_listing')",
            name="ck_freshness_price_availability",
        ),
        sa.ForeignKeyConstraint(
            ["last_observation_id"], ["price_observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["work_id"], ["freshness_work.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "work_id", "price_category", name="uq_freshness_price_category"
        ),
    )
    op.create_table(
        "freshness_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=False),
        sa.Column("claimed_by", sa.String(length=128), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("reserved_request_cost", sa.Integer(), nullable=False),
        sa.Column("request_costs", sa.JSON(), nullable=False),
        sa.Column("actual_request_cost", sa.Integer(), nullable=True),
        sa.Column("charged_request_cost", sa.Integer(), nullable=True),
        sa.Column("result_digest", sa.String(length=64), nullable=True),
        sa.Column("raw_snapshot_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('captured', 'no_listing', 'identity_refusal', 'transient_failure', 'source_denial', 'expired', 'discovery_progress', 'completed')",
            name="ck_freshness_attempt_outcome",
        ),
        sa.CheckConstraint(
            "(outcome IS NULL AND finished_at IS NULL AND charged_request_cost IS NULL) OR (outcome IS NOT NULL AND finished_at IS NOT NULL AND charged_request_cost IS NOT NULL)",
            name="ck_freshness_attempt_terminal",
        ),
        sa.CheckConstraint(
            "reserved_request_cost > 0 AND (actual_request_cost IS NULL OR actual_request_cost >= 0) AND (charged_request_cost IS NULL OR charged_request_cost >= 0)",
            name="ck_freshness_attempt_cost",
        ),
        sa.ForeignKeyConstraint(
            ["raw_snapshot_id"], ["raw_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["work_id"], ["freshness_work.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_token", name="uq_freshness_attempt_token"),
        sa.UniqueConstraint("raw_snapshot_id", name="uq_freshness_attempt_capture"),
    )
    op.create_index(
        op.f("ix_freshness_attempts_work_id"),
        "freshness_attempts",
        ["work_id"],
        unique=False,
    )


def downgrade():
    op.drop_table("freshness_attempts")
    op.drop_table("freshness_price_states")
    op.drop_table("freshness_work")
    op.drop_table("source_dispatch_budgets")
