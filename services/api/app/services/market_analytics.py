"""CURRENT-STATE market analytics, aggregated over exact prints.

What this module answers is deliberately narrow: "for one price basis, across
one slice of the catalogue, what does Atlas know about prices RIGHT NOW?" It
computes no change, no trend, no movement and no ranking - there is no window
parameter here at all, because a 29-day archive whose 30d change is null on
100% of prints cannot honestly answer a movement question yet (see the
Analytics 0D audit). Adding one later is additive; inventing one now would not
be.

WHAT THIS MODULE REFUSES TO DO
------------------------------
It defines no pricing semantics of its own. Eligibility, the platform floor,
the sale-price constraint, the Market Index combination rule and the primary
instrument of a source are all decided elsewhere - by
app.services.source_semantics, app.services.market_index and
app.services.source_instruments - and this module only COUNTS what they
return. There is no threshold, no ¥1,000 and no source name in any branch
below. That is the same discipline app.api.prints already keeps, and it is
what lets a newly configured source flow through these aggregates with no edit
here.

THE FOUR COVERAGE CONCEPTS, AND WHY THEY ARE FOUR
-------------------------------------------------
Collapsing these is the single easiest way to publish a false number, so they
are named separately and counted separately:

  observed_prints   a source reported SOMETHING for this print - the mapping
                    works, the collector ran, a row exists. Says nothing about
                    whether the number is a price.
  usable_priced     the current value for this basis is ELIGIBLE - source
                    semantics let it stand as a market price. This is the only
                    set that may enter a median, a percentile or a bucket.
  excluded_constrained
                    the current value is INELIGIBLE, and specifically because
                    a source-semantics constraint disqualified it. Narrower
                    than "carries a constraint" on purpose: `platform_floor`
                    and `below_platform_minimum` disqualify, `sale_price` does
                    not - a sale price is a real price a collector can pay. So
                    this set is disjoint from `usable_priced`, and reporting
                    the wider notion would have shown 36 perfectly good
                    Yuyu-Tei prices as impaired coverage.
  unavailable       active prints in scope with no usable value for this basis.

On staging today those four are 43 / 25 / 18 / 4,291 for SNKRDUNK: 43 prints
carry a SNKRDUNK number, 18 of them are the ¥1,000 platform minimum, and only
25 are prices. A single "SNKRDUNK covers 43 prints" would have been wrong by
18, in the direction that flatters the product. Yuyu-Tei is 264 / 264 / 0 /
4,052 - it has 36 sale-priced prints, and none of them is excluded.

`observed_prints` and `excluded_constrained_prints` are both None for the
Market Index basis rather than 0. The index is DERIVED from sources; nobody
observes it and it carries no constraint of its own, so neither count is
merely zero - neither is a fact about it. Zero would be a claim.

WHY OBSERVED IS COUNTED FROM OBSERVATIONS, NOT FROM ineligible_reason
---------------------------------------------------------------------
It would be cheaper to read "no_observation" off the resolved source value and
call everything else observed. That is wrong, and staging proves it: Yuyu-Tei
reports `no_observation` for a print it has never seen, while SNKRDUNK reports
`insufficient_sold_and_no_floor` for the same situation - because its resolver
weighs two instruments before concluding. Trusting either string would have
counted all 4,316 prints as SNKRDUNK-observed. The reasons are resolver
narration, not a census, so the census is taken from price_observations.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import CanonicalCard, CardPrint, PriceObservation, Source
from app.services.print_catalogue import effective_rarity_sql
from app.services.print_market_index import INDEX_EVIDENCE_PRICE_TYPES
from app.services.print_series import KIND_MARKET_INDEX, KIND_SOURCE
from app.services.rarity_facets import filter_tokens
from app.services.source_instruments import describe_instrument, primary_price_types

# Percentiles need enough constituents to describe a distribution rather than
# to restate two of its members. Below this a decile is an artefact of the
# sample size, so it is returned as null with a reason - never as a number the
# caller cannot tell apart from a measured one, and never as 0.
#
# The median is deliberately NOT gated the same way: with n>=1 it is a real,
# defensible statement ("the one priced print costs X"), whereas a 10th
# percentile over four points is arithmetic on noise.
MIN_PERCENTILE_CONSTITUENTS = 5

NO_USABLE_PRICES = "no_usable_prices"
INSUFFICIENT_CONSTITUENTS = "insufficient_constituents"

# Fixed, collector-readable JPY bands, returned to the client rather than
# derived from the data.
#
# THE BOUNDARIES ARE CONSTANT ON PURPOSE. Bins computed from the population -
# equal-width, quantile, Freedman-Diaconis - would let ONE ¥66,000 SP card
# redefine every bucket for the 264 commons beneath it, and would silently
# change the x-axis of the whole chart the day a more expensive card is
# priced. A collector comparing two sets, or the same set next week, needs the
# bands to mean the same thing both times. They are also human numbers a
# collector already thinks in, not 0-8250-16500-24750.
#
# The top band is open-ended (`upper_jpy=None`) so no value can ever fall
# outside the distribution and quietly vanish from a total.
PRICE_BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (0, 99, "Under ¥100"),
    (100, 299, "¥100–299"),
    (300, 999, "¥300–999"),
    (1000, 2999, "¥1,000–2,999"),
    (3000, 9999, "¥3,000–9,999"),
    (10000, 29999, "¥10,000–29,999"),
    (30000, 99999, "¥30,000–99,999"),
    (100000, None, "¥100,000+"),
)

MARKET_INDEX_BASIS = KIND_MARKET_INDEX
SOURCE_BASIS_PREFIX = f"{KIND_SOURCE}:"


class BasisError(ValueError):
    """A price_basis string the grammar does not accept."""


@dataclass(frozen=True)
class BasisRequest:
    """One parsed `price_basis`, in the SAME grammar the print series endpoint
    already publishes (`market_index` | `source:<name>` - see
    app.services.print_series.parse_series_key).

    Reusing that grammar rather than inventing an analytics-only one is the
    whole point: a collector who selected SNKRDUNK on a print page and then
    opens analytics is selecting the same thing, spelled the same way, and a
    saved URL means one thing across the product. No source name is validated
    here - an unconfigured one resolves to an explicitly unavailable answer
    later, exactly as a series key does.
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


