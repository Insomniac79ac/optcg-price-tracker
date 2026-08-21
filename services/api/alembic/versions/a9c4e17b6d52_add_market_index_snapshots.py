"""add market_index_snapshots table

Revision ID: a9c4e17b6d52
Revises: d7e2b9f4a1c3
Create Date: 2026-08-21 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a9c4e17b6d52'
down_revision: Union[str, Sequence[str], None] = 'd7e2b9f4a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Creates the append-only exact-print Market Index snapshot table - see
    app.models.market_index_snapshot for the full rationale. Purely additive:
    it creates one new table and touches no existing one. Nothing writes to it
    until app.snapshot_market_index is invoked, and there is no backfill here
    (nor anywhere else) - the first row's snapshot_date is whatever day the
    job first runs, which is the honest start of the series.

    provenance is JSONB on Postgres and plain JSON elsewhere, matching the
    column's with_variant declaration on the model so the SQLite test suite
    exercises the same column definition this migration produces.

    The unique constraint is (card_print_id, snapshot_date) - the identity the
    job's ON CONFLICT DO NOTHING keys on, which is what makes a same-day retry
    a no-op rather than a second row or an overwrite.
    """
    op.create_table(
        'market_index_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_print_id', sa.Integer(), nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('index_value_jpy', sa.Integer(), nullable=True),
        sa.Column('calculation_method', sa.String(length=64), nullable=False),
        sa.Column('source_count', sa.Integer(), nullable=False),
        sa.Column('coverage_status', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.String(length=16), nullable=False),
        sa.Column('source_price_range_low_jpy', sa.Integer(), nullable=True),
        sa.Column('source_price_range_high_jpy', sa.Integer(), nullable=True),
        sa.Column('index_version', sa.Integer(), nullable=False),
        sa.Column('source_semantics_version', sa.Integer(), nullable=False),
        sa.Column('freshest_eligible_source_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stalest_eligible_source_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'provenance',
            sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coverage_status IN ('full', 'limited', 'none')",
            name='ck_market_index_snapshots_coverage_status',
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name='ck_market_index_snapshots_confidence',
        ),
        sa.CheckConstraint(
            '(index_value_jpy IS NULL) = (coverage_status = \'none\')',
            name='ck_market_index_snapshots_value_presence',
        ),
        # The source price range is one value stored across two columns:
        # present together or absent together, and ordered when present. See
        # the matching constraints on app.models.market_index_snapshot for the
        # reasoning, including why low == high is deliberately allowed.
        sa.CheckConstraint(
            '(source_price_range_low_jpy IS NULL) = '
            '(source_price_range_high_jpy IS NULL)',
            name='ck_market_index_snapshots_range_pairing',
        ),
        sa.CheckConstraint(
            'source_price_range_low_jpy IS NULL '
            'OR source_price_range_low_jpy <= source_price_range_high_jpy',
            name='ck_market_index_snapshots_range_order',
        ),
        # RESTRICT, not CASCADE: deleting a print that Atlas has published
        # index history for should fail loudly, not silently truncate the
        # series. Same choice PriceObservation makes for its own lineage FK.
        sa.ForeignKeyConstraint(
            ['card_print_id'], ['card_prints.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'card_print_id', 'snapshot_date', name='uq_market_index_snapshots_print_date'
        ),
    )
    op.create_index(
        'ix_market_index_snapshots_card_print_id', 'market_index_snapshots', ['card_print_id']
    )
    op.create_index(
        'ix_market_index_snapshots_snapshot_date', 'market_index_snapshots', ['snapshot_date']
    )
    op.create_index(
        'ix_market_index_snapshots_print_calculated',
        'market_index_snapshots',
        ['card_print_id', 'calculated_at'],
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops only the table this revision created, and with it every snapshot
    ever written - which is unrecoverable, since snapshots cannot be
    reconstructed from price_observations after the fact (see the model's
    "No backfill"). Safe to run only before the job has ever produced rows
    worth keeping.
    """
    op.drop_index(
        'ix_market_index_snapshots_print_calculated', table_name='market_index_snapshots'
    )
    op.drop_index(
        'ix_market_index_snapshots_snapshot_date', table_name='market_index_snapshots'
    )
    op.drop_index(
        'ix_market_index_snapshots_card_print_id', table_name='market_index_snapshots'
    )
    op.drop_table('market_index_snapshots')
