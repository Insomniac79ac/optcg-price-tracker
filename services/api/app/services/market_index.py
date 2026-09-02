"""Market Index v1 - a single collector-facing JPY value per card, derived
on read from the latest eligible price_observations across sources. See
docs/market_index.md for the full product rules this module implements.

Source-resolver design
-----------------------
Each source contributes zero or more normalized `_SourceValue` objects (one
per reference_type: "retail_sell", "dealer_buy", "transaction_median",
"listing_floor"). A resolver only ever looks at that source's own
observations and returns normalized values with an `eligible` flag - it
never decides how those values combine into an index. `_combine` is the one
place that turns eligible source_values into index_value_jpy/coverage_status,
so adding a third/fourth source (Cardrush, Mercado) later only means adding
a new resolver function and one line in `_resolve_all_for_card` - the
combination step and the API/schema shape are unchanged.

Compute-on-read, not persisted
--------------------------------
Nothing here writes to the database. Every value is recomputed from
price_observations on each call (see docs/market_index.md "Why
compute-on-read").

The rest of this paragraph used to read "there is no market_index_snapshots
table". That has not been true since the snapshot job shipped: the table
exists and holds rows, written by app.snapshot_market_index from THIS module's
output. Compute-on-read still describes the read path - this module is still
the only place an index value is derived, and it still writes nothing - but
the persisted archive is now real, which is exactly why INDEX_VERSION below
has to move whenever the combination rule does.

Batch-safe by construction
----------------------------
`get_market_index_for_cards` takes many card_ids and issues a small, fixed
number of queries total (latest yuyutei sell/buy + latest snkrdunk floor via
app.services.latest_prices's window-function helper, plus one bounded query
for recent snkrdunk sold observations) - never one query per card. Both the
single-card endpoint and the batch catalogue endpoint call this same
function so their numbers can never drift apart.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceObservation
from app.schemas import MarketIndexOut, MarketIndexSourceValueOut, SourcePriceRangeOut
from app.services.latest_prices import get_latest_price_map
from app.services.source_semantics import SOURCE_SEMANTICS_VERSION, classify_observation

# Version 2 (was 1): the COMBINATION step changed. An admissible source value
# whose `fallback_used` is true no longer joins the numerical aggregate while a
# non-fallback value is present - see _compute_index_fields. Nothing about how
# an individual observation is classified moved, so SOURCE_SEMANTICS_VERSION is
# deliberately NOT bumped alongside it; the two version fields exist precisely
# so a change like this one can say which layer moved.
#
# THE BUMP IS LOAD-BEARING, not bookkeeping. market_index_snapshots holds rows
# written under version 1 whose index_value_jpy is the old midpoint of a retail
# price and a listing floor. app.services.market_index_change refuses to
# compare across unequal index_version, so bumping here is what stops a v1
# baseline being read as movement in a v2 number - the 7d percentage goes null
# for a week rather than reporting a methodology change as a price change.
INDEX_VERSION = 2
CALCULATION_METHOD = "median_of_sources"

YUYUTEI = "yuyutei"
SNKRDUNK = "snkrdunk"

# Source eligibility windows (Market Index v1 product rules - see
# docs/market_index.md "Source eligibility"). Deliberately separate from the
# frontend's 48h stale *display* badge (see CardImageFrame/PriceCell) - that
# badge is cosmetic and never changes what counts toward the index.
YUYUTEI_SELL_MAX_AGE_DAYS = 7
SNKRDUNK_SOLD_WINDOW_DAYS = 30
SNKRDUNK_SOLD_MIN_SAMPLE = 3
SNKRDUNK_FLOOR_MAX_AGE_DAYS = 7


def _round_half_up_jpy(value: Decimal) -> int:
    """The one rounding policy for every JPY value this module produces
    (medians and the index midpoint) - round-half-up to the nearest whole
    yen. Chosen over Python's default round-half-to-even because it's the
    deterministic, unsurprising convention collectors expect from a shop
    price, and it's specified with `decimal.Decimal` (never float) so a
    value like the midpoint of 1200 and 1425 (1312.5) rounds to exactly
    1313 on every platform, not 1312 or 1313 depending on float
    representation. See docs/market_index.md "Rounding policy" - this is
    the single source of truth other code should link back to rather than
    re-deriving its own rounding."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _median_jpy(values: list[int]) -> int:
    """Median of integer JPY values, rounded via _round_half_up_jpy when the
    count is even (average of the two middle values can land on a .5)."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return _round_half_up_jpy(Decimal(ordered[mid - 1] + ordered[mid]) / Decimal(2))


@dataclass(frozen=True)
class _SourceValue:
    source: str
    reference_type: str
    evidence_type: str
    value_jpy: int | None
    observed_at: datetime | None
    sample_size: int | None
    stale: bool
    eligible: bool
    fallback_used: bool
    ineligible_reason: str | None = None
    # Source semantics for the underlying observation (see
    # app.services.source_semantics), carried separately from `eligible` on
    # purpose: a constrained value stays visible with its raw number even
    # when some other rule is what currently disqualifies it.
    constraint: str | None = None

    def to_schema(self, *, contributes_to_index: bool) -> MarketIndexSourceValueOut:
        """The API shape for this value, plus the role the COMBINATION step
        assigned it.

        The role is a parameter rather than a field on this frozen dataclass on
        purpose: a resolver looks at one source in isolation and cannot know
        whether a stronger non-fallback source exists elsewhere in the same
        print's set. Only _compute_index_fields can answer that, so only
        _compute_index_fields supplies it - and it is required, not defaulted,
        so a future caller cannot emit a source value whose role was never
        decided.
        """
        return MarketIndexSourceValueOut(
            source=self.source,
            reference_type=self.reference_type,
            evidence_type=self.evidence_type,
            value_jpy=self.value_jpy,
            observed_at=self.observed_at,
            sample_size=self.sample_size,
            stale=self.stale,
            eligible=self.eligible,
            fallback_used=self.fallback_used,
            ineligible_reason=self.ineligible_reason,
            constraint=self.constraint,
            contributes_to_index=contributes_to_index,
        )


def _naive_utc(dt: datetime) -> datetime:
    """price_observations.observed_at is stored via SQLAlchemy DateTime
    columns that come back tz-naive from SQLite (tests) but tz-aware from
    Postgres (staging/prod) - normalize to a naive UTC instant for age math
    either way, matching the pattern already used in app.services.market."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _resolve_yuyutei_sell(
    observation: PriceObservation | None, now: datetime
) -> _SourceValue:
    """Eligibility rule (product decision - see docs/market_index.md
    "Source eligibility"): latest verified Yuyu-Tei sell observation <= 7
    days old. Stock state has no effect - a displayed sell price is useful
    market evidence whether or not Yuyu-Tei currently reports the item in
    stock, so an out-of-stock observation is exactly as eligible as an
    in-stock one of the same age.

    A PROMOTIONAL PRICE IS STILL A RETAIL SELL PRICE, and this function's
    arithmetic says so: when the stored promotion_state is "sale" the only
    thing that changes is `constraint`. The value, the staleness rule, the
    eligibility verdict and therefore the index number, source_count,
    coverage, confidence and source_price_range are all identical to what they
    would have been without the label. The reason is simple - a discounted
    asking price is the price the card can actually be bought at, so treating
    it as anything less than ordinary evidence would make Atlas publish
    nothing for a card whose current price it knows exactly.

    `eligible` is combined with the semantic verdict the same way
    _resolve_snkrdunk does it, rather than ignoring it: today Yuyu-Tei's only
    two possible verdicts are both eligible, so the `and` cannot change any
    current outcome, but writing it this way means a future Yuyu-Tei rule that
    genuinely disqualifies an observation is honoured automatically instead of
    being silently dropped here."""
    if observation is None:
        return _SourceValue(
            source=YUYUTEI,
            reference_type="retail_sell",
            evidence_type="listing",
            value_jpy=None,
            observed_at=None,
            sample_size=None,
            stale=False,
            eligible=False,
            fallback_used=False,
            ineligible_reason="no_observation",
        )

    age = now - _naive_utc(observation.observed_at)
    stale = age > timedelta(days=YUYUTEI_SELL_MAX_AGE_DAYS)

    # What this number *means*, asked of the one module that owns
    # source-specific rules. The stored price_type and the stored
    # promotion_state are both passed through as-is - never the API-facing
    # reference_type below, and never anything derived from the value itself.
    # An observation predating the promotion_state column carries None there
    # and classifies exactly as it always did.
    semantics = classify_observation(
        YUYUTEI,
        observation.price_type,
        observation.price_jpy,
        promotion_state=observation.promotion_state,
    )

    return _SourceValue(
        source=YUYUTEI,
        reference_type="retail_sell",
        evidence_type="listing",
        value_jpy=observation.price_jpy,
        observed_at=observation.observed_at,
        sample_size=None,
        stale=stale,
        eligible=not stale and semantics.eligible,
        fallback_used=False,
        # Staleness keeps the reason string when both apply, matching
        # _resolve_snkrdunk. `sale_price` never supplies one at all - it is
        # not a reason for exclusion - so a fresh sale observation reports
        # ineligible_reason=None exactly as an ordinary one does.
        ineligible_reason="stale" if stale else semantics.ineligible_reason,
        constraint=semantics.constraint,
    )


