"""ONE definition of "which price a basis selects, and when it is usable".

WHY THIS MODULE EXISTS. Two surfaces now answer questions about the same
basis: `/analytics/market/overview` aggregates over a scope, and `GET /prints`
filters a catalogue page down to the prints that basis can actually price. If
each carried its own idea of "usable", the strip of cards under a chart could
show a print the chart never counted - the two would disagree about the same
catalogue on the same screen. So the rule lives here once and both read it.

It sits BELOW both callers on purpose. `app.services.market_analytics` already
imports `app.services.print_catalogue` (for `effective_rarity_sql`), so the
catalogue cannot import analytics back without a cycle. This module depends
only on the basis grammar in `app.services.print_series`, which is where that
vocabulary is already published.

IT DEFINES NO PRICING SEMANTICS OF ITS OWN. Eligibility, the platform floor,
the sale-price constraint and the index combination rule are decided by
`app.services.source_semantics` and `app.services.market_index`, and arrive
here already decided on a resolved `PrintMarketIndexOut`. This module only
READS two fields the resolver already set, and it names no source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.print_series import KIND_MARKET_INDEX, KIND_SOURCE

MARKET_INDEX_BASIS = KIND_MARKET_INDEX
SOURCE_BASIS_PREFIX = f"{KIND_SOURCE}:"


class BasisError(ValueError):
    """A price_basis string the grammar does not accept."""


@dataclass(frozen=True)
class BasisRequest:
    """One parsed `price_basis`, in the SAME grammar the print series endpoint
    already publishes (`market_index` | `source:<name>` - see
    app.services.print_series.parse_series_key).

    Reusing that grammar rather than inventing a second one is the whole
    point: a collector who selected a platform on a print page and then opens
    analytics is selecting the same thing, spelled the same way, and a saved
    URL means one thing across the product. No source name is validated here -
    an unconfigured one resolves to an explicitly unavailable answer later,
    exactly as a series key does.
    """

    key: str
    kind: str
    source_name: str | None = None


def parse_price_basis(raw: str | None) -> BasisRequest:
    """`market_index` (the default) or `source:<name>`. Nothing else."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return BasisRequest(key=MARKET_INDEX_BASIS, kind=KIND_MARKET_INDEX)
    if cleaned == MARKET_INDEX_BASIS:
        return BasisRequest(key=MARKET_INDEX_BASIS, kind=KIND_MARKET_INDEX)
    if cleaned.startswith(SOURCE_BASIS_PREFIX):
        name = cleaned[len(SOURCE_BASIS_PREFIX) :].strip()
        if not name:
            raise BasisError("A source basis must name a source, e.g. source:<name>")
        return BasisRequest(key=f"{SOURCE_BASIS_PREFIX}{name}", kind=KIND_SOURCE, source_name=name)
    raise BasisError(
        f"Invalid price_basis '{cleaned}'. Expected '{MARKET_INDEX_BASIS}' or 'source:<name>'."
    )


def usable_basis_value(index: Any, basis: BasisRequest) -> int | None:
    """The CURRENT usable number this basis reports for one print, else None.

    `index` is a resolved `PrintMarketIndexOut` - the same object
    `/prints/{id}/market-index` serves - so a filter built on this can never
    disagree with the print page a collector clicks through to.

    None means "this basis does not price this print", and it is the only way
    that is ever said. There is no zero here: `¥0` would be a measurement, and
    a caller that rendered a missing price as ¥0 would be inventing one.

    THE SOURCE BRANCH REQUIRES BOTH CONDITIONS, and that pairing is the whole
    correctness of it. `eligible` alone is not a price when no number was
    reported; a number alone is not a price when source semantics disqualified
    it. A platform-minimum listing floor is exactly the second case - a real
    integer that is not a market price - and it must never be returned here.

    IT NEVER SUBSTITUTES A DIFFERENT SOURCE. The loop matches on the requested
    name and returns None when that source has nothing usable, so a print one
    platform prices happily is still unpriced under a platform that does not
    price it. Filling the gap from a neighbour would tell a collector that the
    platform they selected quotes a price it never quoted.

    NO SOURCE NAME APPEARS IN THIS FUNCTION. Whatever sources the resolvers
    produced are the sources this understands, so a newly configured platform
    works the day it is registered, with no edit here.
    """
    if basis.kind == KIND_MARKET_INDEX:
        return index.index_value_jpy
    for source_value in index.source_values:
        if source_value.source != basis.source_name:
            continue
        if source_value.eligible and source_value.value_jpy is not None:
            return source_value.value_jpy
    return None


__all__ = [
    "MARKET_INDEX_BASIS",
    "SOURCE_BASIS_PREFIX",
    "BasisError",
    "BasisRequest",
    "parse_price_basis",
    "usable_basis_value",
]
