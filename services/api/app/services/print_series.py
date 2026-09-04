"""Exact-print historical price series - one shape for every platform.

WHAT THIS IS FOR. A collector picks a PLATFORM ("SNKRDUNK", "Yuyu-Tei",
"Market Index"), not an instrument. The server's job is to answer that request
without ever flattening two different measurements into one line: a SNKRDUNK
series that switches from a listing floor to a completed-sale median has not
"moved", it has changed instrument, and drawing one stroke through the change
would publish a category error as a price movement. So the selector is
platform-level and the response is segmented - see SEGMENTS below.

That is the same reasoning app.services.market_index_change already applies to
the 7-day index change, where the eligible contributor set must be identical
by (source, reference_type) at both ends before any movement is reported.

WHAT THIS MODULE REFUSES TO DECIDE
-----------------------------------
* Whether a value is admissible. `constraint`/`eligible`/`ineligible_reason`
  come from app.services.source_semantics.classify_observation - the same
  classifier market_index's resolvers and GET /prints/{id}/prices use. No
  threshold, no platform minimum and no source name is restated here; a
  SNKRDUNK observation at the ¥1,000 platform floor arrives labelled
  `platform_floor`/ineligible exactly as it does everywhere else, and this
  module neither drops it nor promotes it to an ordinary price.
* What instrument an observation is. That is
  app.services.source_instruments.describe_instrument.
* What a historical Market Index value was. That is
  market_index_snapshots, read verbatim. Nothing here recomputes an index.

THE STORED price_type VOCABULARY IS PRIVATE - IN BOTH DIRECTIONS
-----------------------------------------------------------------
`price_observations.price_type` is collector-side storage ("sell", "floor"),
and it appears in neither half of the public contract. Not in a REQUEST: the
selector is `source:<name>` alone, and `source:yuyutei:sell` is rejected, so
no saved chart URL can be broken by a collector renaming a column value. Not
in a RESPONSE either: a published `price_type` is a field clients would branch
on within a week, which would re-create the same coupling one layer down and
leave it undetectable. What a point IS gets said in the vocabulary the rest of
the pricing API already speaks - `reference_type`/`evidence_type` - and where
Atlas has no rule for a source, the honest answer is that both are null.

Internally price_type is load-bearing and stays so: it groups daily
normalisation, it selects a platform's primary instruments, and it splits
segments where two unlabelled instruments would otherwise merge.

NO ALLOWLIST, ANYWHERE
-----------------------
Source keys resolve against the `sources` table. There is no VALID_SOURCES
tuple, no enum and no per-source branch in this module: adding Card Rush,
Mercado or Cardmarket to `sources` makes `source:cardrush` a working series
key with no code change, unlabelled but real (see source_instruments'
"Unknown is a first-class answer"). A key naming a source that is not
configured is answered with an explicit unavailable series - never a 404, and
never invented points.

DAILY NORMALISATION - THE ONE TRANSFORM THIS MODULE PERFORMS
--------------------------------------------------------------
Collectors poll on their own schedules: Yuyu-Tei nightly, SNKRDUNK three times
a day, and a manual re-run can add more. 70 (print, source, day) groups on
staging already hold more than one observation. Left alone, a chart's density
would be a picture of Atlas's cron configuration rather than of the market,
and a source polled more often would appear to move more.

So each series is normalised to AT MOST ONE POINT PER UTC CALENDAR DAY, per
exact print, per source, per stored price_type, and that point is the LATEST
stored observation of that day (`observed_at` desc, `id` desc as the
deterministic tie-break, matching print_pricing.get_latest_prices_for_prints).

  * NOT an average, and not a median. Every point is a real number the source
    actually displayed at a real instant, which is what makes the accompanying
    `constraint`/`eligible` annotation meaningful - an averaged point would
    have no single semantics to annotate.
  * A day with no observation gets NO POINT. There is no forward-fill, no
    interpolation and no carried-forward last value: a gap is a gap, and
    inventing a flat line through one would assert a price nobody observed.
  * A missing price is an absent point, never 0. `price_observations.price_jpy`
    is NOT NULL, so a source point always carries a real number; the only
    nullable value in the payload is a Market Index point whose archived
    `index_value_jpy` was genuinely NULL (coverage_status='none'), which is a
    recorded result rather than missing data.

`observations_in_day` reports how many stored rows the day held, so a reader
can tell a single nightly reading from the last of three without this module
having to hide that the others existed.

SEGMENTS AND BREAKS
--------------------
Within one platform series, points are walked oldest-first and a new segment
starts whenever the instrument changes:

  * source series      - the INSTRUMENT changes: `reference_type`
                         (listing_floor -> transaction_median, or either ->
                         an unlabelled unknown) or, where a source is
                         unconfigured and every instrument is unlabelled, the
                         stored price_type beneath it. Two instruments Atlas
                         cannot name are still two instruments.
  * market_index series - `index_version` or `source_semantics_version`
                         changes. Staging already holds v1 (2026-08-21..09-01),
                         v2 (09-02) and v3 (09-03) in one 14-day table, so this
                         is not hypothetical: an unsegmented line would draw
                         two methodology changes as price movement.

Every boundary is also reported in `breaks`, timestamped at the FIRST POINT
AFTER the change with the old and new values, so a client can render a marker
("Market Index methodology updated") without re-deriving the boundary from the
segments.

COVERAGE IS FACTUAL, NOT A SCORE
---------------------------------
`coverage` reports earliest, latest, distinct_days and point count, plus
`covers_7d`/`covers_30d` - each strictly "does this series reach back to at
least the UTC day N days before generated_at". SPAN, not volume, and not a
count: 14 days of Market Index history covers 7 days and does NOT cover 30,
which is what today's data actually is. Null where the requested window is too
narrow to answer. Sparse history spanning a window still covers it - a point on
every day is never required, and the gaps stay gaps.

It is NOT a confidence, quality or reliability measure and must never be
presented as one. (Note that market_index_snapshots.confidence is likewise a
1:1 relabelling of coverage_status, not a quality metric - see that model's
docstring. It is carried through verbatim on index points and given no
interpretation here.)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import MarketIndexSnapshot, PriceObservation, Source
from app.services.source_instruments import (
    ROLE_PRIMARY,
    SourceInstrument,
    describe_instrument,
    primary_price_types,
)
from app.services.source_semantics import classify_observation

# The windows this endpoint offers. 90d is deliberately ABSENT rather than
# present-and-empty: the deepest history in the system is 27 days old, so a
# 90-day frame would render a quarter of a chart's width as a claim about data
# that does not exist. It is added when the data reaches it, not before.
WINDOW_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
DEFAULT_WINDOW = "30d"

KIND_MARKET_INDEX = "market_index"
KIND_SOURCE = "source"

MARKET_INDEX_KEY = "market_index"
SOURCE_KEY_PREFIX = "source:"

# Why a series carries no points.
UNAVAILABLE_SOURCE_NOT_CONFIGURED = "source_not_configured"
UNAVAILABLE_NO_HISTORY = "no_history_in_window"

BREAK_REFERENCE_TYPE_CHANGE = "reference_type_change"
# An instrument change that the API-facing vocabulary cannot name: two stored
# price_types of an UNCONFIGURED source both describe as `reference_type=None`,
# and welding them into one segment because their labels match would do exactly
# what this module exists to prevent. The boundary is real even where Atlas
# cannot say what changed, so it is reported under its own reason rather than
# as a reference_type_change from null to null.
BREAK_INSTRUMENT_CHANGE = "instrument_change"
BREAK_INDEX_VERSION_CHANGE = "index_version_change"
BREAK_SOURCE_SEMANTICS_VERSION_CHANGE = "source_semantics_version_change"


class SeriesKeyError(ValueError):
    """A series key this module cannot parse - a client error, never a
    statement about whether the named platform has data."""


@dataclass(frozen=True)
class SeriesRequest:
    """One parsed selector: a PLATFORM, never an instrument.

    There is deliberately no price_type field. Which instruments belong to a
    platform is the server's decision - see `_build_source_series` - and a
    client that could name one would be depending on the fact that Yuyu-Tei
    happens to store "sell" and SNKRDUNK happens to store "floor". Those are
    collector-side storage details, not public vocabulary, and a source that
    renamed one would break every saved chart URL.
    """

    key: str
    kind: str
    source_name: str | None = None


def parse_series_key(key: str) -> SeriesRequest:
    """`market_index` or `source:<name>`. Nothing else.

    THE PUBLIC CONTRACT IS PLATFORM-LEVEL. A caller selects who is quoting the
    price, and the response says what KIND of price it was through each
    segment's reference_type/evidence_type. That indirection is the whole
    point: the stored price_type vocabulary stays private, and an instrument
    change over time shows up as a segment boundary rather than as two
    different things the client had to know to ask for.

    THE EXTENSION POINT FOR AUXILIARY SERIES, when one is wanted, is a
    separate REQUEST-LEVEL flag - e.g. `?include=auxiliary` - which would let
    `_build_source_series` widen the instrument set it selects. It is
    deliberately NOT a wider key grammar: `source:yuyutei:buy` would put a
    stored price_type back in the public contract to solve a problem that a
    boolean solves without one. Nothing in this tranche exposes auxiliary
    values, and `role` is already on every series so a client can tell them
    apart the day they appear.

    The source name is not validated here - this function knows no source
    names, and an unrecognised one is resolved (and reported unavailable)
    against the `sources` table later.
    """
    cleaned = (key or "").strip()
    if not cleaned:
        raise SeriesKeyError("Series key must not be empty")
    if cleaned == MARKET_INDEX_KEY:
        return SeriesRequest(key=cleaned, kind=KIND_MARKET_INDEX)
    if not cleaned.startswith(SOURCE_KEY_PREFIX):
        raise SeriesKeyError(
            f"Unrecognised series key {key!r}. Expected {MARKET_INDEX_KEY!r} "
            f"or {SOURCE_KEY_PREFIX}<source>."
        )
    source_name = cleaned[len(SOURCE_KEY_PREFIX) :]
    if not source_name or ":" in source_name:
        raise SeriesKeyError(
            f"Unrecognised series key {key!r}. Expected {SOURCE_KEY_PREFIX}<source> - "
            "a platform name alone. Instrument selection is the server's decision and "
            "is reported per segment, never requested."
        )
    return SeriesRequest(key=cleaned, kind=KIND_SOURCE, source_name=source_name)


def window_start(window: str, now: datetime) -> datetime | None:
    """The inclusive lower bound for a window, or None for `all`."""
    days = WINDOW_DAYS[window]
    return None if days is None else now - timedelta(days=days)


def _naive_utc(value: datetime) -> datetime:
    """Comparable with the naive timestamps SQLite hands back, without moving
    an instant. Mirrors market_index._naive_utc."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _utc_day(value: datetime) -> date:
    return _naive_utc(value).date()


