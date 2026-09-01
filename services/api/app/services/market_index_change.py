"""Seven-day Market Index movement for a print, or nothing at all.

WHAT THIS ANSWERS. "Has the Market Index moved?" - never "has a source price
moved?". Both ends of the comparison are Market Index values: today's live
index and the immutable one Atlas published exactly seven UTC calendar days
ago (app.models.market_index_snapshot). A source price is never compared to an
index, and no source series is consulted.

WHY THE TEST IS SO STRICT. An index whose contributing evidence changed
between the two dates has not "moved" in any sense a collector would
recognise: a print that lost its Yuyu-Tei retail price and gained a SNKRDUNK
listing floor keeps source_count = 1 while the number underneath switches from
a retail asking price to a platform listing floor. Reporting that as -40% would
be describing a change of measuring instrument as a change of price. So the
eligible contributor SETS must be identical at both ends, compared by
(source, reference_type) identity - never by source_count, which cannot tell
those two one-source cases apart.

WHAT IS DELIBERATELY ABSENT. There is no nearest-date search, no "latest
snapshot minus seven", no 24h or 30d fallback, no source-series substitute and
no stale-observation rescue. The contract is an exact UTC calendar-date match,
and everything else is null. That makes one missed snapshot run null the field
for a week, which is the intended price of never showing a baseline Atlas did
not actually publish.

PROVENANCE IS LOAD-BEARING HERE, ON PURPOSE. `market_index_snapshots.provenance`
is documented as a write-once archive rather than a query target, and that is
respected: this module never filters, indexes or joins on the JSON. It READS
the archived `source_values` in the application layer to answer the one
question the archive exists to answer - what evidence was this number built
from? Nothing else can answer it: the scalar columns record how MANY sources
contributed, never which. Because the field now depends on that archive, the
archive's shape is part of this contract; a malformed or absent one yields
null rather than a guess.

This module computes no index and changes no rule. INDEX_VERSION and
SOURCE_SEMANTICS_VERSION are read, never written or bumped - a derived
comparison is not a methodology change.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketIndexSnapshot
from app.schemas import MarketIndexSourceValueOut, PrintMarketIndexOut

# The one window this contract offers. Not configurable, because a caller that
# could ask for "5d" would be asking for a baseline that may not exist and
# would then want a fallback - which is exactly what this module refuses.
COMPARISON_WINDOW_DAYS = 7

# One eligible contributor, identified the only way that survives a source
# changing what it reports: which source, and which kind of price. Two
# printings can both have source_count = 1 and be measuring entirely different
# things; this pair is what tells them apart.
ContributorKey = tuple[str, str]


def eligible_contributor_set(source_values: list[Any]) -> set[ContributorKey] | None:
    """The (source, reference_type) pairs that actually counted toward an index.

    The predicate is `eligible and value_jpy is not None` - character for
    character the one app.snapshot_market_index._eligible_contributors and
    market_index._compute_index_fields both use, so the historical and live
    sides of a comparison can never silently disagree about what "contributed"
    means. That is the whole reason this helper exists in one place.

    Accepts either Pydantic `MarketIndexSourceValueOut` objects (the live side)
    or the plain dicts `provenance` stores (the historical side), because the
    archive holds `model_dump(mode="json")` output rather than models.

    Returns None - NOT an empty set - when the input cannot be read as a list
    of source values with the three fields this predicate needs. A caller must
    treat None as "cannot prove comparability" and refuse the comparison; an
    empty set would say "nothing contributed", which is a different and much
    stronger claim than "the archive did not tell me".
    """
    if not isinstance(source_values, list):
        return None

    contributors: set[ContributorKey] = set()
    for entry in source_values:
        if isinstance(entry, MarketIndexSourceValueOut):
            eligible, value_jpy = entry.eligible, entry.value_jpy
            source, reference_type = entry.source, entry.reference_type
        elif isinstance(entry, dict):
            # Every field is required. A provenance row missing any of them is
            # not a contributor whose identity can be proven, and guessing at
            # one would defeat the point of the check.
            if not {"source", "reference_type", "eligible", "value_jpy"} <= entry.keys():
                return None
            eligible, value_jpy = entry["eligible"], entry["value_jpy"]
            source, reference_type = entry["source"], entry["reference_type"]
        else:
            return None

        if not isinstance(source, str) or not isinstance(reference_type, str):
            return None
        if eligible is True and value_jpy is not None:
            contributors.add((source, reference_type))

    return contributors


def _baseline_date(today: date | None = None) -> date:
    """The exact UTC calendar date a baseline must carry. `today` is injectable
    for tests only; production always reads the real UTC date, never the
    caller's local one."""
    reference = today if today is not None else datetime.now(timezone.utc).date()
    return reference - timedelta(days=COMPARISON_WINDOW_DAYS)