def _resolve_yuyutei_buy(observation: PriceObservation | None) -> _SourceValue | None:
    """Auxiliary dealer-buy/liquidity indication only - never eligible for
    the index itself (Market Index v1 product rule). Returns None (not
    included in auxiliary_values at all) when there's no observation, same
    "absent, not a fabricated zero" convention as every other resolver."""
    if observation is None:
        return None
    return _SourceValue(
        source=YUYUTEI,
        reference_type="dealer_buy",
        evidence_type="listing",
        value_jpy=observation.price_jpy,
        observed_at=observation.observed_at,
        sample_size=None,
        stale=False,
        eligible=False,
        fallback_used=False,
        ineligible_reason="auxiliary_only",
    )


def _resolve_snkrdunk(
    sold_observations: list[PriceObservation],
    floor_observation: PriceObservation | None,
    now: datetime,
) -> _SourceValue:
    # Genuine completed sales - never subject to the platform-floor rule
    # applied to the fallback listing below. A sold price at any value is a
    # real transaction, not a platform minimum, and classify_observation
    # already treats every non-"floor" price_type as unconstrained.
    if len(sold_observations) >= SNKRDUNK_SOLD_MIN_SAMPLE:
        median = _median_jpy([obs.price_jpy for obs in sold_observations])
        freshest = max(obs.observed_at for obs in sold_observations)
        return _SourceValue(
            source=SNKRDUNK,
            reference_type="transaction_median",
            evidence_type="transaction",
            value_jpy=median,
            observed_at=freshest,
            sample_size=len(sold_observations),
            stale=False,
            eligible=True,
            fallback_used=False,
        )

    # Fewer than the minimum sold sample - fall back to the latest floor
    # listing, but only if it's fresh; never describe it as a completed sale.
    if floor_observation is not None:
        age = now - _naive_utc(floor_observation.observed_at)
        stale = age > timedelta(days=SNKRDUNK_FLOOR_MAX_AGE_DAYS)
        # What this number *means*, asked of the one module that owns
        # source-specific rules - no threshold or source comparison is
        # restated here. The stored price_type is passed through as-is
        # (always "floor" for this query), never the API-facing
        # reference_type below; see source_semantics' module docstring.
        semantics = classify_observation(
            SNKRDUNK, floor_observation.price_type, floor_observation.price_jpy
        )
        # Both gates must pass: semantics never relaxes the freshness rule,
        # and freshness never overrides a semantic disqualification. For the
        # reason string the pre-existing rule wins, so a stale observation
        # keeps reporting "stale"; the semantic verdict stays visible either
        # way through `constraint`.
        return _SourceValue(
            source=SNKRDUNK,
            reference_type="listing_floor",
            evidence_type="listing",
            value_jpy=floor_observation.price_jpy,
            observed_at=floor_observation.observed_at,
            sample_size=None,
            stale=stale,
            eligible=not stale and semantics.eligible,
            fallback_used=True,
            ineligible_reason="stale" if stale else semantics.ineligible_reason,
            constraint=semantics.constraint,
        )

    return _SourceValue(
        source=SNKRDUNK,
        reference_type="listing_floor",
        evidence_type="listing",
        value_jpy=None,
        observed_at=None,
        sample_size=None,
        stale=False,
        eligible=False,
        fallback_used=False,
        ineligible_reason="insufficient_sold_and_no_floor",
    )


