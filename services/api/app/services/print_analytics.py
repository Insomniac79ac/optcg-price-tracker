"""Historical analytics for ONE exact print - the data behind the individual
print analytics page.

WHAT THIS OWNS, AND WHAT IT DELIBERATELY DOES NOT. This module answers "what
has this print's price history done?" over a chosen window. It does NOT answer
"what is this print?" (`GET /prints/{id}`) and it does NOT answer "what are the
current source prices?" (`GET /prints/{id}/prices`). Those stayed separate on
purpose: folding identity or a live price panel in here would make a historical
endpoint re-answer questions whose authority lives elsewhere, and would give
two endpoints the power to disagree about the same card.

NOTHING IS RECOMPUTED. Every figure published here is read off rows Atlas
already archived in `market_index_snapshots`. No resolver is called, no index
is recalculated, no current price is derived, nothing is averaged,
interpolated, forward-filled or back-filled, and a NULL archived index value -
a day on which no source was eligible - is a recorded result that stays null
rather than becoming ¥0. A past day cannot honestly be recomputed under
today's ruleset anyway (freshness windows are relative to the `now` they were
handed), so a recomputed value would claim Atlas published a number it never
published.

THREE VOCABULARIES, ALL BORROWED, NONE INVENTED HERE:

  * The WINDOW grammar (2w/1m/3m/6m/1y/2y/all), its span-test availability and
    its default ladder come from app.services.card_pirate_index_read. The same
    functions build the aggregate Index's window map, so a print's controls and
    the Index's controls cannot drift apart.
  * The SERIES shape - segments, breaks, gaps, reference_type/evidence_type,
    eligibility and per-series coverage - comes from
    app.services.print_series.build_print_series, unchanged. There is no second
    series DTO.
  * The COMPARABILITY rule behind `change` comes from
    app.services.market_index_change.comparability_refusal, which is the same
    guard list the shipped 7-day print change uses. There is no second
    definition of when two Market Index values may be compared.

IDENTITY IS `card_print_id`, ONLY. Nothing here reads, joins on, or falls back
to a card code: 955 of the catalogue's card codes carry more than one print and
one code carries nine, so a code is a family name, not a card. Nothing here
infers identity from treatment or artwork either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MarketIndexSnapshot, PriceObservation
from app.services.card_pirate_index_read import (
    WINDOW_DAYS,
    build_windows,
    resolve_default_window,
)
from app.services.market_index_change import (
    comparability_refusal,
    snapshot_source_values,
)
from app.services.print_series import build_print_series

# Why a change could not be published, beyond the comparability refusals
# app.services.market_index_change already names. Both of these are statements
# about the WINDOW's contents rather than about methodology.
CHANGE_UNAVAILABLE_NO_VALUE = "no_archived_value_in_window"
CHANGE_UNAVAILABLE_SINGLE_POINT = "single_point_window"

# The refusal a per-series change falls back to when the two ends sit in
# different segments but no break between them can be named. Structurally
# unreachable - segments are contiguous, so a boundary always has a break - and
# kept as a fail-closed default: an unnameable boundary must still refuse the
# comparison rather than publish one.
CHANGE_UNAVAILABLE_SEGMENT_BOUNDARY = "segment_boundary"

__all__ = [
    "CHANGE_UNAVAILABLE_NO_VALUE",
    "CHANGE_UNAVAILABLE_SEGMENT_BOUNDARY",
    "CHANGE_UNAVAILABLE_SINGLE_POINT",
    "WINDOW_TOKENS",
    "get_print_analytics",
    "is_supported_window",
]

# The public token set, in the frozen display order. Read off the Index's own
# map so the two can never disagree about either membership or order.
WINDOW_TOKENS: tuple[str, ...] = tuple(WINDOW_DAYS)


def is_supported_window(token: str) -> bool:
    return token in WINDOW_DAYS


def _naive_utc(value: datetime) -> datetime:
    """Comparable with the naive timestamps SQLite hands back, without moving
    an instant. Mirrors print_series._naive_utc."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _day_start(day: date) -> datetime:
    """Midnight UTC at the start of `day`, naive - the instant a window that
    begins on that calendar day begins at. Naive because every timestamp this
    module compares against arrives naive from SQLite."""
    return datetime.combine(day, time.min)