def scoped_print_ids(
    db: Session, *, set_code: str | None = None, rarity: str | None = None
) -> list[int]:
    """The active prints one request is about, as ids, in one query.

    Filters are applied with the SAME expressions the public catalogue uses -
    `effective_rarity_sql()` and `filter_tokens` - so a rarity that selects a
    print at /cards selects the same print here. A second rarity rule would be
    a second answer to "what rarity is this print", which is precisely the
    thing print_catalogue's docstring exists to prevent.
    """
    stmt = (
        select(CardPrint.id)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(CardPrint.is_active.is_(True))
    )
    if set_code:
        stmt = stmt.where(CardPrint.release_product_code == set_code)
    if rarity:
        stmt = stmt.where(effective_rarity_sql().in_(filter_tokens(rarity)))
    return list(db.scalars(stmt).all())



def prints_with_observations(db: Session, print_ids: list[int]) -> list[int]:
    """The subset that any source has ever reported a price for, in one query.

    WHY THIS NARROWING IS SAFE, not a shortcut. A Market Index value and a
    source value are both computed ENTIRELY from observations - a print with
    none resolves to index_value_jpy=None and to source values with no number
    and eligible=False. So an unobserved print can only ever contribute to
    `unavailable_prints`, which is a count of the scope, not of the resolve.
    Excluding it changes no published number.

    It changes the cost a great deal. On staging 4,316 prints are active and
    290 have ever been observed, so resolving the whole catalogue built 4,026
    guaranteed-empty index objects per request - about 1.2s of pure Python
    with nothing at the end of it. This is the difference between a page that
    loads and one that does not, and it needs no materialised table.
    """
    if not print_ids:
        return []
    return list(
        db.scalars(
            select(distinct(PriceObservation.card_print_id)).where(
                PriceObservation.card_print_id.in_(print_ids)
            )
        ).all()
    )