@dataclass
class _Point:
    """One normalised point, before it becomes a schema object."""

    t: datetime
    day: date
    value_jpy: int | None
    reference_type: str | None = None
    evidence_type: str | None = None
    price_type: str | None = None
    eligible: bool | None = None
    constraint: str | None = None
    ineligible_reason: str | None = None
    sample_size: int | None = None
    observations_in_day: int | None = None
    index_version: int | None = None
    source_semantics_version: int | None = None
    source_count: int | None = None
    coverage_status: str | None = None
    source_price_range_low_jpy: int | None = None
    source_price_range_high_jpy: int | None = None


@dataclass
class _Segment:
    reference_type: str | None = None
    evidence_type: str | None = None
    price_type: str | None = None
    index_version: int | None = None
    source_semantics_version: int | None = None
    points: list[_Point] = field(default_factory=list)


def _daily_latest(
    observations: list[PriceObservation],
) -> list[tuple[PriceObservation, int]]:
    """The normalisation rule, in one place: latest stored observation per
    (price_type, UTC day), paired with how many rows that day actually held.

    Grouping includes price_type so two instruments captured on the same day
    both survive - collapsing them would silently discard one measurement, and
    it is exactly the kind of measurement whose disappearance nobody would
    notice. Ordering is (observed_at, id) descending, the same deterministic
    tie-break print_pricing uses for "latest".
    """
    buckets: dict[tuple[str, date], list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        buckets[(obs.price_type, _utc_day(obs.observed_at))].append(obs)

    chosen: list[tuple[PriceObservation, int]] = []
    for rows in buckets.values():
        rows.sort(key=lambda o: (_naive_utc(o.observed_at), o.id))
        chosen.append((rows[-1], len(rows)))
    chosen.sort(key=lambda pair: (_naive_utc(pair[0].observed_at), pair[0].id))
    return chosen


def _source_points(
    observations: list[PriceObservation], source_name: str
) -> list[_Point]:
    points: list[_Point] = []
    for obs, in_day in _daily_latest(observations):
        instrument: SourceInstrument = describe_instrument(source_name, obs.price_type)
        # The shipped classifier, asked exactly as every other read path asks
        # it. Nothing below re-derives a threshold, and the verdict is attached
        # to the point rather than used to filter it: a constrained ¥1,000
        # platform floor stays visible AND stays marked ineligible, so a client
        # can show it without a client-side rule and can never mistake it for
        # an ordinary market price.
        semantics = classify_observation(
            source_name, obs.price_type, obs.price_jpy, obs.promotion_state
        )
        points.append(
            _Point(
                t=obs.observed_at,
                day=_utc_day(obs.observed_at),
                value_jpy=obs.price_jpy,
                reference_type=instrument.reference_type,
                evidence_type=instrument.evidence_type,
                price_type=obs.price_type,
                eligible=semantics.eligible,
                constraint=semantics.constraint,
                ineligible_reason=semantics.ineligible_reason,
                # No stored observation is an aggregate of others, so there is
                # no sample behind it to report. The field exists because a
                # future aggregated instrument would have one; leaving it null
                # is the honest answer for every row that exists today.
                sample_size=None,
                observations_in_day=in_day,
            )
        )
    return points


def _snapshot_points(snapshots: list[MarketIndexSnapshot]) -> list[_Point]:
    return [
        _Point(
            t=snap.calculated_at,
            day=snap.snapshot_date,
            # NULL here is a recorded result - "no source was eligible that
            # day" - guarded by ck_market_index_snapshots_value_presence. It is
            # not missing data and must never be rendered as 0.
            value_jpy=snap.index_value_jpy,
            index_version=snap.index_version,
            source_semantics_version=snap.source_semantics_version,
            source_count=snap.source_count,
            coverage_status=snap.coverage_status,
            source_price_range_low_jpy=snap.source_price_range_low_jpy,
            source_price_range_high_jpy=snap.source_price_range_high_jpy,
        )
        for snap in snapshots
    ]


def _segment_source_points(points: list[_Point]) -> tuple[list[_Segment], list[dict]]:
    """Split wherever the INSTRUMENT changes; report each boundary.

    The instrument is the stored (price_type -> reference_type) pair, and the
    split tests BOTH halves. For a configured source that is the same test
    twice - "sell" is the only thing describing as retail_sell, "floor" the
    only thing describing as listing_floor - so nothing changes. For an
    UNCONFIGURED source it is the whole point: every price_type it stores
    describes as `reference_type=None`, so a label-only test would weld a
    hypothetical cardrush "listing" line to its "sold" line and draw a change
    of measuring instrument as a price movement, which is precisely the error
    this module exists to prevent. Being unlabelled is not being the same.

    Splitting per price_type does NOT break an unknown series at every point:
    a source storing one price_type is still one continuous segment, which is
    every source that exists today.
    """
    segments: list[_Segment] = []
    breaks: list[dict] = []
    for point in points:
        current = segments[-1] if segments else None
        same_instrument = (
            current is not None
            and current.reference_type == point.reference_type
            and current.price_type == point.price_type
        )
        if same_instrument:
            current.points.append(point)
            continue
        if current is not None:
            breaks.append(
                {
                    "at": point.t,
                    # Named for what a client can actually be told: the label
                    # moved, or the instrument moved beneath an unchanged
                    # (unlabelled) label.
                    "reason": (
                        BREAK_REFERENCE_TYPE_CHANGE
                        if current.reference_type != point.reference_type
                        else BREAK_INSTRUMENT_CHANGE
                    ),
                    "from_reference_type": current.reference_type,
                    "to_reference_type": point.reference_type,
                }
            )
        segments.append(
            _Segment(
                reference_type=point.reference_type,
                evidence_type=point.evidence_type,
                price_type=point.price_type,
                points=[point],
            )
        )
    return segments, breaks


def _segment_index_points(points: list[_Point]) -> tuple[list[_Segment], list[dict]]:
    """Split on either archived version changing, and say which one moved.

    Both are reported because they mean different things: INDEX_VERSION is the
    combination algorithm and SOURCE_SEMANTICS_VERSION is the per-source
    ruleset, and they move on different cadences (a snapshot records them
    independently). A day where both changed emits one break per changed
    field, so a client is never left guessing which methodology moved.
    """
    segments: list[_Segment] = []
    breaks: list[dict] = []
    for point in points:
        current = segments[-1] if segments else None
        same = (
            current is not None
            and current.index_version == point.index_version
            and current.source_semantics_version == point.source_semantics_version
        )
        if same:
            current.points.append(point)
            continue
        if current is not None:
            if current.index_version != point.index_version:
                breaks.append(
                    {
                        "at": point.t,
                        "reason": BREAK_INDEX_VERSION_CHANGE,
                        "from_index_version": current.index_version,
                        "to_index_version": point.index_version,
                    }
                )
            if current.source_semantics_version != point.source_semantics_version:
                breaks.append(
                    {
                        "at": point.t,
                        "reason": BREAK_SOURCE_SEMANTICS_VERSION_CHANGE,
                        "from_source_semantics_version": current.source_semantics_version,
                        "to_source_semantics_version": point.source_semantics_version,
                    }
                )
        segments.append(
            _Segment(
                index_version=point.index_version,
                source_semantics_version=point.source_semantics_version,
                points=[point],
            )
        )
    return segments, breaks


def _coverage(points: list[_Point], now: datetime, window: str) -> dict:
    """Measured facts about what this series holds. Never a score.

    `covers_7d`/`covers_30d` ANSWER SPAN, NOT VOLUME. Each asks exactly one
    question: does this series reach back to at least the UTC calendar day N
    days before `generated_at`? They were previously named
    `sufficient_for_*` and meant "there are at least two points somewhere in
    there", which reported `sufficient_for_30d: true` for a series holding 14
    days - technically "enough to draw a line" and, as a claim about a 30-day
    window, misleading. The rename is deliberate: `covers_` states what is
    now measured, and nothing named `sufficient` survives to be read the old
    way.

    Compared on UTC CALENDAR DAYS, consistently with daily normalisation: a
    point is identified by its day, so "reaches back 7 days" means "has a
    point on or before the day that is 7 days ago". It does NOT require a
    point on every day in between - sparse history spanning the window covers
    the window, and the gaps stay honest gaps with no invented points.

    NULL MEANS "THIS REQUEST CANNOT ANSWER IT". A `window=7d` request truncates
    the data at 7 days by construction, so it can say nothing about whether 30
    days of history exists; `covers_30d` is null rather than a false that would
    read as "there is no 30-day history". A wider window answers both.

    A window asked about its OWN width answers about its own edge: under
    `window=30d` the data stops at `now - 30 days`, so `covers_30d` reports
    whether the returned points reach that start instant. History older than
    the window was never in this response to be measured, and `window=all`
    is where the unbounded answer lives.

    Still not a confidence, quality or reliability measure, and still nothing
    to do with market_index_snapshots.confidence - which is a 1:1 relabelling
    of coverage_status, carried through verbatim on index points and given no
    interpretation here.
    """
    window_days = WINDOW_DAYS[window]

    def covers(day_count: int) -> bool | None:
        # A window narrower than the span being asked about cannot answer it.
        if window_days is not None and window_days < day_count:
            return None
        if not points:
            return False
        earliest_day = min(point.day for point in points)
        return earliest_day <= (_naive_utc(now) - timedelta(days=day_count)).date()

    if not points:
        return {
            "earliest": None,
            "latest": None,
            "distinct_days": 0,
            "point_count": 0,
            "covers_7d": covers(7),
            "covers_30d": covers(30),
        }
    return {
        "earliest": min(point.t for point in points),
        "latest": max(point.t for point in points),
        "distinct_days": len({point.day for point in points}),
        "point_count": len(points),
        "covers_7d": covers(7),
        "covers_30d": covers(30),
    }


# Internal-only point fields: real, load-bearing, and not part of the public
# contract. See "THE STORED price_type VOCABULARY IS PRIVATE" above - this is
# the one place that rule is enforced, so a field added to _Point is published
# only by being left out of this set.
PRIVATE_POINT_FIELDS = frozenset({"price_type"})


def _public_point(point: _Point) -> dict:
    return {
        name: value
        for name, value in vars(point).items()
        if name not in PRIVATE_POINT_FIELDS
    }


def _series_payload(
    *,
    key: str,
    kind: str,
    source: str | None,
    role: str,
    segments: list[_Segment],
    breaks: list[dict],
    points: list[_Point],
    now: datetime,
    window: str,
    unavailable_reason: str | None,
) -> dict:
    return {
        "key": key,
        "kind": kind,
        "source": source,
        "role": role,
        "available": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
        "segments": [
            {
                "reference_type": seg.reference_type,
                "evidence_type": seg.evidence_type,
                "index_version": seg.index_version,
                "source_semantics_version": seg.source_semantics_version,
                "points": [_public_point(point) for point in seg.points],
            }
            for seg in segments
        ],
        "breaks": breaks,
        "coverage": _coverage(points, now, window),
    }


def _instrument_filter(source_name: str, source_id: int):
    """The WHERE clause selecting one platform's PRIMARY instruments.

    A configured source is narrowed to its primary price_types, which is the
    mechanism that keeps Yuyu-Tei's auxiliary dealer-buy quote out of
    `source:yuyutei`. An unconfigured source has no primary set to read, so it
    is taken unfiltered: its data is not less real for being unlabelled, and
    it cannot carry an auxiliary instrument anyway - being auxiliary requires a
    configuration entry.
    """
    price_types = primary_price_types(source_name)
    clause = PriceObservation.source_id == source_id
    return and_(clause, PriceObservation.price_type.in_(price_types)) if price_types else clause


def load_observations_for_sources(
    db: Session,
    *,
    print_id: int,
    sources: list[tuple[str, int]],
    start: datetime | None,
) -> dict[int, list[PriceObservation]]:
    """Every requested platform's observations for one print, in ONE query.

    Partitioned in Python afterwards rather than issued per source: selecting
    four platforms is one round trip, not four, and this endpoint is called
    per print-detail page. There is no cache and no materialised table behind
    it - the composite index already makes the read cheap, and adding storage
    to save a round trip that a single OR removes would be the wrong trade.

    EXACT-PRINT AUTHORITATIVE BY CONSTRUCTION. Filtering on card_print_id is
    the whole isolation guarantee: the column is only ever set together with
    source_card_mapping_id (see ck_price_observations_lineage_paired), so a
    legacy lineage-less row can never match, and a sibling printing that
    bridges through the same legacy card_id has a different card_print_id and
    is unreachable from here. card_id is never consulted.

    Hits ix_price_observations_print_source_type_observed
    (card_print_id, source_id, price_type, observed_at).
    """
    by_source: dict[int, list[PriceObservation]] = {source_id: [] for _, source_id in sources}
    if not sources:
        return by_source

    stmt = select(PriceObservation).where(
        PriceObservation.card_print_id == print_id,
        or_(*(_instrument_filter(name, source_id) for name, source_id in sources)),
    )
    if start is not None:
        stmt = stmt.where(PriceObservation.observed_at >= start)

    for obs in db.scalars(
        stmt.order_by(PriceObservation.observed_at.asc(), PriceObservation.id.asc())
    ):
        by_source[obs.source_id].append(obs)
    return by_source


def _build_source_series(
    *,
    request: SeriesRequest,
    source_ids: dict[str, int],
    observations_by_source: dict[int, list[PriceObservation]],
    window: str,
    now: datetime,
) -> dict:
    """One platform series, built from already-fetched rows.

    Issues no query of its own - everything it needs was loaded in the single
    batch above, which is what keeps the request's query count flat as more
    platforms are selected.
    """
    source_name = request.source_name or ""
    source_id = source_ids.get(source_name)
    if source_id is None:
        # An unavailable source is answered honestly, not with a 404 and not
        # with invented points. A client asking for a platform Atlas does not
        # collect gets a named, empty, explicitly-unavailable series it can
        # render as "not tracked" - and the same shape it will get once that
        # platform is added.
        return _series_payload(
            key=request.key,
            kind=KIND_SOURCE,
            source=source_name,
            role=ROLE_PRIMARY,
            segments=[],
            breaks=[],
            points=[],
            now=now,
            window=window,
            unavailable_reason=UNAVAILABLE_SOURCE_NOT_CONFIGURED,
        )

    points = _source_points(observations_by_source.get(source_id, []), source_name)
    segments, breaks = _segment_source_points(points)
    return _series_payload(
        key=request.key,
        kind=KIND_SOURCE,
        source=source_name,
        # Every publicly reachable series is primary in this tranche: the
        # platform selector returns primary instruments only. `role` stays on
        # the schema so an auxiliary series is distinguishable the day a
        # request-level flag makes one reachable - see parse_series_key.
        role=ROLE_PRIMARY,
        segments=segments,
        breaks=breaks,
        points=points,
        now=now,
        window=window,
        unavailable_reason=None if points else UNAVAILABLE_NO_HISTORY,
    )


def _build_market_index_series(
    db: Session, *, print_id: int, start: datetime | None, now: datetime, window: str
) -> dict:
    """Archived Market Index values, read verbatim.

    THE ONLY SOURCE IS market_index_snapshots. No index is computed, no
    resolver is called and today's algorithm never touches a historical point:
    a past day cannot be recomputed under its own ruleset anyway (freshness
    windows are relative to the `now` they are handed, see the model's "No
    backfill"), so a recomputed value would claim Atlas published a number it
    never published.
    """
    stmt = select(MarketIndexSnapshot).where(MarketIndexSnapshot.card_print_id == print_id)
    if start is not None:
        stmt = stmt.where(MarketIndexSnapshot.calculated_at >= start)
    snapshots = list(
        db.scalars(
            stmt.order_by(
                MarketIndexSnapshot.snapshot_date.asc(), MarketIndexSnapshot.id.asc()
            )
        ).all()
    )
    points = _snapshot_points(snapshots)
    segments, breaks = _segment_index_points(points)
    return _series_payload(
        key=MARKET_INDEX_KEY,
        kind=KIND_MARKET_INDEX,
        source=None,
        role=ROLE_PRIMARY,
        segments=segments,
        breaks=breaks,
        points=points,
        now=now,
        window=window,
        unavailable_reason=None if points else UNAVAILABLE_NO_HISTORY,
    )


def load_source_catalogue(db: Session, print_id: int) -> tuple[dict[str, int], list[str]]:
    """Every source's id by name, AND which of them have observed this print -
    in ONE query.

    Two questions, one round trip, because they are the same row: resolving a
    requested `source:<name>` needs the id, and the default selection needs to
    know which platforms actually hold history for this print. Asked
    separately that is a `sources` read plus a DISTINCT join, and the default
    request - the one a print detail page sends - would pay four round trips
    where three do. The correlated EXISTS costs one index-only probe per
    source against ix_price_observations_print_source_type_observed.

    The observed list is DISCOVERED FROM THE DATA, never from a list of source
    names, so a source added tomorrow appears in the default selection the
    first time it records an observation, with no code change here.
    """
    observed = (
        select(PriceObservation.id)
        .where(
            PriceObservation.source_id == Source.id,
            PriceObservation.card_print_id == print_id,
        )
        .exists()
    )
    rows = db.execute(select(Source.id, Source.name, observed.label("observed"))).all()
    return (
        {name: source_id for source_id, name, _ in rows},
        sorted(name for _, name, has_history in rows if has_history),
    )


def default_series_requests(observed_sources: list[str]) -> list[SeriesRequest]:
    """What to return when the caller names no series.

    Market Index plus one PLATFORM series per source that has observed this
    print. Auxiliary instruments are deliberately absent - a platform series
    carries its primary instruments, and nothing in this tranche reaches an
    auxiliary one.

    Takes the already-loaded source list rather than querying: the catalogue
    read that resolves requested names answers this too (see
    load_source_catalogue), and issuing a second query for it is the round
    trip this endpoint does not need to spend.
    """
    keys = [MARKET_INDEX_KEY] + [f"{SOURCE_KEY_PREFIX}{name}" for name in observed_sources]
    return [parse_series_key(key) for key in keys]


def get_print_series(
    db: Session,
    print_id: int,
    *,
    series: list[SeriesRequest] | None = None,
    window: str = DEFAULT_WINDOW,
    now: datetime | None = None,
) -> dict:
    """The whole payload for one print, as plain dicts for the schema layer.

    Requested order is preserved, and a duplicate key is returned once: a
    client repeating a selector gets one series, not two identical lines.
    """
    if window not in WINDOW_DAYS:
        raise SeriesKeyError(f"Unsupported window {window!r}")
    now = now or datetime.now(timezone.utc)
    start = window_start(window, now)

    # THREE queries for a full request, regardless of how many platforms were
    # selected and regardless of whether the caller named any: the source
    # catalogue once (ids plus which sources have history for this print),
    # every requested platform's observations once, and the snapshot archive
    # once if Market Index was asked for.
    source_ids, observed_sources = load_source_catalogue(db, print_id)

    requests = series if series is not None else default_series_requests(observed_sources)
    seen: set[str] = set()
    ordered: list[SeriesRequest] = []
    for request in requests:
        if request.key in seen:
            continue
        seen.add(request.key)
        ordered.append(request)

    requested_sources = [
        (request.source_name, source_ids[request.source_name])
        for request in ordered
        if request.kind == KIND_SOURCE
        and request.source_name is not None
        and request.source_name in source_ids
    ]
    observations_by_source = load_observations_for_sources(
        db, print_id=print_id, sources=requested_sources, start=start
    )

    payload_series = [
        _build_market_index_series(
            db, print_id=print_id, start=start, now=now, window=window
        )
        if request.kind == KIND_MARKET_INDEX
        else _build_source_series(
            request=request,
            source_ids=source_ids,
            observations_by_source=observations_by_source,
            window=window,
            now=now,
        )
        for request in ordered
    ]

    return {
        "card_print_id": print_id,
        "window": window,
        "window_start": start,
        "generated_at": now,
        "series": payload_series,
    }


__all__ = [
    "BREAK_INDEX_VERSION_CHANGE",
    "BREAK_INSTRUMENT_CHANGE",
    "BREAK_REFERENCE_TYPE_CHANGE",
    "BREAK_SOURCE_SEMANTICS_VERSION_CHANGE",
    "DEFAULT_WINDOW",
    "KIND_MARKET_INDEX",
    "KIND_SOURCE",
    "MARKET_INDEX_KEY",
    "PRIVATE_POINT_FIELDS",
    "ROLE_PRIMARY",
    "UNAVAILABLE_NO_HISTORY",
    "UNAVAILABLE_SOURCE_NOT_CONFIGURED",
    "WINDOW_DAYS",
    "SeriesKeyError",
    "SeriesRequest",
    "default_series_requests",
    "load_observations_for_sources",
    "load_source_catalogue",
    "get_print_series",
    "parse_series_key",
    "window_start",
]