@dataclass(frozen=True)
class _Extent:
    """A historical span, as two calendar days or two nulls.

    TWO DIFFERENT EXTENTS ARE COMPUTED FROM THIS TYPE, and keeping them apart
    is the whole of this module's window policy - see `get_print_analytics`.
    One spans every series the print has and decides which timeframes are
    SELECTABLE; the other spans the Market Index alone and decides which
    timeframe the page OPENS on.
    """

    earliest: date | None
    latest: date | None


def _to_day(value: object) -> date | None:
    """A stored date or timestamp as a UTC calendar day. SQLite hands Date
    columns back as `date` and DateTime columns back naive; Postgres returns
    `date` and an aware datetime. Both are normalised here rather than at four
    call sites."""
    if isinstance(value, datetime):
        return _naive_utc(value).date()
    if isinstance(value, date):
        return value
    return None


def _snapshot_extent(
    snapshots: list[MarketIndexSnapshot], *, usable_only: bool
) -> _Extent:
    """The span of the archived Market Index rows already loaded.

    `usable_only` selects the rows carrying a real number. A day archived as
    NULL is a published result - "no source was eligible" - and it is part of
    the print's history for the purpose of drawing a chart, but it is NOT
    Market Index history for the purpose of deciding whether the Market Index
    can answer a three-month question. The default-window authority asks with
    `usable_only=True` for exactly that reason.
    """
    rows = [
        row
        for row in snapshots
        if not usable_only or row.index_value_jpy is not None
    ]
    days = [day for day in (_to_day(row.snapshot_date) for row in rows) if day]
    if not days:
        return _Extent(earliest=None, latest=None)
    return _Extent(earliest=min(days), latest=max(days))


def _chart_extent(
    db: Session, print_id: int, snapshots: list[MarketIndexSnapshot]
) -> _Extent:
    """The earliest and latest day this print has ANY archived history on -
    Market Index or any source.

    THIS DECIDES WHAT IS SELECTABLE, NOT WHAT OPENS. The window governs the
    whole chart, which carries Yuyu-Tei and SNKRDUNK beside the index, so a
    print with 32 days of Yuyu-Tei history and 9 days of index genuinely does
    have a month to show and marking 1M unavailable would hide real data the
    chart is about to draw. Which series reaches how far back is disclosed
    where it can be stated truthfully - in each series' own `coverage` block -
    rather than flattened into one bit that would have to lie about one series
    to be true about another.

    One aggregate query: the snapshot side reuses rows already in memory.
    """
    obs_lo, obs_hi = db.execute(
        select(
            func.min(PriceObservation.observed_at),
            func.max(PriceObservation.observed_at),
        ).where(PriceObservation.card_print_id == print_id)
    ).one()

    snapshot_span = _snapshot_extent(snapshots, usable_only=False)
    days = [
        day
        for day in (
            snapshot_span.earliest,
            snapshot_span.latest,
            _to_day(obs_lo),
            _to_day(obs_hi),
        )
        if day is not None
    ]
    if not days:
        return _Extent(earliest=None, latest=None)
    return _Extent(earliest=min(days), latest=max(days))


def _load_snapshots(db: Session, print_id: int) -> list[MarketIndexSnapshot]:
    """Every archived Market Index row for this print, oldest first.

    Read verbatim and never filtered by value: a NULL `index_value_jpy` is a
    published result ("no source was eligible that day") and the headline needs
    to see it in order to exclude it from a min/max without treating it as a
    zero.
    """
    return list(
        db.scalars(
            select(MarketIndexSnapshot)
            .where(MarketIndexSnapshot.card_print_id == print_id)
            .order_by(
                MarketIndexSnapshot.snapshot_date.asc(),
                MarketIndexSnapshot.id.asc(),
            )
        ).all()
    )


def _valued(
    snapshots: list[MarketIndexSnapshot],
) -> list[MarketIndexSnapshot]:
    """The snapshots carrying a real archived number.

    A null is dropped from every statistic rather than coerced: it is not a
    zero, not a low, and not a point the series should be measured between.
    """
    return [row for row in snapshots if row.index_value_jpy is not None]