def _compute_index_fields(
    source_values: list[_SourceValue],
    auxiliary_values: list[_SourceValue],
    now: datetime,
) -> dict:
    """The combination step, independent of what entity (legacy card or
    card_print) the result will be attached to - see this module's
    docstring "Source-resolver design". Returns a plain dict of every
    MarketIndexOut field except card_id, so both this module's _combine
    (card-keyed) and app.services.print_market_index (print-keyed) can build
    their own schema instance from the exact same computation without
    duplicating it."""
    # ADMISSIBLE - is this value usable evidence at all? Unchanged from v1, and
    # `eligible` still means exactly what it always meant. Constrained, stale
    # and absent values are out, and they stay out of everything below.
    admissible = [sv for sv in source_values if sv.eligible and sv.value_jpy is not None]

    # CONTRIBUTORS - which admissible values go into the number? This is the
    # whole of the v2 change, and it is a rule about EVIDENCE STRENGTH, not
    # about source names: nothing here mentions yuyutei or snkrdunk, and a
    # future source's fallback is handled by the same two lines.
    #
    # `fallback_used` is the resolver's own admission that a value is standing
    # in for the evidence it could not get - today, a SNKRDUNK listing floor
    # substituting for a sold median it lacked the sample size to compute. A
    # marketplace's minimum permitted ask and a dealer's displayed retail price
    # are different quantities, so averaging them produced a number no source
    # ever reported, and then labelled it `full`/`high`. So:
    #
    #   - a fallback stands ASIDE whenever any non-fallback value is admissible;
    #   - a fallback stands ALONE quite happily when it is all there is, which
    #     is why it remains eligible rather than being disqualified outright -
    #     one imperfect number beats no number, as long as it is not dressed up
    #     as corroboration.
    #
    # A SNKRDUNK transaction_median carries fallback_used=False, so the day the
    # sold sample reaches its minimum it aggregates with Yuyu-Tei exactly as v1
    # always intended. That case is the reason the rule keys on the flag rather
    # than on reference_type.
    non_fallback = [sv for sv in admissible if not sv.fallback_used]
    contributors = non_fallback if non_fallback else admissible
    contributor_ids = {id(sv) for sv in contributors}

    # THE RANGE IS DERIVED FROM ADMISSIBLE, BEFORE ROLE FILTERING - deliberately
    # a different set from `contributors` above. A fallback that stood aside is
    # still a real measured number that disagrees with the published index, and
    # this field exists to expose exactly that disagreement; recomputing it from
    # contributors would hide the thing it was built to show. So `source_count =
    # 1` beside a two-endpoint range is valid and intended, not a bug.
    #
    # min/max are order-independent by definition, so resolver ordering cannot
    # affect the result, and equal values still produce a range object (a real,
    # measured zero spread). Below two admissible sources there is no
    # disagreement to report and the field is absent rather than a
    # self-referential "X to X".
    admissible_values: list[int] = [sv.value_jpy for sv in admissible]  # type: ignore[misc]
    source_price_range = (
        SourcePriceRangeOut(
            low_jpy=min(admissible_values), high_jpy=max(admissible_values)
        )
        if len(admissible_values) >= 2
        else None
    )

    # Index, count, coverage and confidence all come from CONTRIBUTORS, so
    # `confidence` finally describes the evidence behind the number rather than
    # counting rows beside it.
    if len(contributors) >= 2:
        index_value = _median_jpy([sv.value_jpy for sv in contributors])  # type: ignore[list-item]
        coverage_status = "full"
        confidence = "high"
    elif len(contributors) == 1:
        index_value = contributors[0].value_jpy
        coverage_status = "limited"
        confidence = "medium"
    else:
        index_value = None
        coverage_status = "none"
        confidence = "low"

    all_observed_ats = [sv.observed_at for sv in source_values if sv.observed_at is not None]
    freshest = max(all_observed_ats) if all_observed_ats else None
    # Still keyed on ADMISSIBLE, matching this field's name and `eligible`'s
    # unchanged meaning: it bounds the freshness of the evidence on display, not
    # of the aggregate alone. Moving it to contributors would silently change
    # what every already-written market_index_snapshots row's
    # stalest_eligible_source_at column means.
    eligible_observed_ats = [sv.observed_at for sv in admissible if sv.observed_at is not None]
    stalest_eligible = min(eligible_observed_ats) if eligible_observed_ats else None
    stale_sources = [sv.source for sv in source_values if sv.stale]

    return {
        "index_version": INDEX_VERSION,
        # Which source-normalisation ruleset interpreted the observations
        # above - re-exported from app.services.source_semantics, never
        # restated, and versioned independently of INDEX_VERSION because the
        # combination algorithm and the per-source rules change on different
        # cadences. Emitted here, on the one path both the card-keyed and
        # print-keyed payloads are built from, so the two can never report
        # different rulesets for the same observation.
        "source_semantics_version": SOURCE_SEMANTICS_VERSION,
        "source_price_range": source_price_range,
        "index_value_jpy": index_value,
        "calculation_method": CALCULATION_METHOD,
        "source_count": len(contributors),
        "coverage_status": coverage_status,
        "confidence": confidence,
        # Identity, not equality: two sources can legitimately report the same
        # value, and `sv in contributors` on a frozen dataclass would then give
        # both the same role. The set of id()s is built above while every
        # object is still referenced by `contributors`, so none can be
        # collected and have its id reused.
        "source_values": [
            sv.to_schema(contributes_to_index=id(sv) in contributor_ids)
            for sv in source_values
        ],
        # Auxiliary values are not index candidates at all (Yuyu-Tei dealer buy
        # is the standing example), so the answer is a flat false - stated
        # explicitly rather than left None, which would mean "unknown".
        "auxiliary_values": [
            sv.to_schema(contributes_to_index=False) for sv in auxiliary_values
        ],
        "freshest_observation_at": freshest,
        "stalest_eligible_source_at": stalest_eligible,
        "stale_sources": stale_sources,
        "calculated_at": now.replace(tzinfo=timezone.utc),
    }


