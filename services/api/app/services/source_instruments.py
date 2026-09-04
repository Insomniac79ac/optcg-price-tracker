"""What KIND of price a stored observation is - the naming layer between
`price_observations.price_type` (stored vocabulary) and the API-facing
`reference_type`/`evidence_type` pair every pricing payload already speaks.

Why this is a separate module from source_semantics
----------------------------------------------------
`app.services.source_semantics` answers "does this number mean what it says?"
- constraint, eligible, ineligible_reason. That is a question about VALIDITY,
it is versioned by SOURCE_SEMANTICS_VERSION, and archived Market Index
snapshots depend on it never changing meaning underneath them.

This module answers a different and much smaller question: "what instrument is
this an observation of?" - a retail asking price, a marketplace listing floor,
a dealer buy quote, a completed-transaction median. That is NAMING, not
validity. Nothing here can make an observation eligible or ineligible,
constrain a value, or move an index number, so nothing here is covered by
SOURCE_SEMANTICS_VERSION and changing it requires no version bump. Keeping the
two apart is what lets a future source acquire a label without touching the
ruleset that historical snapshots are frozen against.

Why the strings are restated rather than imported
--------------------------------------------------
The API-facing reference_type/evidence_type values are chosen today inside
`app.services.market_index`'s per-source resolvers, as literals on the
`_SourceValue` each one returns. Those resolvers answer for the LATEST value
only - they apply freshness windows and the sold-sample minimum relative to
`now` - so they cannot be called per historical point without retro-applying
today's staleness to a point captured weeks ago. A historical series therefore
needs the same vocabulary reached a different way.

This is the same trade `source_semantics` already documents for source and
price_type constants: restate, and hold the restatement honest with a test
rather than with a comment. `tests/test_print_series.py` asserts every entry
below against the shipped resolvers' own output, so the two cannot drift
without a red test.

Unknown is a first-class answer
--------------------------------
An unconfigured (source, price_type) returns an instrument with
`reference_type=None` and `evidence_type=None` rather than raising or guessing.
A future Card Rush / Mercado / Cardmarket observation is then charted as an
unlabelled series of real numbers - honest about what Atlas knows - instead of
being dropped or given an invented label. This mirrors
`classify_observation`'s fail-open rule for an unconfigured source, and it is
what keeps this module free of any allowlist: nothing here decides whether a
source may be charted, only how its points can be described.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.print_market_index import (
    AUXILIARY_ONLY_PRICE_TYPES,
    SNKRDUNK,
    SNKRDUNK_FLOOR_PRICE_TYPE,
    SNKRDUNK_SOLD_PRICE_TYPE,
    YUYUTEI,
    YUYUTEI_BUY_PRICE_TYPE,
    YUYUTEI_SELL_PRICE_TYPE,
)

# The two roles a series can play in a collector-facing chart.
#
# PRIMARY   market-facing evidence - what the card is being offered or traded
#           at. These are the series a platform selector shows by default.
# AUXILIARY read and reported, but never market-facing and never an index
#           input. Yuyu-Tei's dealer buy quote is the only one today: it is
#           what a shop pays, not what the card costs, and putting it in the
#           same line as retail sell would silently halve a card's apparent
#           price. There is NO public selector that reaches one today: a
#           platform series returns its primary instruments only, and the
#           extension point when auxiliary values are wanted is a
#           request-level flag - see app.services.print_series.parse_series_key.
ROLE_PRIMARY = "primary"
ROLE_AUXILIARY = "auxiliary"

# Evidence kinds, matching MarketIndexSourceValueOut.evidence_type.
EVIDENCE_LISTING = "listing"
EVIDENCE_TRANSACTION = "transaction"


@dataclass(frozen=True)
class SourceInstrument:
    """How one (source, stored price_type) pair is described to a client.

    Frozen so the shared unknown-instrument default below can be handed out
    without any caller being able to mutate the registry through it.
    """

    reference_type: str | None
    evidence_type: str | None
    role: str

    @property
    def is_known(self) -> bool:
        return self.reference_type is not None


# The unconfigured answer. `role` is primary rather than auxiliary on purpose:
# a source Atlas has no rule for is presumed to be quoting a market-facing
# price, because that is what every configured source does and because hiding
# an unknown series by default would make a newly-added source look broken.
UNKNOWN_INSTRUMENT = SourceInstrument(reference_type=None, evidence_type=None, role=ROLE_PRIMARY)


def _role_for(source: str, price_type: str) -> str:
    """Auxiliary iff the shipped index config says so - never a second list.

    Read from app.services.print_market_index.AUXILIARY_ONLY_PRICE_TYPES, the
    same constant `snapshot_market_index` derives its evidence set from, so a
    price_type that stops being auxiliary stops being auxiliary here too with
    no edit.
    """
    return (
        ROLE_AUXILIARY
        if price_type in AUXILIARY_ONLY_PRICE_TYPES.get(source, ())
        else ROLE_PRIMARY
    )


def _instrument(source: str, price_type: str, reference_type: str, evidence_type: str):
    return (source, price_type), SourceInstrument(
        reference_type=reference_type,
        evidence_type=evidence_type,
        role=_role_for(source, price_type),
    )


# Keyed on (sources.name, price_observations.price_type) - the STORED
# vocabulary, never the API-facing one. SNKRDUNK stores "floor" and is
# reported as "listing_floor"; a registry keyed on the latter would match zero
# rows, which is the exact trap source_semantics documents.
SOURCE_INSTRUMENTS: dict[tuple[str, str], SourceInstrument] = dict(
    (
        # market_index._resolve_yuyutei_sell
        _instrument(YUYUTEI, YUYUTEI_SELL_PRICE_TYPE, "retail_sell", EVIDENCE_LISTING),
        # market_index._resolve_yuyutei_buy - auxiliary_only, and the reason
        # ROLE_AUXILIARY exists at all.
        _instrument(YUYUTEI, YUYUTEI_BUY_PRICE_TYPE, "dealer_buy", EVIDENCE_LISTING),
        # market_index._resolve_snkrdunk, fallback branch
        _instrument(SNKRDUNK, SNKRDUNK_FLOOR_PRICE_TYPE, "listing_floor", EVIDENCE_LISTING),
        # market_index._resolve_snkrdunk, sold branch.
        #
        # AN OPEN PRODUCT QUESTION IS PARKED HERE, DELIBERATELY UNRESOLVED.
        # The resolver's "transaction_median" is a median over the recent sold
        # sample; a single stored `sold` row is one completed sale. Zero such
        # rows exist anywhere today (the SNKRDUNK collector does not persist
        # sold history - no stable per-sale identifier exists in its DOM, see
        # snkrdunk_collector/sales_history.py), so no historical point has ever
        # been labelled with this and nothing is currently mislabelled. When
        # sold rows do begin to exist, whether a daily point should be the
        # latest sale or that day's median is a product decision that must be
        # made before this series is charted - it is NOT settled by naming it
        # here. What is settled, and is the part this module is responsible
        # for, is that sold evidence is a DIFFERENT INSTRUMENT from a listing
        # floor and can never share a line with one.
        _instrument(SNKRDUNK, SNKRDUNK_SOLD_PRICE_TYPE, "transaction_median", EVIDENCE_TRANSACTION),
    )
)


def describe_instrument(source: str, price_type: str) -> SourceInstrument:
    """The instrument for one (source, stored price_type), never raising.

    Returns UNKNOWN_INSTRUMENT for anything unconfigured. There is no
    allowlist here and no source name is privileged: a caller asking about a
    source this build has never heard of gets a usable, honestly-unlabelled
    answer rather than an error.
    """
    return SOURCE_INSTRUMENTS.get((source, price_type), UNKNOWN_INSTRUMENT)


def primary_price_types(source: str) -> tuple[str, ...]:
    """The stored price_types that belong in `source:<name>`'s default series.

    Auxiliary instruments are excluded, which is the mechanism that keeps
    Yuyu-Tei's dealer buy out of the retail line. Empty for an unconfigured
    source - a caller must then fall back to whatever price_types the print
    actually has observations for, because an unknown source has no
    configuration to read and its data is not thereby less real.
    """
    return tuple(
        price_type
        for (registered_source, price_type), instrument in SOURCE_INSTRUMENTS.items()
        if registered_source == source and instrument.role == ROLE_PRIMARY
    )


__all__ = [
    "EVIDENCE_LISTING",
    "EVIDENCE_TRANSACTION",
    "ROLE_AUXILIARY",
    "ROLE_PRIMARY",
    "SOURCE_INSTRUMENTS",
    "SourceInstrument",
    "UNKNOWN_INSTRUMENT",
    "describe_instrument",
    "primary_price_types",
]