def _change(
    start: MarketIndexSnapshot,
    end: MarketIndexSnapshot,
) -> tuple[dict | None, str | None]:
    """Change between the window's first and last archived values, or the
    reason there is none.

    NEVER A NAIVE FIRST-VS-LAST. The two ends are put through
    `comparability_refusal` - the same guards the shipped 7-day print change
    uses - so a window that crosses an index_version bump, a
    source_semantics_version bump, or a change in WHICH sources built the
    number yields no percentage and says which of those happened. That refusal
    is the whole point: reporting a methodology change as a price change is the
    specific failure this rule exists to prevent.

    `spans_break` is reported alongside a REFUSAL as well as alongside a
    number, because "the window contains a methodology boundary" is true either
    way; it is never used to license a comparison the guards declined.
    """
    spans_break = (
        start.index_version != end.index_version
        or start.source_semantics_version != end.source_semantics_version
    )

    refusal = comparability_refusal(
        baseline_value=start.index_value_jpy,
        baseline_index_version=start.index_version,
        baseline_source_semantics_version=start.source_semantics_version,
        baseline_source_values=snapshot_source_values(start),
        current_value=end.index_value_jpy,
        current_index_version=end.index_version,
        current_source_semantics_version=end.source_semantics_version,
        current_source_values=snapshot_source_values(end),
    )
    if refusal is not None:
        return None, refusal

    # Narrowed by the guards above; asserted for the type checker only.
    assert start.index_value_jpy is not None
    assert end.index_value_jpy is not None
    baseline = start.index_value_jpy
    current = end.index_value_jpy
    return (
        {
            "absolute_jpy": current - baseline,
            # Not rounded and not classified: the schema serialises a float and
            # the client decides how to present it. A genuine 0.0 is a
            # measurement - the index is where it started - and is published as
            # 0.0, never collapsed into the null that means "not comparable".
            "pct": ((current - baseline) / baseline) * 100.0,
            "from_date": start.snapshot_date,
            "to_date": end.snapshot_date,
            "spans_break": spans_break,
        },
        None,
    )


def _headline(snapshots: list[MarketIndexSnapshot]) -> dict:
    """The Card Pirate Market Index headline for one window.

    THE MARKET INDEX ONLY. Not Yuyu-Tei, not SNKRDUNK, not a blend of them:
    every figure below comes from `market_index_snapshots` rows, which are
    Atlas's own published values. The per-source story is told by the series
    beside this, where each platform keeps its own instrument and semantics.

    `observed_days` COUNTS DISTINCT HISTORICAL DAYS CARRYING A USABLE ARCHIVED
    MARKET INDEX VALUE. It is not sales, trades, volume, listings or a sample
    size, and Atlas holds no such figure for any source: nothing in this system
    records a transaction, `listing_count` is null on every stored observation
    and `sample_size` is null on every series point. A day is counted once
    however many times the collector ran.
    """
    valued = _valued(snapshots)
    if not valued:
        return {
            "current_value_jpy": None,
            "current_as_of": None,
            "starting_value_jpy": None,
            "starting_as_of": None,
            "low_value_jpy": None,
            "low_as_of": None,
            "high_value_jpy": None,
            "high_as_of": None,
            "change": None,
            "change_unavailable_reason": CHANGE_UNAVAILABLE_NO_VALUE,
            "observed_days": 0,
            # The newest archived row's own status, even when its value was
            # null: "no source was eligible" is a coverage answer worth
            # publishing, and dropping it would leave the panel unable to say
            # why there is no number.
            "coverage_status": snapshots[-1].coverage_status if snapshots else None,
        }

    start, end = valued[0], valued[-1]
    # `min`/`max` on the value, ties broken by the EARLIEST day: a price first
    # reached on the 3rd and matched on the 7th was reached on the 3rd, and
    # reporting the later date would misdate the event.
    low = min(valued, key=lambda row: (row.index_value_jpy, row.snapshot_date))
    high = max(
        valued,
        key=lambda row: (row.index_value_jpy, -row.snapshot_date.toordinal()),
    )

    if start is end:
        # One day of history is not a change. There is no second point to
        # measure against, and inventing a baseline from a neighbouring window
        # or another series is exactly what this module refuses to do.
        change, reason = None, CHANGE_UNAVAILABLE_SINGLE_POINT
    else:
        change, reason = _change(start, end)

    return {
        "current_value_jpy": end.index_value_jpy,
        "current_as_of": end.snapshot_date,
        "starting_value_jpy": start.index_value_jpy,
        "starting_as_of": start.snapshot_date,
        "low_value_jpy": low.index_value_jpy,
        "low_as_of": low.snapshot_date,
        "high_value_jpy": high.index_value_jpy,
        "high_as_of": high.snapshot_date,
        "change": change,
        "change_unavailable_reason": reason,
        "observed_days": len({row.snapshot_date for row in valued}),
        "coverage_status": end.coverage_status,
    }


