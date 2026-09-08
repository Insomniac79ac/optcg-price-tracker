"""What is IN the Card Pirate Index on one published day, by rarity.

READ-ONLY, AND ARCHIVE-ONLY. The population is the constituent set behind a
PUBLISHED `card_pirate_index_points` row, reconstructed from the archived
`market_index_snapshots` for that point's own two days. Nothing here calls the
live pricing resolver, reads `price_observations`, touches
`/analytics/market/overview`'s composition, or recomputes a source price. The
only numbers this module produces are counts of prints and a percentage of a
count.

WHY THE POPULATION IS NOT "THE CATALOGUE"
-----------------------------------------
On 2026-09-07 the catalogue held 4,316 active prints, 305 of them valued, and
296 of those were constituents. Those are three different populations and only
the last one is what the index measured. A rarity chart drawn from the first
would be a chart of Bandai's release history; drawn from the second it would
include prints that produced no return. Neither is "what is in the index".

WHY MEMBERSHIP IS NOT RE-DECIDED HERE
-------------------------------------
Constituency is a pairwise property of two days, not a column, so it has to be
derived - but it is derived by `card_pirate_index.constituent_print_ids`,
which shares its predicate with `compute_step` itself. This module states no
rule of its own about who is a constituent. If it did, the rarity buckets
would be free to disagree with the `constituent_count` printed beside them.

WHY THE LABELS ARE CURRENT AND THE POPULATION IS ARCHIVED
---------------------------------------------------------
The print ids come from the archive; their rarity comes from today's
catalogue. That split is deliberate. Rarity is Bandai metadata that gets
corrected by re-import, and a histogram frozen at write time would be
permanently wrong afterwards with no way to fix it. So a correction moves the
LABELS on a historical composition and never the population - which is the
honest behaviour, and the reason this is derived at read time rather than
persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical_card import CanonicalCard
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.card_print import CardPrint
from app.services.card_pirate_index import (
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    constituent_print_ids,
)
from app.services.card_pirate_index_replay import load_snapshot_days
from app.services.print_catalogue import effective_rarity_sql
from app.services.rarity_facets import facet_value

# The bucket for a print whose effective rarity is absent.
#
# BOTH source columns are nullable - `card_prints.official_rarity` and
# `canonical_cards.rarity` - so this is not hypothetical, it is merely zero
# today. Dropping such a print would break `sum(count) == constituent_count`
# silently, which is precisely the kind of quiet arithmetic hole the integrity
# guard below exists to prevent; an explicit bucket keeps the invariant true by
# construction. The key is a token no Bandai rarity uses.
UNKNOWN_RARITY_KEY = "UNKNOWN"
UNKNOWN_RARITY_LABEL = "Unknown"

# Percentages are quantised to two places with banker's rounding, the same
# rounding the estimator uses for its own quantisation. Deterministic, so the
# same archived day always yields byte-identical output.
_PCT_PLACES = Decimal("0.01")


class CompositionIntegrityError(RuntimeError):
    """The derived constituent set contradicts the published point.

    FAIL CLOSED. The read path derives membership from `market_index_snapshots`
    while `constituent_count` was written from those same rows at write time,
    so the two agreeing is the whole basis for deriving rather than persisting.
    If a snapshot backfill ever rewrote a past day, the derivation would drift
    and this endpoint would start publishing a rarity breakdown that summed to
    a different number than the count the index itself published. Answering
    with a contradiction is worse than answering with an error, so this raises
    and the route turns it into a 500.
    """


@dataclass(frozen=True)
class RarityBucket:
    key: str
    label: str
    count: int
    pct: Decimal


@dataclass(frozen=True)
class IndexCompositionOut:
    as_of: date
    constituent_count: int
    rarity: tuple[RarityBucket, ...]


def _published_point(
    db: Session,
    *,
    on: date | None,
    scope_kind: str,
    scope_key: str,
    methodology_version: int,
) -> CardPirateIndexPoint | None:
    """The point this composition is about, or None.

    "Published" means `index_value IS NOT NULL`, the same test the index read
    path applies - an unpublishable day (section 5.4) is not a day the product
    ever showed a level for, so it is not a day it can describe the contents
    of either.

    A supplied date selects EXACTLY that day. It never falls back to the
    nearest one: a caller asking about 2026-09-05 and silently receiving
    2026-09-04's composition would have no way to tell, and would caption
    someone else's numbers with their own date.
    """
    stmt = select(CardPirateIndexPoint).where(
        CardPirateIndexPoint.scope_kind == scope_kind,
        CardPirateIndexPoint.scope_key == scope_key,
        CardPirateIndexPoint.methodology_version == methodology_version,
        CardPirateIndexPoint.index_value.is_not(None),
    )
    if on is not None:
        stmt = stmt.where(CardPirateIndexPoint.point_date == on)
    else:
        stmt = stmt.order_by(CardPirateIndexPoint.point_date.desc())
    return db.execute(stmt.limit(1)).scalars().first()


def _rarity_buckets(db: Session, print_ids: tuple[int, ...]) -> tuple[RarityBucket, ...]:
    """Count the constituents by catalogue rarity.

    IDENTITY METADATA ONLY. The join is `card_prints -> canonical_cards` and
    reaches no pricing table; `effective_rarity_sql()` and `facet_value()` are
    the very expression and folding the print catalogue's `?rarity=` filter
    uses, so a bucket here selects the same prints that bucket selects at
    /cards. Introducing a second rarity vocabulary would give the product two
    answers to "what rarity is this print".
    """
    if not print_ids:
        return ()

    rarity = effective_rarity_sql()
    rows = db.execute(
        select(CardPrint.id, rarity)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(CardPrint.id.in_(print_ids))
    ).all()

    counts: dict[str, int] = {}
    seen: set[int] = set()
    for print_id, value in rows:
        seen.add(print_id)
        key = UNKNOWN_RARITY_KEY if value is None else facet_value(value)
        counts[key] = counts.get(key, 0) + 1

    # A constituent with no catalogue row at all is still a constituent, and
    # dropping it would break the sum. It cannot happen while
    # market_index_snapshots.card_print_id is a RESTRICT foreign key, which is
    # exactly why this costs one line rather than a migration.
    missing = len(print_ids) - len(seen)
    if missing:
        counts[UNKNOWN_RARITY_KEY] = counts.get(UNKNOWN_RARITY_KEY, 0) + missing

    total = len(print_ids)
    buckets = [
        RarityBucket(
            key=key,
            label=UNKNOWN_RARITY_LABEL if key == UNKNOWN_RARITY_KEY else key,
            count=count,
            # Display metadata, computed from the two integers beside it.
            # Rounded independently per bucket and never nudged to force the
            # column to total 100: adjusting one bucket to absorb the rounding
            # residue would make that bucket's printed share disagree with its
            # own count, which is a worse lie than a column that sums to
            # 99.99.
            pct=(Decimal(count) * 100 / Decimal(total)).quantize(
                _PCT_PLACES, rounding=ROUND_HALF_EVEN
            ),
        )
        for key, count in counts.items()
    ]
    # Largest first, ties broken by key so the order is total rather than
    # merely mostly-determined - and UNKNOWN last whatever its size, because it
    # is an absence rather than a rarity and should not lead the chart.
    buckets.sort(key=lambda b: (b.key == UNKNOWN_RARITY_KEY, -b.count, b.key))
    return tuple(buckets)


def get_index_composition(
    db: Session,
    *,
    on: date | None = None,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    methodology_version: int = METHODOLOGY_VERSION,
) -> IndexCompositionOut | None:
    """Rarity composition of one published point's constituent set.

    `None` means there is no published point for the request - the route turns
    that into a 404 rather than substituting a neighbouring day.
    """
    point = _published_point(
        db,
        on=on,
        scope_kind=scope_kind,
        scope_key=scope_key,
        methodology_version=methodology_version,
    )
    if point is None:
        return None

    # A base point opens a segment: it came from no step, so it has no prior
    # day and, by `ck_cpi_points_base_has_no_step`, no constituents. There is
    # nothing to reconstruct and nothing to draw - an empty list, not a
    # fabricated one, and not a division by zero.
    if point.prior_point_date is None or point.constituent_count == 0:
        if point.constituent_count != 0:
            raise CompositionIntegrityError(
                f"point {point.point_date} has no prior day but "
                f"constituent_count={point.constituent_count}"
            )
        return IndexCompositionOut(
            as_of=point.point_date, constituent_count=0, rarity=()
        )

    # The same archived query the writer and the replay use, narrowed to the
    # two days this step spanned. `load_snapshot_days` returns only rows with a
    # non-NULL index_value_jpy, which is membership rule 1.
    days = {
        day.point_date: day
        for day in load_snapshot_days(
            db, history_start=point.prior_point_date, end=point.point_date
        )
    }
    current = days.get(point.point_date)
    prior = days.get(point.prior_point_date)
    if current is None or prior is None:
        raise CompositionIntegrityError(
            f"archived snapshots missing for {point.prior_point_date} -> "
            f"{point.point_date}; cannot reconstruct the constituent set"
        )

    # Rules 2 and 3, from the estimator's own predicate.
    print_ids = constituent_print_ids(prior, current)

    # MANDATORY. The derivation must reproduce what the index published, or
    # this endpoint says nothing at all.
    if len(print_ids) != point.constituent_count:
        raise CompositionIntegrityError(
            f"derived {len(print_ids)} constituents for {point.point_date} but "
            f"the published point carries {point.constituent_count}"
        )

    return IndexCompositionOut(
        as_of=point.point_date,
        constituent_count=point.constituent_count,
        rarity=_rarity_buckets(db, print_ids),
    )


__all__ = [
    "UNKNOWN_RARITY_KEY",
    "UNKNOWN_RARITY_LABEL",
    "CompositionIntegrityError",
    "IndexCompositionOut",
    "RarityBucket",
    "get_index_composition",
]
