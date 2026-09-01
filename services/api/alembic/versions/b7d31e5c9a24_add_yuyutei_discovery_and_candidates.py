"""add yuyutei discovery runs and candidates

Listing-level discovery persistence for Yuyu-Tei. Two new tables, no changes
to any existing one: nothing here touches source_card_mappings,
price_observations, market_index_snapshots or the SNKRDUNK candidate tables.

The natural key on yuyutei_candidates is (set_slug, product_id), not
product_id: Yuyu-Tei numbers products within a category, and ids 10152-10154
were measured in both op01 and op13 denoting different cards.

Revision ID: b7d31e5c9a24
Revises: d7a4c2b91f08
Create Date: 2026-09-01 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d31e5c9a24'
down_revision: Union[str, Sequence[str], None] = 'd7a4c2b91f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'yuyutei_discovery_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='running', nullable=False),
        sa.Column('requested_set_slugs', sa.JSON(), nullable=True),
        sa.Column('pages_fetched', sa.Integer(), server_default='0', nullable=False),
        sa.Column('products_seen', sa.Integer(), server_default='0', nullable=False),
        sa.Column('candidates_written', sa.Integer(), server_default='0', nullable=False),
        sa.Column('foreign_series_filtered', sa.Integer(), server_default='0', nullable=False),
        sa.Column('duplicate_products', sa.Integer(), server_default='0', nullable=False),
        sa.Column('unparseable_codes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('stopped_reason', sa.String(length=255), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('per_slug_metrics_json', sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'denied', 'failed')",
            name='ck_yuyutei_discovery_runs_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'yuyutei_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discovery_run_id', sa.Integer(), nullable=True),
        sa.Column('set_slug', sa.String(length=32), nullable=False),
        sa.Column('product_id', sa.String(length=32), nullable=False),
        sa.Column('source_url', sa.String(length=1024), nullable=False),
        sa.Column('detected_card_code', sa.String(length=64), nullable=True),
        sa.Column('detected_rarity', sa.String(length=32), nullable=True),
        sa.Column('name_jp', sa.String(length=512), nullable=True),
        sa.Column('image_url', sa.String(length=1024), nullable=True),
        sa.Column('price_jpy', sa.Integer(), nullable=True),
        sa.Column('availability', sa.String(length=32), nullable=True),
        sa.Column('raw_listing_text', sa.Text(), nullable=True),
        sa.Column('match_status', sa.String(length=32), server_default='unmatched', nullable=False),
        sa.Column('matched_card_print_id', sa.Integer(), nullable=True),
        sa.Column('match_explanation_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "match_status IN ('unmatched', 'family_matched', 'print_matched', "
            "'identity_conflict')",
            name='ck_yuyutei_candidates_match_status',
        ),
        sa.CheckConstraint(
            "matched_card_print_id IS NULL OR match_status = 'print_matched'",
            name='ck_yuyutei_candidates_print_requires_print_matched',
        ),
        sa.CheckConstraint(
            "availability IS NULL OR availability IN ('in_stock', 'out_of_stock', "
            "'unknown_present_marker')",
            name='ck_yuyutei_candidates_availability',
        ),
        sa.CheckConstraint(
            'price_jpy IS NULL OR price_jpy > 0',
            name='ck_yuyutei_candidates_price_positive',
        ),
        sa.ForeignKeyConstraint(['discovery_run_id'], ['yuyutei_discovery_runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['matched_card_print_id'], ['card_prints.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('set_slug', 'product_id', name='uq_yuyutei_candidates_set_slug_product'),
    )
    op.create_index(op.f('ix_yuyutei_candidates_discovery_run_id'), 'yuyutei_candidates', ['discovery_run_id'], unique=False)
    op.create_index(op.f('ix_yuyutei_candidates_set_slug'), 'yuyutei_candidates', ['set_slug'], unique=False)
    op.create_index(op.f('ix_yuyutei_candidates_detected_card_code'), 'yuyutei_candidates', ['detected_card_code'], unique=False)
    op.create_index(op.f('ix_yuyutei_candidates_match_status'), 'yuyutei_candidates', ['match_status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_yuyutei_candidates_match_status'), table_name='yuyutei_candidates')
    op.drop_index(op.f('ix_yuyutei_candidates_detected_card_code'), table_name='yuyutei_candidates')
    op.drop_index(op.f('ix_yuyutei_candidates_set_slug'), table_name='yuyutei_candidates')
    op.drop_index(op.f('ix_yuyutei_candidates_discovery_run_id'), table_name='yuyutei_candidates')
    op.drop_table('yuyutei_candidates')
    op.drop_table('yuyutei_discovery_runs')