def _plotted_points(series: dict) -> list[tuple[int, dict]]:
    """Every point of one series this chart can draw, tagged with its segment.

    THE SAME PLOTTABILITY RULE THE CHART USES, and the reason the rule lives
    with the points rather than with the caller: a statistic taken over a
    different set from the one on screen would be a number the reader cannot
    find on the plot. Two ways a point is not drawable, and neither is missing
    data:

      * `value_jpy is None` - an archived Market Index day on which no source
        was eligible. A recorded result, and never a zero, a low, or a point to
        measure between.
      * `eligible is False` - source semantics disqualified the reading (a
        platform-minimum listing, say). The number is real and stays in the
        payload for the tooltip; it is not a price this card traded at.

    The segment index travels with each point because it is what makes the
    change rule below break-aware without a second definition of "break".
    """
    out: list[tuple[int, dict]] = []
    for index, segment in enumerate(series.get("segments") or []):
        for point in segment.get("points") or []:
            if point.get("value_jpy") is None:
                continue
            if point.get("eligible") is False:
                continue
            out.append((index, point))
    return out


def _series_change(
    series: dict,
    plotted: list[tuple[int, dict]],
) -> tuple[dict | None, str | None]:
    """Movement between one series' first and last drawable points, or the
    reason there is none.

    BREAK-AWARENESS COMES FROM THE SHIPPED SEGMENTS, NOT A SECOND RULE. The
    series arrives already split wherever its measurement changed - by
    index_version and source_semantics_version for the Market Index, by
    reference_type/evidence_type for a source - and a break is recorded at
    every one of those boundaries. So the test is simply whether the two ends
    sit in the SAME segment. If they do not, the endpoints were taken under
    different methodologies or different instruments, and subtracting one from
    the other would report a definition change as a price movement.

    The refusal NAMES THE BOUNDARY, using the server's own break vocabulary
    (`index_version_change`, `source_semantics_version_change`,
    `reference_type_change`, `instrument_change`), so a client can explain the
    refusal rather than just report it.

    A PLAIN MISSING DAY IS NOT A BOUNDARY. A day Atlas simply did not record
    splits no segment and emits no break, so it neither refuses the comparison
    nor gets a point invented to fill it - the two real ends are compared and
    `observed_days` counts only the days that exist.
    """
    if len(plotted) == 1:
        return None, CHANGE_UNAVAILABLE_SINGLE_POINT

    (start_segment, start_point) = plotted[0]
    (end_segment, end_point) = plotted[-1]

    if start_segment != end_segment:
        reason = _boundary_reason(series, start_point, end_point)
        return None, reason

    baseline = start_point["value_jpy"]
    current = end_point["value_jpy"]
    if baseline is None or current is None or baseline <= 0:
        # A non-positive baseline cannot carry a percentage, and the shipped
        # index guard refuses the same case rather than dividing by it.
        return None, CHANGE_UNAVAILABLE_SEGMENT_BOUNDARY if baseline is None else "non_positive_baseline"

    return (
        {
            "absolute_jpy": current - baseline,
            # Not rounded and not classified - the schema serialises a float
            # and the client decides how to present it, exactly as the headline
            # change does. A genuine 0.0 is a measurement (the series is where
            # it started) and is published as 0.0, never collapsed into the
            # null that means "not comparable".
            "pct": ((current - baseline) / baseline) * 100.0,
            "from_date": start_point["day"],
            "to_date": end_point["day"],
            # Structurally False whenever a change is published: same-segment
            # ends have no boundary between them. Computed rather than
            # hardcoded so a segmentation bug shows up here instead of being
            # asserted away.
            "spans_break": _spans_break(series, start_point, end_point),
        },
        None,
    )


