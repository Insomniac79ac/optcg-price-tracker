"""add price_observations.promotion_state

WHY A COLUMN AND NOT A DERIVED VALUE. Whether a source displayed its own
promotional state is a fact about the PAGE at capture time, and nothing
already stored can reconstruct it:

  * price_jpy cannot. A sale price and an ordinary price are both just
    integers, and the sale prices measured on 2026-09-02 (80, 120, 180, 220)
    are all values that ordinary listings also carry. Any rule keyed on
    magnitude would be inventing a threshold the source does not have.
  * app.services.source_semantics cannot derive it either. That module is a
    pure function of (source, price_type, value_jpy) by design, and
    promotional state is not a function of the value - which is precisely why
    it has to be stored rather than classified at read time.
  * yuyutei_candidates cannot stand in. It has no promotion field, its rows
    are UPSERTed in place per discovery run (so a row records current state,
    not the state at any past instant), and it describes a listing page
    fetched hours apart from the product page an observation comes from.
    price_observations has no provenance link to a Yuyu candidate at all.

So the fact is genuinely unexpressible today, which is the condition this
migration exists to satisfy. The collector reads it from the product page it
already fetches, and writes it here.

NULL MEANS NOT DETERMINED, AND THAT IS LOAD-BEARING. It covers two situations
that must never be confused with "no promotion": a row written before this
column existed, and a row whose page markers disagreed. Hence a three-valued
string rather than a boolean.

NO BACKFILL IS PERFORMED, and that is a decision rather than an omission. The
549 Yuyu observations already stored include known sale-priced ones - prints
4, 12, 14 and 17 carried a SALE badge and a struck former price on every one
of their 105 captured product pages between 2026-08-08 and 2026-09-01. Setting
them all to 'none' would be false; setting those four to 'sale' would claim
Atlas classified them at capture time when it did not. Leaving them NULL is
the only honest answer, and it is exactly what NULL is defined to mean above.
This migration therefore issues no UPDATE and mutates no existing row: it adds
a nullable column and a CHECK, and nothing else.

THE CHECK IS THE VOCABULARY. Postgres, not convention, is what stops a value
outside {'none', 'sale'} landing in the column - a string source_semantics has
no rule for would be silently treated as unconstrained, which is the one
failure mode that would be invisible in the published Market Index.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4a7e9d15b83"
down_revision: Union[str, Sequence[str], None] = "b7d31e5c9a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "price_observations",
        sa.Column("promotion_state", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_price_observations_promotion_state",
        "price_observations",
        "promotion_state IS NULL OR promotion_state IN ('none', 'sale')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_price_observations_promotion_state",
        "price_observations",
        type_="check",
    )
    op.drop_column("price_observations", "promotion_state")