def _percent_change(baseline: int, current: int) -> float:
    """((current - baseline) / baseline) * 100.

    Not rounded and not classified into rise/fall: the API serializes a float
    and the caller decides how to present it. A genuine 0.0 is a measurement -
    the index was the same seven days ago - and is returned as 0.0, never
    collapsed into the null that means "no comparable baseline".
    """
    return ((current - baseline) / baseline) * 100.0


def _change_for(
    snapshot: MarketIndexSnapshot | None, market_index: PrintMarketIndexOut
) -> float | None:
    """The strict comparison for one print, or None. Every guard below is a
    reason a percentage would have been misleading."""
    if snapshot is None:
        return None

    baseline_value = snapshot.index_value_jpy
    if baseline_value is None or baseline_value <= 0:
        # <= 0 rather than == 0: a non-positive baseline is not a denominator,
        # and a negative one would silently flip the sign of the result.
        return None
    if market_index.index_value_jpy is None:
        return None

    # A number produced under a different ruleset is not comparable to one
    # produced under this one, however close the two look.
    if snapshot.index_version != market_index.index_version:
        return None
    if snapshot.source_semantics_version != market_index.source_semantics_version:
        return None

    provenance = snapshot.provenance
    if not isinstance(provenance, dict):
        return None
    baseline_set = eligible_contributor_set(provenance.get("source_values"))
    current_set = eligible_contributor_set(market_index.source_values)
    if baseline_set is None or current_set is None:
        return None
    # A real, non-empty set on both sides. An index resting on nothing is not a
    # thing to measure movement in, and two empty sets must not compare equal.
    if not baseline_set or not current_set:
        return None
    if baseline_set != current_set:
        return None

    return _percent_change(baseline_value, market_index.index_value_jpy)


def get_index_change_7d_for_prints(
    db: Session,
    index_by_print: dict[int, PrintMarketIndexOut],
    *,
    today: date | None = None,
) -> dict[int, float | None]:
    """Seven-day movement for every print in `index_by_print`, batched.

    ONE query for the whole page, never one per print: the baseline rows are
    fetched with a single `card_print_id IN (...) AND snapshot_date = ?`, which
    is served directly by the unique (card_print_id, snapshot_date) index. The
    current side is not recomputed at all - it is the caller's already-computed
    index map, so a page cannot end up comparing against a second, independently
    derived set of current values.

    Every requested print id appears in the result exactly once, with None
    meaning "no comparable baseline". Callers therefore never need to guard a
    missing key, and a print can never receive two answers.
    """
    if not index_by_print:
        return {}

    print_ids = list(index_by_print)
    rows = db.scalars(
        select(MarketIndexSnapshot).where(
            MarketIndexSnapshot.card_print_id.in_(print_ids),
            MarketIndexSnapshot.snapshot_date == _baseline_date(today),
        )
    ).all()
    # The (card_print_id, snapshot_date) uniqueness constraint makes this map
    # total by construction - one row per print at most.
    snapshot_by_print = {row.card_print_id: row for row in rows}

    return {
        print_id: _change_for(snapshot_by_print.get(print_id), market_index)
        for print_id, market_index in index_by_print.items()
    }