def observed_print_counts(db: Session, print_ids: list[int]) -> dict[str, int]:
    """source name -> how many of these prints it has reported a PRIMARY
    instrument observation for, in one grouped query.

    Counts distinct prints, not rows: a source that captured the same print on
    25 consecutive days has observed one print, not twenty-five.

    Auxiliary instruments are excluded via INDEX_EVIDENCE_PRICE_TYPES, so
    Yuyu-Tei's dealer buy quote cannot make a print look retail-covered. The
    price_type set is read from that registry rather than listed here - a
    source whose instruments change is counted differently with no edit in
    this module, and no price_type literal appears in analytics code.
    """
    if not print_ids:
        return {}
    evidence_pairs = [
        (source, price_type)
        for source, price_types in INDEX_EVIDENCE_PRICE_TYPES.items()
        for price_type in price_types
    ]
    if not evidence_pairs:
        return {}

    rows = db.execute(
        select(Source.name, func.count(distinct(PriceObservation.card_print_id)))
        .join(Source, Source.id == PriceObservation.source_id)
        .where(
            PriceObservation.card_print_id.in_(print_ids),
            # Tuple-free equivalent of "(source, price_type) IN (...)", kept as
            # an OR of equality pairs so it runs identically on SQLite and
            # Postgres. The pairs come from the registry above.
            _evidence_predicate(evidence_pairs),
        )
        .group_by(Source.name)
    ).all()
    return {name: count for name, count in rows}


def _evidence_predicate(evidence_pairs: list[tuple[str, str]]):
    from sqlalchemy import and_, or_

    return or_(
        *[
            and_(Source.name == source, PriceObservation.price_type == price_type)
            for source, price_type in evidence_pairs
        ]
    )