def _boundary_reason(series: dict, start_point: dict, end_point: dict) -> str:
    """Which boundary made the two ends incomparable, in the server's own
    break vocabulary.

    The EARLIEST break between them, because that is the first thing that
    changed and the one a reader is being told about. A day on which two
    fields moved emits one break per field, and taking the earliest keeps this
    deterministic rather than dependent on emission order.
    """
    between = [
        entry
        for entry in (series.get("breaks") or [])
        if start_point["t"] < entry["at"] <= end_point["t"]
    ]
    if not between:
        return CHANGE_UNAVAILABLE_SEGMENT_BOUNDARY
    return min(between, key=lambda entry: entry["at"])["reason"]


def _spans_break(series: dict, start_point: dict, end_point: dict) -> bool:
    return any(
        start_point["t"] < entry["at"] <= end_point["t"]
        for entry in (series.get("breaks") or [])
    )


def _series_stats(series_payload: list[dict], headline: dict) -> list[dict]:
    """One summary per series the chart actually draws.

    WHY THIS IS BUILT FROM THE SERIES PAYLOAD AND NOT FROM A SECOND QUERY. The
    invariant that matters is that every figure here can be found on the plot
    beside it, and the only way to guarantee that is to compute it from the
    very objects the plot is drawn from. A parallel query would be a second
    definition of the window, of plottability and of ordering, free to disagree
    with the first.

    NOTHING IS RESOLVED, RECOMPUTED, AVERAGED, INTERPOLATED OR FORWARD-FILLED.
    Every published number is an integer JPY value lifted from one archived
    observation, and every date is that observation's own day. There is no mean
    anywhere: the only combination rule Atlas owns is a same-day median across
    sources, so an average over time would be inventing methodology.

    A SERIES WITH NOTHING DRAWABLE GETS NO ROW. An unconfigured platform, a
    platform with no history in this window, and a platform whose every reading
    was disqualified all produce no entry rather than a row of nulls - a
    zero-filled summary would assert a measurement that was never taken. This
    is also why the list is not keyed by a fixed set of platform names.

    THE MARKET INDEX DEFERS TO THE HEADLINE FOR ITS CHANGE. The headline is the
    same archived series over the same window, and it applies one guard this
    payload cannot see: whether the SET OF SOURCES behind the number changed
    between the two ends (`market_index_snapshots` carries the contributors;
    the series points do not). Publishing a movement here that the headline
    refuses would put two contradictory answers about one number on one page,
    so the segment test below runs first and the headline's verdict is applied
    on top of it. Neither can license what the other declined.
    """
    stats: list[dict] = []
    for series in series_payload:
        plotted = _plotted_points(series)
        if not plotted:
            continue

        points = [point for _, point in plotted]
        # Earliest occurrence on a tie, for both ends of the range: `min`/`max`
        # over an already date-ordered list return the FIRST extreme they meet,
        # which is the rule stated in the contract.
        low = min(points, key=lambda point: point["value_jpy"])
        high = max(points, key=lambda point: point["value_jpy"])

        change, reason = _series_change(series, plotted)
        if series.get("key") == "market_index" and change is not None:
            # The headline's own verdict, applied on top - see above.
            change, reason = headline.get("change"), headline.get(
                "change_unavailable_reason"
            )

        stats.append(
            {
                "series_key": series["key"],
                "kind": series["kind"],
                "source": series.get("source"),
                "starting_value_jpy": points[0]["value_jpy"],
                "starting_as_of": points[0]["day"],
                "current_value_jpy": points[-1]["value_jpy"],
                "current_as_of": points[-1]["day"],
                "low_value_jpy": low["value_jpy"],
                "low_as_of": low["day"],
                "high_value_jpy": high["value_jpy"],
                "high_as_of": high["day"],
                # DISTINCT DRAWABLE DAYS. Not sales, trades, volume, listings
                # or a sample size - Atlas records no transaction anywhere, and
                # holds no such figure for any source.
                "observed_days": len({point["day"] for point in points}),
                "change": change,
                "change_unavailable_reason": reason,
            }
        )
    return stats


