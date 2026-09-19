"""add source-scoped release aliases and exact-print proposals

Revision ID: f4c8a2d91b60
Revises: e3a7c5d9b102

No proposal, mapping, candidate, or observation rows are backfilled.  The only
data normalization assigns the already-declared storefront aliases to their
known SNKRDUNK namespace so the new database constraint can be enforced.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c8a2d91b60"
down_revision: Union[str, Sequence[str], None] = "e3a7c5d9b102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A clean alembic-only database contains one historical SNKRDUNK rendering
    # but no seeded sources.  Establishing this known source is required to
    # make that existing evidence source-scoped; no alias value is inferred.
    op.execute(
        "INSERT INTO sources (name, base_url) "
        "SELECT 'snkrdunk', 'https://snkrdunk.com' "
        "WHERE NOT EXISTS (SELECT 1 FROM sources WHERE name = 'snkrdunk')"
    )
    op.add_column(
        "release_product_aliases",
        sa.Column("source_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_release_product_aliases_source_id",
        "release_product_aliases",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_release_product_aliases_source_id",
        "release_product_aliases",
        ["source_id"],
    )
    op.execute(
        "UPDATE release_product_aliases SET source_id = "
        "(SELECT id FROM sources WHERE name = 'snkrdunk') "
        "WHERE alias_kind = 'source_rendering'"
    )
    op.drop_constraint(
        "uq_release_product_aliases_identity",
        "release_product_aliases",
        type_="unique",
    )
    op.create_index(
        "uq_release_product_aliases_authority_identity",
        "release_product_aliases",
        ["product_id", "alias_kind", "alias_name"],
        unique=True,
        postgresql_where=sa.text("alias_kind <> 'source_rendering'"),
    )
    op.create_index(
        "uq_release_product_aliases_source_identity",
        "release_product_aliases",
        ["source_id", "alias_name"],
        unique=True,
        postgresql_where=sa.text("alias_kind = 'source_rendering'"),
    )
    op.create_check_constraint(
        "ck_release_product_aliases_source_scope",
        "release_product_aliases",
        "(alias_kind = 'source_rendering' AND source_id IS NOT NULL) OR "
        "(alias_kind <> 'source_rendering' AND source_id IS NULL)",
    )

    op.create_table(
        "source_mapping_proposal_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("canonical_source_listing_identity", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("source_candidate_type", sa.String(length=32), nullable=False),
        sa.Column("source_candidate_id", sa.Integer(), nullable=False),
        sa.Column("canonical_card_id", sa.Integer(), nullable=True),
        sa.Column("release_product_id", sa.Integer(), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("resolver_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("resolution_reasons_json", sa.JSON(), nullable=False),
        sa.Column("resulting_source_card_mapping_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resolution_status IN ('exact', 'ambiguous', 'unresolved_identity', "
            "'release_unresolved', 'conflict', 'stale', 'superseded')",
            name="ck_mapping_proposal_groups_resolution_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_mapping_proposal_groups_review_status",
        ),
        sa.CheckConstraint(
            "source_candidate_type IN ('yuyutei_candidate', 'snkrdunk_candidate')",
            name="ck_mapping_proposal_groups_candidate_type",
        ),
        sa.CheckConstraint(
            "length(evidence_digest) = 64",
            name="ck_mapping_proposal_groups_digest_length",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canonical_card_id"], ["canonical_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["release_product_id"], ["release_products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["resulting_source_card_mapping_id"], ["source_card_mappings.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "canonical_source_listing_identity", "resolver_version", "evidence_digest",
            name="uq_mapping_proposal_groups_evidence_version",
        ),
    )
    op.create_index("ix_source_mapping_proposal_groups_source_id", "source_mapping_proposal_groups", ["source_id"])
    op.create_index("ix_source_mapping_proposal_groups_canonical_card_id", "source_mapping_proposal_groups", ["canonical_card_id"])
    op.create_index("ix_source_mapping_proposal_groups_release_product_id", "source_mapping_proposal_groups", ["release_product_id"])
    op.create_index("ix_source_mapping_proposal_groups_resolution_status", "source_mapping_proposal_groups", ["resolution_status"])
    op.create_index("ix_source_mapping_proposal_groups_review_status", "source_mapping_proposal_groups", ["review_status"])
    op.create_index("ix_mapping_proposal_groups_result_mapping", "source_mapping_proposal_groups", ["resulting_source_card_mapping_id"])
    op.create_index(
        "ix_mapping_proposal_groups_release_status", "source_mapping_proposal_groups",
        ["release_product_id", "resolution_status"],
    )
    op.create_index(
        "ix_mapping_proposal_groups_candidate", "source_mapping_proposal_groups",
        ["source_candidate_type", "source_candidate_id"],
    )
    op.create_index(
        "uq_mapping_proposal_groups_current_listing", "source_mapping_proposal_groups",
        ["source_id", "canonical_source_listing_identity"], unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "source_mapping_proposal_alternatives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_group_id", sa.Integer(), nullable=False),
        sa.Column("card_print_id", sa.Integer(), nullable=False),
        sa.Column("recommended", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supporting_evidence_json", sa.JSON(), nullable=False),
        sa.Column("missing_evidence_json", sa.JSON(), nullable=False),
        sa.Column("conflict_reasons_json", sa.JSON(), nullable=False),
        sa.Column("review_disposition", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "review_disposition IN ('pending', 'approved', 'rejected')",
            name="ck_mapping_proposal_alternatives_review_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_group_id"], ["source_mapping_proposal_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["card_print_id"], ["card_prints.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proposal_group_id", "card_print_id",
            name="uq_mapping_proposal_alternatives_group_print",
        ),
    )
    op.create_index("ix_mapping_proposal_alternatives_group", "source_mapping_proposal_alternatives", ["proposal_group_id"])
    op.create_index("ix_source_mapping_proposal_alternatives_card_print_id", "source_mapping_proposal_alternatives", ["card_print_id"])
    op.create_index("ix_source_mapping_proposal_alternatives_review_disposition", "source_mapping_proposal_alternatives", ["review_disposition"])
    op.create_index(
        "ix_mapping_proposal_alternatives_print_recommended",
        "source_mapping_proposal_alternatives", ["card_print_id", "recommended"],
    )


def downgrade() -> None:
    op.drop_index("ix_mapping_proposal_alternatives_print_recommended", table_name="source_mapping_proposal_alternatives")
    op.drop_index("ix_source_mapping_proposal_alternatives_review_disposition", table_name="source_mapping_proposal_alternatives")
    op.drop_index("ix_source_mapping_proposal_alternatives_card_print_id", table_name="source_mapping_proposal_alternatives")
    op.drop_index("ix_mapping_proposal_alternatives_group", table_name="source_mapping_proposal_alternatives")
    op.drop_table("source_mapping_proposal_alternatives")

    op.drop_index("uq_mapping_proposal_groups_current_listing", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_mapping_proposal_groups_candidate", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_mapping_proposal_groups_release_status", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_mapping_proposal_groups_result_mapping", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_source_mapping_proposal_groups_review_status", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_source_mapping_proposal_groups_resolution_status", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_source_mapping_proposal_groups_release_product_id", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_source_mapping_proposal_groups_canonical_card_id", table_name="source_mapping_proposal_groups")
    op.drop_index("ix_source_mapping_proposal_groups_source_id", table_name="source_mapping_proposal_groups")
    op.drop_table("source_mapping_proposal_groups")

    op.drop_constraint("ck_release_product_aliases_source_scope", "release_product_aliases", type_="check")
    op.drop_index("uq_release_product_aliases_source_identity", table_name="release_product_aliases")
    op.drop_index("uq_release_product_aliases_authority_identity", table_name="release_product_aliases")
    op.create_unique_constraint(
        "uq_release_product_aliases_identity",
        "release_product_aliases",
        ["product_id", "alias_kind", "alias_name"],
    )
    op.drop_index("ix_release_product_aliases_source_id", table_name="release_product_aliases")
    op.drop_constraint("fk_release_product_aliases_source_id", "release_product_aliases", type_="foreignkey")
    op.drop_column("release_product_aliases", "source_id")