def _combine(
    card_id: int,
    source_values: list[_SourceValue],
    auxiliary_values: list[_SourceValue],
    now: datetime,
) -> MarketIndexOut:
    return MarketIndexOut(
        card_id=card_id,
        **_compute_index_fields(source_values, auxiliary_values, now),
    )


def _fetch_recent_snkrdunk_sold(
    db: Session, card_ids: list[int], now: datetime
) -> dict[int, list[PriceObservation]]:
    """Bounded query for recent SNKRDUNK sold observations across many
    cards at once - the one query this module needs beyond
    get_latest_price_map, since a median needs more than just the single
    latest row per card. Filtered by both card_id and the 30-day window
    server-side so this never pulls a card's full sold history."""
    if not card_ids:
        return {}

    from app.models import Source  # local import avoids a cycle at module load

    snkrdunk_source_id = db.scalar(select(Source.id).where(Source.name == SNKRDUNK))
    if snkrdunk_source_id is None:
        return {}

    cutoff = now - timedelta(days=SNKRDUNK_SOLD_WINDOW_DAYS)
    rows = db.scalars(
        select(PriceObservation)
        .where(
            PriceObservation.card_id.in_(card_ids),
            PriceObservation.source_id == snkrdunk_source_id,
            PriceObservation.price_type == "sold",
            PriceObservation.observed_at >= cutoff,
        )
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
    ).all()

    by_card: dict[int, list[PriceObservation]] = defaultdict(list)
    for row in rows:
        by_card[row.card_id].append(row)
    return by_card


