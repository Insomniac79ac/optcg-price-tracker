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

Why below-minimum fails closed (Task 1C-2D)
---------------------------------------------
For a source with a known documented platform minimum, an observation *below*
that minimum is inconsistent with the configured source contract: either the
extractor is wrong or the platform changed its rule, and neither is something
derived pricing should absorb silently. Atlas therefore preserves the raw
observation, excludes it from Market Index, and exposes a distinct semantic
reason (``below_platform_minimum``) rather than the ``platform_floor`` reason,
which would misdescribe an impossible value as the documented floor.

Failing closed rather than open is the deliberate asymmetry here. An unknown
source is unconstrained (see ``classify_observation``) because nothing is
claimed about it; a *configured* source contradicting its own configured
contract is a different situation, and admitting that number to the index
would let an extractor bug set a card's price. Nothing in this module alerts
or monitors - it only classifies.
"""

from __future__ import annotations

from dataclasses import dataclass

# Identifies the SOURCE_SEMANTICS ruleset a derived Market Index was computed
# under, so a stored index value can later be traced back to the rules that
# produced it.
#
# Version 1 is still correct today: no Market Index snapshot has ever been
# persisted, so there is no stored value anywhere that a bump would need to
# distinguish itself from.
#
# The binding contract, from the first persisted snapshot onward
# ---------------------------------------------------------------
# market_index_snapshots rows record source_semantics_version and are
# append-only - they are never recomputed, and the classification that
# produced them cannot be reconstructed from the row itself. So once a
# snapshot has been written under a given version, that version is frozen:
# it permanently means "the ruleset as it stood when those rows were made".
#
# Therefore, once any snapshot exists, ANY subsequent change to the
# SOURCE_SEMANTICS rules or thresholds below that could alter how an
# observation is classified or whether it is eligible MUST increment
# SOURCE_SEMANTICS_VERSION in the same change, before that change is
# deployed. That includes adding or removing a source entry, changing a
# platform minimum, changing which price_type maps to which semantics, and
# changing the eligible flag for any existing combination. Editing the rules
# in place without a bump silently makes older snapshot rows claim a ruleset
# that no longer exists, which is the one failure this field is here to
# prevent. Purely editorial changes - comments, reason-string docs, tests -
# do not need a bump.
#
# Deliberately separate from market_index.INDEX_VERSION: the combination
# algorithm and the per-source rules change on different cadences, and a
# snapshot records both independently. Not exposed through any API schema yet.
SOURCE_SEMANTICS_VERSION = 1

# Stored source names, as they appear in sources.name.
SNKRDUNK = "snkrdunk"

# Stored price_type values, as they appear in price_observations.price_type.
# Never the API-facing reference_type - see the module docstring.
STORED_FLOOR = "floor"

# The observed number IS the platform's minimum permitted listing price, not an
# unconstrained market price, so it says nothing about what the card is
# actually worth. Applies at the minimum exactly - see below for under it.
PLATFORM_FLOOR = "platform_floor"

# The observed number is below a minimum the platform documents as its floor,
# so the observation contradicts its own source contract and cannot be
# described as that floor. See "Why below-minimum fails closed" above.
BELOW_PLATFORM_MINIMUM = "below_platform_minimum"


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

    Deliberately declarative: the only thing configured is the documented
    number itself. What each side of it *means* is derived by
    ``classify_observation`` - equal to the minimum is ``platform_floor``,
    below it is ``below_platform_minimum`` - so the config cannot drift into
    describing a below-minimum value as the floor, which an earlier
    ``at_or_below_minimum`` field allowed (Task 1C-2D). A source with no
    documented minimum leaves it None and is unconstrained at every value.
    """

    platform_minimum_jpy: int | None = None


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
        STORED_FLOOR: _PriceTypeRule(platform_minimum_jpy=1000),
    },
}

# The three possible results. Frozen dataclasses, so one shared instance of
# each is safe to return repeatedly - a caller can never mutate the verdict
# another caller then observes.
#
# _UNCONSTRAINED is handed out for every unconfigured source, price_type, or
# missing value. Both constrained results carry their constraint as the
# ineligible_reason too: the reason a constrained observation is unusable is
# exactly the constraint, and giving them separate vocabularies would invite
# them to disagree.
_UNCONSTRAINED = SourceSemantics()
_AT_PLATFORM_FLOOR = SourceSemantics(
    constraint=PLATFORM_FLOOR, eligible=False, ineligible_reason=PLATFORM_FLOOR
)
_BELOW_PLATFORM_MINIMUM = SourceSemantics(
    constraint=BELOW_PLATFORM_MINIMUM,
    eligible=False,
    ineligible_reason=BELOW_PLATFORM_MINIMUM,
)


def classify_observation(
    source: str, price_type: str, value_jpy: int | None
) -> SourceSemantics:
    """Semantics for one stored observation, from its source name, its stored
    price_type, and its observed JPY value.

    Fail-open for anything *unconfigured*: an unknown or unconfigured source,
    an unconfigured price_type, or a missing value all return the
    unconstrained default rather than raising. A new source must never break
    pricing merely by not being listed in SOURCE_SEMANTICS yet - the worst
    case is that it is treated exactly as it is treated today. A configured
    source contradicting its own configured minimum is the opposite case and
    fails closed; see the module docstring for that asymmetry.

    ``value_jpy=None`` is unconstrained on purpose: a missing value is already
    handled by Market Index's own ``value_jpy is not None`` gate
    (app.services.market_index._compute_index_fields), and duplicating that
    concern here would give two places the power to reject an observation for
    the same reason.

    Against a configured platform minimum the verdict is three-way, never a
    single ``<=`` bucket: above it is an ordinary market value, exactly it is
    the documented floor, and below it contradicts the source contract (see
    the module docstring). The raw value is only ever read, never rewritten.
    """
    rule = SOURCE_SEMANTICS.get(source, {}).get(price_type)
    if rule is None or value_jpy is None:
        return _UNCONSTRAINED

    minimum = rule.platform_minimum_jpy
    if minimum is not None:
        if value_jpy == minimum:
            return _AT_PLATFORM_FLOOR
        if value_jpy < minimum:
            return _BELOW_PLATFORM_MINIMUM

    return _UNCONSTRAINED