def get_print_analytics(
    db: Session,
    print_id: int,
    *,
    window: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Everything the exact-print analytics page needs, in one response.

    ONE REQUEST, NOT THREE. The windows map, the headline and every platform
    series are assembled together because they must agree with each other: a
    client that fetched them separately could render a headline from one window
    beside a chart from another, and would have to re-derive availability that
    the server is the only honest authority on.

    THE WINDOW IS ANCHORED ON THE PRINT'S NEWEST HISTORY, NOT ON THE WALL
    CLOCK - the same rule the aggregate Index applies. A reader asking for 1M
    wants a month of the history that exists; anchoring on today would silently
    empty the window the moment collection paused, which is a worse answer than
    "here is what there is".

    AN UNAVAILABLE WINDOW IS ANSWERED, NOT SUBSTITUTED. A valid token whose
    span the print's history does not reach comes back as itself in
    `requested_window`, with `windows[]` reporting `available: false` and the
    real (possibly empty) data for that span. Quietly serving a different
    token's data under the requested name would make the control lie about what
    the reader is looking at.

    WHAT IS SELECTABLE AND WHAT OPENS ARE TWO DIFFERENT QUESTIONS, ANSWERED BY
    TWO DIFFERENT EXTENTS. They are deliberately not the same authority:

      * `windows[].available` spans EVERY series. The chart draws Yuyu-Tei and
        SNKRDUNK beside the index, so a print with three months of Yuyu-Tei
        history really can fill a 3M chart and the control must let a reader
        ask for it.
      * `default_window` spans the MARKET INDEX alone, and only its usable
        (non-null) days. The view the page opens on is the primary performance
        view, and every figure in it - current, starting, low, high, change -
        is a Market Index figure. Letting a long source-only history open the
        page on 3M would put a three-month frame around a headline the Market
        Index cannot fill, which is precisely the misleading pairing the
        per-series coverage exists to prevent.

    So a print with 3M of Yuyu-Tei and 9 days of index reports `3m` AVAILABLE
    and `default_window: "all"`. That combination is intended, not an
    inconsistency: the reader may go to 3M, and is simply not started there.
    A Market Index with no usable history yields `all` by the same rule, since
    an absent index satisfies no threshold.
    """
    now = _naive_utc(now or datetime.now(timezone.utc))

    # Loaded once, unfiltered: the extents below are measured from these rows,
    # and the window they decide is applied afterwards.
    all_snapshots = _load_snapshots(db, print_id)

    chart_extent = _chart_extent(db, print_id, all_snapshots)
    anchor = chart_extent.latest
    windows = build_windows(available_from=chart_extent.earliest, anchor=anchor)

    # THE DEFAULT'S OWN AUTHORITY. A separate map, built by the same function
    # from the Market Index's own usable span and anchored on the Market
    # Index's own newest day, so "3m" here means "the Market Index itself
    # reaches back three months" rather than "something on this page does".
    # This map decides the default and is never published - `windows[]` above
    # is what the control renders.
    index_extent = _snapshot_extent(all_snapshots, usable_only=True)
    default_window = resolve_default_window(
        build_windows(
            available_from=index_extent.earliest, anchor=index_extent.latest
        )
    )

    # The ONE place a request with no window acquires one, so an implicit
    # request and an explicit request for the same token are indistinguishable
    # in the payload.
    token = window or default_window
    days = WINDOW_DAYS[token]

    window_start_day = None if (days is None or anchor is None) else anchor - timedelta(days=days)
    start = None if window_start_day is None else _day_start(window_start_day)

    snapshots = [
        row
        for row in all_snapshots
        if window_start_day is None or row.snapshot_date >= window_start_day
    ]

    headline = _headline(snapshots)
    # The shipped series builder, over exactly this window. Segments, breaks,
    # gaps, instrument semantics, eligibility and per-series coverage all
    # arrive as `/prints/{id}/series` produces them - and the payload below is
    # handed to the stats builder UNCHANGED, so `series` is byte-for-byte what
    # it was before this field existed.
    series_payload = build_print_series(
        db,
        print_id,
        start=start,
        window_days=days,
        now=now,
    )

    return {
        "card_print_id": print_id,
        "requested_window": token,
        "window_start": window_start_day,
        "default_window": default_window,
        "generated_at": now,
        "windows": [
            {
                "token": row.token,
                "available": row.available,
                "covered_days": row.covered_days,
                "required_days": row.required_days,
            }
            for row in windows
        ],
        "headline": headline,
        "series": series_payload,
        # Derived from `series_payload` above and from nothing else, so every
        # figure here is findable on the plot beside it.
        "series_stats": _series_stats(series_payload, headline),
    }
