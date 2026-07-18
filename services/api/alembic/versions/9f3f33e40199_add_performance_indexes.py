"""add performance indexes

Revision ID: 9f3f33e40199
Revises: a1c9e4d7f2b6
Create Date: 2026-07-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f3f33e40199'
down_revision: Union[str, Sequence[str], None] = 'a1c9e4d7f2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds indexes identified by the db-index-audit performance review (see
    app.services.db_index_audit and GET /admin/db-index-audit) - none of
    these duplicate an existing index; every one is a genuinely new column
    or column-combination. Safe for existing data: CREATE INDEX (without
    CONCURRENTLY, matching every other migration in this repo, all of which
    run inside Alembic's own transaction) only reads the table to build the
    index, it never modifies row data.
    """
    op.create_index(op.f('ix_cards_rarity'), 'cards', ['rarity'], unique=False)
    op.create_index(op.f('ix_cards_language'), 'cards', ['language'], unique=False)

    op.create_index(
        op.f('ix_source_card_mappings_source_url'),
        'source_card_mappings',
        ['source_url'],
        unique=False,
    )

    op.create_index(
        op.f('ix_price_observations_price_type'), 'price_observations', ['price_type'], unique=False
    )
    # Backs the latest-price-per-(card, source, price_type) window-function
    # query in app.services.latest_prices - card_id/source_id/price_type is
    # the partition key, observed_at last so the same index also serves
    # ORDER BY observed_at DESC within each partition.
    op.create_index(
        'ix_price_observations_card_source_type_observed',
        'price_observations',
        ['card_id', 'source_id', 'price_type', 'observed_at'],
        unique=False,
    )
    op.create_index(
        'ix_price_observations_source_observed',
        'price_observations',
        ['source_id', 'observed_at'],
        unique=False,
    )

    op.create_index(
        op.f('ix_raw_snapshots_source_url'), 'raw_snapshots', ['source_url'], unique=False
    )

    op.create_index(
        op.f('ix_collection_items_created_at'), 'collection_items', ['created_at'], unique=False
    )

    op.create_index(
        op.f('ix_wishlist_items_target_buy_price_jpy'),
        'wishlist_items',
        ['target_buy_price_jpy'],
        unique=False,
    )

    op.create_index(
        op.f('ix_grading_submissions_grading_company'),
        'grading_submissions',
        ['grading_company'],
        unique=False,
    )

    op.create_index(
        op.f('ix_collector_notes_created_at'), 'collector_notes', ['created_at'], unique=False
    )

    op.create_index(op.f('ix_search_history_query'), 'search_history', ['query'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_search_history_query'), table_name='search_history')
    op.drop_index(op.f('ix_collector_notes_created_at'), table_name='collector_notes')
    op.drop_index(
        op.f('ix_grading_submissions_grading_company'), table_name='grading_submissions'
    )
    op.drop_index(
        op.f('ix_wishlist_items_target_buy_price_jpy'), table_name='wishlist_items'
    )
    op.drop_index(op.f('ix_collection_items_created_at'), table_name='collection_items')
    op.drop_index(op.f('ix_raw_snapshots_source_url'), table_name='raw_snapshots')
    op.drop_index('ix_price_observations_source_observed', table_name='price_observations')
    op.drop_index(
        'ix_price_observations_card_source_type_observed', table_name='price_observations'
    )
    op.drop_index(op.f('ix_price_observations_price_type'), table_name='price_observations')
    op.drop_index(
        op.f('ix_source_card_mappings_source_url'), table_name='source_card_mappings'
    )
    op.drop_index(op.f('ix_cards_language'), table_name='cards')
    op.drop_index(op.f('ix_cards_rarity'), table_name='cards')