def percentile(sorted_values: list[int], fraction: float) -> int | None:
    """Linear interpolation between closest ranks, on the ALREADY-SORTED
    usable values.

    Stated explicitly because "the 10th percentile" is not one number: this is
    the R type-7 / numpy default `linear` method - rank = (n-1) * fraction,
    then interpolate between the two neighbouring order statistics. Chosen
    because it is the most widely-implemented definition, is exact at the
    median for odd n, and needs no tie-breaking rule.

    The result is rounded to whole yen, because every price in this product is
    an integer number of yen and a percentile of yen prices reported to four
    decimal places would imply a precision the underlying observations do not
    have.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return round(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * weight)


def bucket_distribution(sorted_values: list[int]) -> list[dict]:
    """Every usable value in exactly one fixed band.

    Bands are returned even when empty, so the shape of the chart is the same
    for every basis and every filter and a reader can see that ¥30,000+ is
    empty rather than being unable to tell it from absent. The counts sum to
    len(sorted_values) by construction - the top band is open-ended - which is
    asserted in the tests rather than trusted.
    """
    buckets = []
    for lower, upper, label in PRICE_BUCKETS:
        if upper is None:
            count = sum(1 for value in sorted_values if value >= lower)
        else:
            count = sum(1 for value in sorted_values if lower <= value <= upper)
        buckets.append({"lower_jpy": lower, "upper_jpy": upper, "label": label, "count": count})
    return buckets


def describe_source_basis(source_name: str) -> tuple[str | None, str | None]:
    """The public instrument vocabulary for a source's PRIMARY basis.

    Asks source_instruments for the source's primary price_types and describes
    the first one. There is no source name and no price_type literal here: a
    source with no configured primary instrument (an unknown one, or one whose
    every instrument is auxiliary) truthfully yields (None, None) rather than a
    guess, which is what keeps Yuyu-Tei's dealer buy from ever becoming a
    selectable basis - `primary_price_types` simply does not return it.
    """
    primaries = primary_price_types(source_name)
    if not primaries:
        return None, None
    instrument = describe_instrument(source_name, primaries[0])
    return instrument.reference_type, instrument.evidence_type


# Reused verbatim from app.services.print_series so a source that is
# unavailable on a print page is unavailable here for the same stated reason,
# in the same word. A second vocabulary would let the two surfaces disagree
# about the same source on the same day.
UNAVAILABLE_SOURCE_NOT_CONFIGURED = "source_not_configured"
UNAVAILABLE_NO_USABLE_PRICES = "no_usable_prices_in_scope"


def _basis_values(
    basis: BasisRequest, indexes: dict[int, object]
) -> tuple[list[int], int | None, dict[str, int]]:
    """Pull one basis's CURRENT values out of the already-computed indexes.

    Returns (usable values, excluded-constrained count or None, index
    composition).

    Everything here reads the resolved PrintMarketIndexOut - the same object
    /prints/{id}/market-index serves - so an aggregate can never disagree with
    the print page a collector clicks through to. The source branch iterates
    `source_values` and matches on the requested name: whatever sources the
    resolvers produced are the sources this understands, which is why adding
    one needs no edit here.
    """
    usable: list[int] = []
    excluded_constrained = 0
    single = multi = 0

    for index in indexes.values():
        if basis.kind == KIND_MARKET_INDEX:
            value = index.index_value_jpy
            if value is not None:
                usable.append(value)
                # source_count is the resolver's own count of contributors, so
                # "multi-source" means the index actually combined two
                # opinions - not merely that two sources were asked.
                if (index.source_count or 0) >= 2:
                    multi += 1
                else:
                    single += 1
            continue

        for source_value in index.source_values:
            if source_value.source != basis.source_name:
                continue
            # EXCLUDED-because-constrained, which is narrower than
            # "carries a constraint". source_semantics ships four verdicts and
            # only two of them disqualify: platform_floor and
            # below_platform_minimum are ineligible, sale_price is a fully
            # valid market price that merely has a name. Reading `constraint`
            # alone would have reported Yuyu-Tei's 36 sale-priced prints as
            # impaired coverage when every one of them is a real price a
            # collector can pay today - see source_semantics, "Anything
            # reading `constraint` as a synonym for 'excluded' is reading it
            # wrong; `eligible` is the field that answers that."
            #
            # Both conditions, and no constraint NAME: a future ineligible
            # constraint is counted here the day the classifier ships it, and
            # a future eligible one is correctly ignored, with no edit.
            if source_value.constraint is not None and not source_value.eligible:
                excluded_constrained += 1
            # BOTH conditions: eligible alone is not a price if no number was
            # reported, and a number alone is not a price if semantics
            # disqualified it. The ¥1,000 platform floor is exactly the second
            # case and must never reach `usable`.
            if source_value.eligible and source_value.value_jpy is not None:
                usable.append(source_value.value_jpy)

    usable.sort()
    if basis.kind == KIND_MARKET_INDEX:
        # A constraint is a property of a source's reading. The index is a
        # combination, carries no constraint of its own, and reporting 0 here
        # would be a claim about something that has no answer.
        return usable, None, {"single_source_prints": single, "multi_source_prints": multi}
    return usable, excluded_constrained, {}


def build_overview(
    db: Session,
    *,
    basis: BasisRequest,
    set_code: str | None = None,
    rarity: str | None = None,
) -> dict:
    """The whole CURRENT-STATE payload for one basis and one scope.

    Query shape is flat and bounded: one query for the scope, a fixed handful
    inside get_market_index_for_prints regardless of how many prints it is
    given, and one grouped count for observed prints. Nothing iterates prints
    issuing queries - a 4,316-print scope costs the same round trips as a
    10-print one.
    """
    print_ids = scoped_print_ids(db, set_code=set_code, rarity=rarity)
    # The scope's size is the denominator of coverage and is counted here, in
    # full. Only the observed subset is then RESOLVED - see
    # prints_with_observations for why that cannot move a published number.
    active_prints = len(print_ids)
    resolvable = prints_with_observations(db, print_ids)
    indexes = _all_indexes(db, resolvable)
    usable, excluded_constrained, composition = _basis_values(basis, indexes)

    observed: int | None = None
    available = True
    unavailable_reason: str | None = None
    reference_type = evidence_type = None

    if basis.kind == KIND_SOURCE:
        reference_type, evidence_type = describe_source_basis(basis.source_name or "")
        observed = observed_print_counts(db, print_ids).get(basis.source_name or "", 0)
        source_exists = db.scalar(select(Source.id).where(Source.name == basis.source_name))
        if source_exists is None or reference_type is None:
            # Unknown, or configured but with no primary instrument. Answered,
            # never 404'd: "Atlas does not price with that" is a real answer,
            # and every count below stays truthfully zero rather than absent.
            available = False
            unavailable_reason = UNAVAILABLE_SOURCE_NOT_CONFIGURED
        elif not usable:
            available = False
            unavailable_reason = UNAVAILABLE_NO_USABLE_PRICES

    constituent_count = len(usable)
    if constituent_count == 0:
        median = p10 = p90 = None
        price_reason: str | None = NO_USABLE_PRICES
    elif constituent_count < MIN_PERCENTILE_CONSTITUENTS:
        median = percentile(usable, 0.5)
        p10 = p90 = None
        price_reason = INSUFFICIENT_CONSTITUENTS
    else:
        median = percentile(usable, 0.5)
        p10 = percentile(usable, 0.10)
        p90 = percentile(usable, 0.90)
        price_reason = None

    return {
        "price_basis": basis.key,
        "kind": basis.kind,
        "source": basis.source_name,
        "reference_type": reference_type,
        "evidence_type": evidence_type,
        "available": available,
        "unavailable_reason": unavailable_reason,
        "scope": {"active_prints": active_prints, "set": set_code, "rarity": rarity},
        "coverage": {
            "observed_prints": observed,
            "usable_priced_prints": constituent_count,
            # Guarded against an empty scope: 0/0 is not 0%, it is no answer.
            "coverage_pct": (
                round(constituent_count / active_prints * 100, 2) if active_prints else None
            ),
            "excluded_constrained_prints": excluded_constrained,
            "unavailable_prints": active_prints - constituent_count,
        },
        "current_price": {
            "constituent_count": constituent_count,
            "median_jpy": median,
            "p10_jpy": p10,
            "p90_jpy": p90,
            "unavailable_reason": price_reason,
        },
        "distribution": bucket_distribution(usable),
        "index_composition": composition or None,
    }


def list_bases(db: Session) -> list[dict]:
    """Every price basis a client may select, derived rather than listed.

    Market Index first - it is the product's own answer and the default - then
    one entry per source that BOTH exists in the `sources` table AND has a
    configured primary instrument. The intersection is what excludes an
    auxiliary-only source from ever becoming a selectable basis: Yuyu-Tei's
    dealer buy is not a primary instrument, so it contributes no key, and
    there is no rule here naming it.

    `available` is false for a source with no usable price anywhere, so a
    client can drop it rather than render a control that answers nothing - but
    the row is still returned, with its count, because "SNKRDUNK has priced 25
    prints" is a fact worth showing and silence is not.
    """
    print_ids = scoped_print_ids(db)
    indexes = _all_indexes(db, prints_with_observations(db, print_ids))

    index_usable = sum(1 for i in indexes.values() if i.index_value_jpy is not None)
    bases: list[dict] = [
        {
            "key": MARKET_INDEX_BASIS,
            "kind": KIND_MARKET_INDEX,
            "source": None,
            "reference_type": None,
            "evidence_type": None,
            "available": index_usable > 0,
            "unavailable_reason": None if index_usable else UNAVAILABLE_NO_USABLE_PRICES,
            "usable_priced_prints": index_usable,
        }
    ]

    for name in sorted(db.scalars(select(Source.name)).all()):
        reference_type, evidence_type = describe_source_basis(name)
        if reference_type is None:
            # No configured PRIMARY instrument: an unknown source, or one whose
            # every instrument is auxiliary. Either way there is no basis to
            # offer and nothing here had to know its name to decide that.
            continue
        request = BasisRequest(key=f"{SOURCE_BASIS_PREFIX}{name}", kind=KIND_SOURCE, source_name=name)
        usable, _, _ = _basis_values(request, indexes)
        bases.append(
            {
                "key": request.key,
                "kind": KIND_SOURCE,
                "source": name,
                "reference_type": reference_type,
                "evidence_type": evidence_type,
                "available": bool(usable),
                "unavailable_reason": None if usable else UNAVAILABLE_NO_USABLE_PRICES,
                "usable_priced_prints": len(usable),
            }
        )
    return bases


def _all_indexes(db: Session, print_ids: list[int]) -> dict:
    from app.services.print_market_index import get_market_index_for_prints

    return get_market_index_for_prints(db, print_ids) if print_ids else {}
