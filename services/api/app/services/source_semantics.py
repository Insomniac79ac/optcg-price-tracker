"""Source-specific semantics for a single stored price observation - the one
authoritative place that answers "does this source/price_type/value combination
mean what its number literally says?".

Why a separate leaf module
---------------------------
This module imports nothing from the application. That is deliberate: the
intended caller is app.services.market_index's per-source resolvers, and
market_index will import *this* module, so importing anything back from
market_index here would create a cycle at module load. The source-name and
price_type constants below are therefore restated rather than imported from
market_index, and the two must stay in agreement - see "Stored vs API-facing
names" below for the trap that makes restating them worth the duplication.

Stored vs API-facing names (audit correction, Task 1C-1)
---------------------------------------------------------
Classification keys off the value stored in price_observations.price_type,
which for SNKRDUNK is ``"floor"`` (written by
services/snkrdunk_collector/snkrdunk_collector/writer.py). It is NOT
``"listing_floor"`` - that string exists only as the API-facing
``reference_type`` on MarketIndexSourceValueOut (set in
app.services.market_index._resolve_snkrdunk). A rule keyed on
``"listing_floor"`` would silently match zero rows, so this module only ever
sees and compares stored price_type values.

Derived at read time, never persisted
--------------------------------------
Nothing here reads or writes the database, and nothing mutates an
observation. The classification is a pure function of
(source, price_type, value_jpy) - all three already stored and immutable - so
historical rows acquire the correct semantics on the next read with no
migration or backfill, and a rule change is reverted simply by reverting the
config below. See docs/source_semantics_contract_audit_2026-08-19 for the
reasoning behind read-time derivation over collector-time classification.

Scope of ``eligible``
----------------------
``SourceSemantics.eligible`` answers only "is this observation disqualified by
*source semantics*?". It is not the whole Market Index eligibility rule -
staleness (YUYUTEI_SELL_MAX_AGE_DAYS, SNKRDUNK_FLOOR_MAX_AGE_DAYS) and the
sold-sample minimum still live in market_index's resolvers. A caller wiring
this in must combine the two, never substitute one for the other.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bumped whenever any rule in SOURCE_SEMANTICS below changes, so a derived
# Market Index can later be traced back to the ruleset that produced it.
# Deliberately separate from market_index.INDEX_VERSION: the combination
# algorithm and the per-source rules change on different cadences. Not exposed
# through any API schema yet.
SOURCE_SEMANTICS_VERSION = 1

# Stored source names, as they appear in sources.name.
SNKRDUNK = "snkrdunk"

# Stored price_type values, as they appear in price_observations.price_type.
# Never the API-facing reference_type - see the module docstring.
STORED_FLOOR = "floor"

# The one semantic state this version can produce: the observed number is the
# platform's minimum permitted listing price, not an unconstrained market
# price, so it says nothing about what the card is actually worth.
PLATFORM_FLOOR = "platform_floor"


@dataclass(frozen=True)
class SourceSemantics:
    """What a stored observation's number actually means. Frozen so a shared
    default instance can be handed out safely."""

    constraint: str | None = None
    eligible: bool = True
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class _PriceTypeRule:
    """Semantics configured for one (source, stored price_type) pair.

    ``platform_minimum_jpy`` is compared with ``<=``, not ``==``: the minimum
    is the platform's own listing floor, so a value at or below it is equally
    constrained, and the rule keeps working if the platform ever reports a
    value just under its stated minimum.
    """

    platform_minimum_jpy: int | None = None
    at_or_below_minimum: str | None = None


# The single authoritative location for source-specific rules. Every literal
# threshold in the system belongs here and nowhere else - no pricing code
# should ever compare a source name against a magic number directly.
#
# SNKRDUNK's verified platform minimum is 1000 JPY (Task 1C-1: 45 of 109 stored
# floor observations sit at exactly 1000, which is also the observed minimum
# across the whole table). Only the stored "floor" price_type is configured;
# any other SNKRDUNK price_type - including a future "sold" one, which the
# collector does not currently write - falls through to the safe default.
SOURCE_SEMANTICS: dict[str, dict[str, _PriceTypeRule]] = {
    SNKRDUNK: {
        STORED_FLOOR: _PriceTypeRule(
            platform_minimum_jpy=1000,
            at_or_below_minimum=PLATFORM_FLOOR,
        ),
    },
}

# Handed out for every unconfigured source, price_type, or missing value.
# A frozen dataclass, so one shared instance is safe to return repeatedly.
_UNCONSTRAINED = SourceSemantics()


def classify_observation(
    source: str, price_type: str, value_jpy: int | None
) -> SourceSemantics:
    """Semantics for one stored observation, from its source name, its stored
    price_type, and its observed JPY value.

    Fail-open by design: an unknown or unconfigured source, an unconfigured
    price_type, or a missing value all return the unconstrained default rather
    than raising. A new source must never break pricing merely by not being
    listed in SOURCE_SEMANTICS yet - the worst case is that it is treated
    exactly as it is treated today.

    ``value_jpy=None`` is unconstrained on purpose: a missing value is already
    handled by Market Index's own ``value_jpy is not None`` gate
    (app.services.market_index._compute_index_fields), and duplicating that
    concern here would give two places the power to reject an observation for
    the same reason.
    """
    rule = SOURCE_SEMANTICS.get(source, {}).get(price_type)
    if rule is None or value_jpy is None:
        return _UNCONSTRAINED

    minimum = rule.platform_minimum_jpy
    if minimum is not None and value_jpy <= minimum:
        constraint = rule.at_or_below_minimum
        if constraint is not None:
            return SourceSemantics(
                constraint=constraint,
                eligible=False,
                ineligible_reason=constraint,
            )

    return _UNCONSTRAINED
