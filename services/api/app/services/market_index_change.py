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

Since Market Index v2 the contributor test is `contributes_to_index`, not
`eligible` - see `eligible_contributor_set`. The two stopped meaning the same
thing the moment an admissible-but-non-contributing fallback became possible,
and this module needs the narrower one: it compares the evidence a number was
BUILT from, not the evidence displayed beside it.

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

    THE PREDICATE IS `contributes_to_index is True`, NOT `eligible`. Since
    Market Index v2 those are different questions (see
    app.services.market_index._compute_index_fields): an admissible SNKRDUNK
    listing floor that stood aside for a Yuyu-Tei retail price keeps
    eligible=true and keeps its raw number, but it did not go into the
    aggregate. Comparing on `eligible` would call two indexes comparable when
    one of them rested on evidence the other only displayed - the precise class
    of mistake this module exists to prevent.

    Accepts either Pydantic `MarketIndexSourceValueOut` objects (the live side)
    or the plain dicts `provenance` stores (the historical side), because the
    archive holds `model_dump(mode="json")` output rather than models.

    FAILS CLOSED WHEN THE ROLE CANNOT BE PROVEN. `contributes_to_index` is
    optional in the schema so the field could be added without breaking
    clients, and its None default means "this payload predates the field" - it
    never means "did not contribute". So a value carrying None, and a
    provenance dict lacking the key entirely, both return None here rather than
    being quietly read as a non-contributor. In practice a v1 archive is
    already rejected one guard earlier by the index_version equality test in
    `_change_for`; this is the second lock on the same door, and it is the one
    that still holds if someone ever relaxes the first.

    Returns None - NOT an empty set - for any input that cannot be read as a
    list of source values carrying every field this predicate needs. A caller
    must treat None as "cannot prove comparability" and refuse the comparison;
    an empty set would say "nothing contributed", which is a different and much
    stronger claim than "the archive did not tell me".
    """
    if not isinstance(source_values, list):
        return None

    contributors: set[ContributorKey] = set()
    for entry in source_values:
        if isinstance(entry, MarketIndexSourceValueOut):
            contributes, value_jpy = entry.contributes_to_index, entry.value_jpy
            source, reference_type = entry.source, entry.reference_type
        elif isinstance(entry, dict):
            # Every field is required. A provenance row missing any of them is
            # not a contributor whose identity can be proven, and guessing at
            # one would defeat the point of the check.
            required = {"source", "reference_type", "contributes_to_index", "value_jpy"}
            if not required <= entry.keys():
                return None
            contributes, value_jpy = entry["contributes_to_index"], entry["value_jpy"]
            source, reference_type = entry["source"], entry["reference_type"]
        else:
            return None

        if not isinstance(source, str) or not isinstance(reference_type, str):
            return None
        # None is "unknown", not "false" - refuse rather than assume.
        if contributes is None:
            return None
        if contributes is True and value_jpy is not None:
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


# Why a comparison was refused. These are the guards below, named, so a caller
# that must EXPLAIN the absence (the exact-print analytics headline) can say
# which rule bit instead of publishing a bare null. The two version tokens are
# deliberately the same strings app.services.print_series publishes as segment
# BREAK reasons, so one vocabulary describes a boundary whether a client meets
# it on the chart or in the headline.
NOT_COMPARABLE_NO_BASELINE = "no_comparable_baseline"
NOT_COMPARABLE_NON_POSITIVE_BASELINE = "non_positive_baseline"
NOT_COMPARABLE_NULL_VALUE = "null_archived_value"
NOT_COMPARABLE_INDEX_VERSION = "index_version_change"
NOT_COMPARABLE_SOURCE_SEMANTICS_VERSION = "source_semantics_version_change"
NOT_COMPARABLE_CONTRIBUTORS = "contributor_set_changed"


def comparability_refusal(
    *,
    baseline_value: int | None,
    baseline_index_version: int,
    baseline_source_semantics_version: int,
    baseline_source_values: Any,
    current_value: int | None,
    current_index_version: int,
    current_source_semantics_version: int,
    current_source_values: Any,
) -> str | None:
    """THE comparability rule for two per-print Market Index values, in one
    place. Returns the reason a comparison must be refused, or None when the
    two ends may legitimately be compared.

    Every guard here was already in `_change_for`; this function is that
    function's test list lifted out unchanged so a second caller cannot grow a
    second, subtly different definition of "comparable". `_change_for` now asks
    it, and so does the window comparison in
    app.services.print_analytics - there is no third copy.

    The per-print Market Index is NOT chain-linked. Unlike the aggregate Card
    Pirate Index, whose carried segments let a linked return be reported across
    a boundary, a print's index is a raw JPY combination whose ruleset can
    change underneath it. So a version boundary here is not a break to be
    reported alongside a number - it is a reason there is no number.
    """
    if baseline_value is None or current_value is None:
        return NOT_COMPARABLE_NULL_VALUE
    if baseline_value <= 0:
        # <= 0 rather than == 0: a non-positive baseline is not a denominator,
        # and a negative one would silently flip the sign of the result.
        return NOT_COMPARABLE_NON_POSITIVE_BASELINE

    # A number produced under a different ruleset is not comparable to one
    # produced under this one, however close the two look.
    if baseline_index_version != current_index_version:
        return NOT_COMPARABLE_INDEX_VERSION
    if baseline_source_semantics_version != current_source_semantics_version:
        return NOT_COMPARABLE_SOURCE_SEMANTICS_VERSION

    baseline_set = eligible_contributor_set(baseline_source_values)
    current_set = eligible_contributor_set(current_source_values)
    if baseline_set is None or current_set is None:
        return NOT_COMPARABLE_CONTRIBUTORS
    # A real, non-empty set on both sides. An index resting on nothing is not a
    # thing to measure movement in, and two empty sets must not compare equal.
    if not baseline_set or not current_set:
        return NOT_COMPARABLE_CONTRIBUTORS
    if baseline_set != current_set:
        return NOT_COMPARABLE_CONTRIBUTORS
    return None


def snapshot_source_values(snapshot: MarketIndexSnapshot) -> Any:
    """The archived `source_values` list, or None when the archive cannot be
    read as one. Never a guess and never an empty list standing in for an
    unreadable archive - `comparability_refusal` must be able to tell "nothing
    contributed" from "the archive did not say"."""
    provenance = snapshot.provenance
    if not isinstance(provenance, dict):
        return None
    return provenance.get("source_values")


def _change_for(
    snapshot: MarketIndexSnapshot | None, market_index: PrintMarketIndexOut
) -> float | None:
    """The strict comparison for one print, or None.

    The guards live in `comparability_refusal`; this function is the 7-day
    live-vs-archived caller of them.
    """
    if snapshot is None:
        return None

    refusal = comparability_refusal(
        baseline_value=snapshot.index_value_jpy,
        baseline_index_version=snapshot.index_version,
        baseline_source_semantics_version=snapshot.source_semantics_version,
        baseline_source_values=snapshot_source_values(snapshot),
        current_value=market_index.index_value_jpy,
        current_index_version=market_index.index_version,
        current_source_semantics_version=market_index.source_semantics_version,
        current_source_values=market_index.source_values,
    )
    if refusal is not None:
        return None

    # Narrowed by the guards above; asserted for the type checker only.
    assert snapshot.index_value_jpy is not None
    assert market_index.index_value_jpy is not None
    return _percent_change(snapshot.index_value_jpy, market_index.index_value_jpy)


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
