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
observation. The classification is a pure function of its arguments - every
one of which is a value already stored on the observation and immutable once
written - so historical rows acquire the correct semantics on the next read
with no migration or backfill, and a rule change is reverted simply by
reverting the config below. See
docs/source_semantics_contract_audit_2026-08-19 for the reasoning behind
read-time derivation over collector-time classification.

That purity is why ``promotion_state`` is an ARGUMENT here rather than
something this module works out for itself. Whether a source displayed its
own sale state is a fact about the page at capture time, not a function of
(source, price_type, value_jpy): the sale prices measured on 2026-09-02 - 80,
120, 180, 220 - are all values ordinary listings also carry, so no rule over
the number could recover it, and any attempt would be inventing a threshold
the source does not have. The collector records it
(price_observations.promotion_state), and this module classifies what it
recorded. Passing a fourth *stored, immutable* column keeps the function
exactly as pure as it was.

Scope of ``eligible``
----------------------
``SourceSemantics.eligible`` answers only "is this observation disqualified by
*source semantics*?". It is not the whole Market Index eligibility rule -
staleness (YUYUTEI_SELL_MAX_AGE_DAYS, SNKRDUNK_FLOOR_MAX_AGE_DAYS) and the
sold-sample minimum still live in market_index's resolvers. A caller wiring
this in must combine the two, never substitute one for the other.

Not every constraint disqualifies
----------------------------------
``constraint`` and ``eligible`` are separate fields because they answer
separate questions, and ``sale_price`` is the case that proves it. A
promotional price is a fully valid market observation - it is the price the
card can actually be bought at today, and on the evidence it is not even
transient (the four sale-priced prints on staging held one unchanged price,
beside one unchanged struck price, on every captured page across 25
consecutive days). So it is *described*, never *excluded*: ``eligible`` stays
True, ``ineligible_reason`` stays None, and the Market Index number it feeds
is byte-identical to what it would have been without the label.

The struck former price is not represented here at all, under any name. It is
not an offer, so it is not stored as one and cannot be classified as one.

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
# Version 2 (was 1): a new classification exists. A Yuyu-Tei retail sell
# observation whose stored promotion_state is "sale" is now described as
# ``sale_price`` instead of unconstrained. No observation's ELIGIBILITY moved
# and no index value changes because of it - but the ruleset that interprets
# an observation did, which is exactly the event this counter exists to
# record. 310 snapshots are already stored under version 1, written when the
# distinction was not knowable; the bump is what keeps "Atlas could not tell"
# and "Atlas could tell, and it was ordinary" from collapsing into the same
# unlabelled row forever.
#
# INDEX_VERSION is deliberately NOT bumped alongside it. The combination
# algorithm in market_index did not move, and a spurious bump there would make
# market_index_change refuse every cross-version comparison - blanking the
# 7-day change across the whole catalogue for a week to report a methodology
# change that did not happen.
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
SOURCE_SEMANTICS_VERSION = 2

# Stored source names, as they appear in sources.name.
SNKRDUNK = "snkrdunk"
YUYUTEI = "yuyutei"

# Stored price_type values, as they appear in price_observations.price_type.
# Never the API-facing reference_type - see the module docstring. Yuyu-Tei
# stores "sell"; "retail_sell" exists only as the API-facing reference_type
# set in market_index._resolve_yuyutei_sell, and a rule keyed on it would
# match zero rows.
STORED_FLOOR = "floor"
STORED_SELL = "sell"

# Stored promotion_state values, as they appear in
# price_observations.promotion_state. NULL is a third state - "not
# determined" - and is deliberately absent from this pair: it is the
# default every legacy row carries and must never be read as "no promotion".
PROMOTION_SALE = "sale"
PROMOTION_NONE = "none"

# The observed number IS the platform's minimum permitted listing price, not an
# unconstrained market price, so it says nothing about what the card is
# actually worth. Applies at the minimum exactly - see below for under it.
PLATFORM_FLOOR = "platform_floor"

# The observed number is below a minimum the platform documents as its floor,
# so the observation contradicts its own source contract and cannot be
# described as that floor. See "Why below-minimum fails closed" above.
BELOW_PLATFORM_MINIMUM = "below_platform_minimum"