def get_market_index_for_cards(db: Session, card_ids: list[int]) -> dict[int, MarketIndexOut]:
    """The one entry point both GET /cards/{id}/market-index and the
    catalogue batch endpoint call - same code path, so a single card's
    index can never disagree with what the catalogue shows for it. Issues a
    fixed number of queries regardless of len(card_ids): two calls to
    get_latest_price_map (already N+1-safe) plus one bounded sold-
    observations query."""
    if not card_ids:
        return {}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    yuyutei_latest = get_latest_price_map(
        db, card_ids, source_names=(YUYUTEI,), price_types=("sell", "buy")
    )
    snkrdunk_floor_latest = get_latest_price_map(
        db, card_ids, source_names=(SNKRDUNK,), price_types=("floor",)
    )
    snkrdunk_sold_by_card = _fetch_recent_snkrdunk_sold(db, card_ids, now)

    results: dict[int, MarketIndexOut] = {}
    for card_id in card_ids:
        card_yuyutei = yuyutei_latest.get(card_id, {})
        card_snkrdunk_floor = snkrdunk_floor_latest.get(card_id, {})

        sell_value = _resolve_yuyutei_sell(card_yuyutei.get((YUYUTEI, "sell")), now)
        buy_value = _resolve_yuyutei_buy(card_yuyutei.get((YUYUTEI, "buy")))
        snkrdunk_value = _resolve_snkrdunk(
            snkrdunk_sold_by_card.get(card_id, []),
            card_snkrdunk_floor.get((SNKRDUNK, "floor")),
            now,
        )

        auxiliary_values = [buy_value] if buy_value is not None else []
        results[card_id] = _combine(card_id, [sell_value, snkrdunk_value], auxiliary_values, now)

    return results


def get_market_index_for_card(db: Session, card_id: int) -> MarketIndexOut:
    return get_market_index_for_cards(db, [card_id])[card_id]
