"""add print-scoped price observation index

Revision ID: d7e2b9f4a1c3
Revises: b858237e3706
Create Date: 2026-08-19 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd7e2b9f4a1c3'
down_revision: Union[str, Sequence[str], None] = 'b858237e3706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds the exact-print counterpart of
    ix_price_observations_card_source_type_observed (see
    9f3f33e40199_add_performance_indexes), which covers only the legacy
    card_id-keyed path. Since b858237e3706 added print lineage, every public
    price read goes through app.services.print_pricing/print_market_index,
    which filter on card_print_id instead - see
    docs/print_centric_pricing.md - and had only the single-column
    ix_price_observations_card_print_id (b858237e3706) available.

    Column order mirrors the legacy index exactly: (card_print_id, source_id,
    price_type) is the partition key of the ROW_NUMBER() window in
    get_latest_prices_for_prints, and observed_at comes last so the same
    index also covers the trailing range/ORDER BY within a series.

    Measured on Postgres 16 against 40k seeded observations over 20 prints:
    print_market_index's sold/floor window - (card_print_id IN ..., source_id
    =, price_type =, observed_at >= cutoff) - plans onto this index as a
    single index scan on all four columns. Queries predicating on
    card_print_id alone (get_latest_prices_for_prints,
    get_price_history_for_print) continue to prefer the narrower
    single-column index and sort afterwards, which is why that index is left
    in place: the two coexist exactly as ix_price_observations_card_id
    coexists with the legacy composite.

    Additive and safe for existing rows: CREATE INDEX (without CONCURRENTLY,
    matching every other migration in this repo, all of which run inside
    Alembic's own transaction) only reads the table to build the index - it
    never modifies, rewrites or backfills row data, and it adds no
    constraint. Rows with card_print_id IS NULL (legacy, lineage-less
    observations) are simply indexed under a NULL leading key and keep using
    the legacy index for their own card_id-keyed reads.
    """
    op.create_index(
        'ix_price_observations_print_source_type_observed',
        'price_observations',
        ['card_print_id', 'source_id', 'price_type', 'observed_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops only the index this revision created. No data is touched, and the
    pre-existing ix_price_observations_card_print_id single-column index
    (owned by b858237e3706) is deliberately left in place - it is not this
    revision's to remove.
    """
    op.drop_index(
        'ix_price_observations_print_source_type_observed', table_name='price_observations'
    )