# The observed number is what the source is asking for the card RIGHT NOW,
# while the source itself displays that price as a discount off its own
# regular price. It is a real, current, executable offer - the only price the
# card can actually be bought at - so unlike the two constraints above this
# one is purely descriptive and never disqualifies. See "Not every constraint
# disqualifies" in the module docstring.
#
# It describes the CURRENT price. The struck former price is a different
# quantity, is never stored, and has no vocabulary here.
SALE_PRICE = "sale_price"


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

    ``promotion_aware`` is the same idea for a different kind of fact: it
    declares that this (source, price_type) pair is one whose collector
    actually records promotion_state, so a stored "sale" there is a
    measurement rather than a stray string. A pair that leaves it False
    ignores promotion_state entirely - which is what keeps a column shared by
    every source from silently changing how an unrelated source's
    observations are described.
    """

    platform_minimum_jpy: int | None = None
    promotion_aware: bool = False


# The single authoritative location for source-specific rules. Every literal
# threshold in the system belongs here and nowhere else - no pricing code
# should ever compare a source name against a magic number directly.
#
# SNKRDUNK's verified platform minimum is 1000 JPY (Task 1C-1: 45 of 109 stored
# floor observations sit at exactly 1000, which is also the observed minimum
# across the whole table). Only the stored "floor" price_type is configured;
# any other SNKRDUNK price_type - including a future "sold" one, which the
# collector does not currently write - falls through to the safe default.
#
# Yuyu-Tei's stored "sell" price_type carries no platform minimum - the source
# publishes none, and inventing one would be exactly the magic number this
# table exists to prevent. Its entry exists solely to declare that the Yuyu
# collector records promotion_state on the observations it writes. Yuyu-Tei's
# "buy" price_type is deliberately absent: it is a dealer quote the resolver
# already marks auxiliary_only, and no promotion is displayed against it.
SOURCE_SEMANTICS: dict[str, dict[str, _PriceTypeRule]] = {
    SNKRDUNK: {
        STORED_FLOOR: _PriceTypeRule(platform_minimum_jpy=1000),
    },
    YUYUTEI: {
        STORED_SELL: _PriceTypeRule(promotion_aware=True),
    },
}

# The four possible results. Frozen dataclasses, so one shared instance of
# each is safe to return repeatedly - a caller can never mutate the verdict
# another caller then observes.
#
# _UNCONSTRAINED is handed out for every unconfigured source, price_type, or
# missing value. The two DISQUALIFYING results carry their constraint as the
# ineligible_reason too: the reason a disqualified observation is unusable is
# exactly the constraint, and giving them separate vocabularies would invite
# them to disagree.
#
# _SALE_PRICE is the one constrained-but-usable verdict, and its
# ineligible_reason is None precisely because there is no reason - it is not
# ineligible. Anything reading `constraint` as a synonym for "excluded" is
# reading it wrong; `eligible` is the field that answers that.
_UNCONSTRAINED = SourceSemantics()
_AT_PLATFORM_FLOOR = SourceSemantics(
    constraint=PLATFORM_FLOOR, eligible=False, ineligible_reason=PLATFORM_FLOOR
)
_BELOW_PLATFORM_MINIMUM = SourceSemantics(
    constraint=BELOW_PLATFORM_MINIMUM,
    eligible=False,
    ineligible_reason=BELOW_PLATFORM_MINIMUM,
)
_SALE_PRICE = SourceSemantics(
    constraint=SALE_PRICE, eligible=True, ineligible_reason=None
)


def classify_observation(
    source: str,
    price_type: str,
    value_jpy: int | None,
    promotion_state: str | None = None,
) -> SourceSemantics:
    """Semantics for one stored observation, from its source name, its stored
    price_type, its observed JPY value, and what the source said about its own
    price when the observation was captured.

    ``promotion_state`` is keyword-optional and defaults to None - the stored
    value on every observation written before the column existed - so every
    existing call site keeps its exact previous behaviour without being
    touched. None never means "no promotion"; it means the state was not
    determined, and an undetermined state is classified exactly as an ordinary
    one, because claiming a promotion Atlas did not observe would be worse
    than saying nothing.

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

    A disqualifying verdict wins over the descriptive one. If a source ever
    had both a platform minimum and promotions, an observation at that minimum
    is reported as ``platform_floor`` rather than ``sale_price``: "this number
    is not a market price" is a stronger statement than "this number is
    discounted", and letting a descriptive label mask an exclusion would put
    an inadmissible value back into the index. No source is configured both
    ways today; the ordering is stated so it cannot be decided by accident
    later.

    Nothing here branches on the magnitude of a promotional price. There is no
    discount threshold, and there is no rule that a "sale" price must be lower
    than anything - the source's own displayed state is the entire input.
    """
    rule = SOURCE_SEMANTICS.get(source, {}).get(price_type)
    if rule is None:
        return _UNCONSTRAINED

    minimum = rule.platform_minimum_jpy
    if minimum is not None and value_jpy is not None:
        if value_jpy == minimum:
            return _AT_PLATFORM_FLOOR
        if value_jpy < minimum:
            return _BELOW_PLATFORM_MINIMUM

    if rule.promotion_aware and promotion_state == PROMOTION_SALE:
        return _SALE_PRICE

    return _UNCONSTRAINED
