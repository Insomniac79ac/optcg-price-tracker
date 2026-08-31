"""add source_card_mappings.last_collection_attempted_at

WHY A COLUMN AND NOT A DERIVED VALUE. Fair scheduling needs to know when the
price collector last ATTEMPTED a mapping, and nothing already stored can say
that:

  * price_observations.observed_at records only mappings that produced a
    price. On the 2026-08-31 run of 100 mappings, 96 verified their card but
    had no purchasable listing (`no_raw_condition_price_available`), so 96
    have no observation and never would.
  * raw_snapshots cannot stand in either. writer.py returns on `if reasons:`
    BEFORE the RawSnapshot is constructed, so a mapping with any blocking
    reason persists no snapshot at all - the same 96.
  * source_card_mappings.last_verified_at already means "a human reviewed
    this mapping" (app.api.source_mappings, admin_source_mapping_quality),
    and last_match_checked_at is owned by app.services.source_mapping_
    confidence. Reusing either would conflate human review, or match
    scoring, with machine collection.

So the attempt time is genuinely unexpressible today, which is the condition
this migration exists to satisfy.

NULL MEANS NEVER ATTEMPTED, and that is load-bearing: the scheduler orders
NULLS FIRST, so every existing mapping is treated as never-collected and is
drained before anything is revisited. No backfill is performed for exactly
that reason - inventing a timestamp would tell the scheduler a mapping had
been collected when it had not.

The index matches the scheduler's ORDER BY (last_collection_attempted_at ASC
NULLS FIRST, id ASC) so selection stays cheap as the mapping population
grows, which is the whole point of the change.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7a4c2b91f08"
down_revision: Union[str, Sequence[str], None] = "c9f31e2a7d04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "source_card_mappings",
        sa.Column("last_collection_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_source_card_mappings_collection_order",
        "source_card_mappings",
        ["last_collection_attempted_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_card_mappings_collection_order", table_name="source_card_mappings")
    op.drop_column("source_card_mappings", "last_collection_attempted_at")
