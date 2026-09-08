"""Read the PERSISTED Card Pirate Index. No estimator, no writes.

This module serves `card_pirate_index_points` and nothing else. It never
recomputes a level, never touches `market_index_snapshots`, and never writes.
The distinction matters: `card_pirate_index_replay` exists to CONSTRUCT the
series from the archive, and if this module recomputed anything there would be
two answers to "what is the index on 2026-09-04" - the one that was published
and the one a reader happened to derive. There is one, and it is the stored
row.

WHY CHANGE IS NOT COMPUTED HERE
--------------------------------
Percentage and absolute change are delegated verbatim to
`card_pirate_index.compute_change`, which implements section 5.6 of the frozen
methodology - endpoint resolution, the carried/reset distinction,
`spans_break`, and the rule that a span with no carried continuity returns
None rather than a spliced number. Re-deriving `(last / first - 1) * 100` here
would look identical today and would silently disagree the first time a reset
appears in the archive. Stored rows are lifted into `PointDraft` purely so
that one frozen function can be reused unchanged.

WHAT IS DELIBERATELY NOT SERVED
--------------------------------
`average_value` is absent. The methodology defines no mean level, and one
cannot be added here without inventing a convention: an unweighted mean over
points and a step_days-weighted mean over time give different numbers the
moment a snapshot gap exists, and nothing in the document says which is meant.
Publishing either would create exactly the second definition this module's
change delegation exists to avoid. `low_value`/`high_value` are served because
a minimum and a maximum of the published levels need no convention at all.

Surrogate ids never leave this module. `id` and `carried_from_point_id` are
not reproducible across a rebuild, so the payload carries dates; the carry is
resolved to its target's `point_date` by join, exactly as the replay module's
contract requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.services.card_pirate_index import (
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    ChangeResult,
    PointDraft,
    compute_change,
)

# The published window grammar (methodology section 12). `all` is not a
# duration, so it maps to None rather than to a very large number of days -
# "everything there is" and "the last 7300 days" are different questions and
# only one of them stays correct.
WINDOW_DAYS: dict[str, int | None] = {
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "all": None,
}

# Section 13.1 freezes the ANALYTICS default as `all` until three months of
# history exist, then `3m` - and that ladder is decided HERE, once, for every
# caller. It is not a frontend concern: section 13.1 rule 4 forbids a client
# re-deriving it, and rule 3 makes an absent `?window=` the way a client asks
# for it.
#
# Section 13.1's two rungs, named so `resolve_default_window` reads as the rule
# rather than as two string literals.
#
# THERE IS NO SEPARATE TRANSPORT DEFAULT ANY MORE. Until TASK INDEX 2A-C this
# module also exported `DEFAULT_WINDOW = "3m"`, which the route used as the
# `?window=` fallback - so a request with no window meant `3m` while the
# *published* `default_window` meant `all`, and a client that wanted the
# product default had to know that and ask for something else. Two notions of
# "default" for one endpoint is one too many; a request with no window now
# resolves through `resolve_default_window` like everything else.
PREFERRED_DEFAULT_WINDOW = "3m"
FALLBACK_DEFAULT_WINDOW = "all"


@dataclass(frozen=True)
class IndexPointOut:
    point_date: date
    index_value: Decimal
    is_base: bool
    prior_point_date: date | None
    step_days: int | None
    chain_link_log_return: Decimal | None
    constituent_count: int
    eligible_print_count: int
    movers_up: int | None
    movers_down: int | None
    movers_flat: int | None
    capped_count: int | None


@dataclass(frozen=True)
class WindowAvailability:
    """One row of the section 12.1 `windows` map.

    Section 12.2 rule 3 calls this map "the key affordance": it is what lets a
    frontend render 2W/1M/3M/6M/1Y/2Y as disabled buttons with a reason rather
    than as clickable paths into a misleading chart. Rule 4 fixes what
    `available` means, and it is a SPAN test, not a point count -
    `coverage.earliest <= window_start`, matching the existing
    `covers_7d`/`covers_30d` definition. Sparse history that spans a window
    still covers it; gaps stay gaps. Rule 5 adds that a break never makes a
    window unavailable, because the level series is continuous across segments.
    """

    token: str
    available: bool
    covered_days: int
    required_days: int | None


@dataclass(frozen=True)
class IndexBreak:
    """One boundary in the returned series - section 12.1's `breaks` entry.

    DERIVED FROM THE PERSISTED ROWS, never from chart geometry. Each stored
    point carries its own `methodology_version`, `index_version`,
    `source_semantics_version`, `carried_from_point_id` and `step_days`, so a
    boundary is a fact about two adjacent rows and is decided here, once, on
    the server. A client comparing pixel positions or point dates would be
    re-deriving a methodology question from a drawing.

    The two kinds mean different things and section 13.4 renders them
    differently. A version change is CONTINUOUS - the level really does carry
    across it (section 5.1 rule 4), so the line is solid through the boundary
    and a marker names what changed. A `snapshot_gap` is genuinely missing
    data, so the join is dashed. Accordingly a `snapshot_gap` carries neither
    `carried` nor `carried_level`: it is a cadence fact, not a methodology one.

    `carried: false` on a version boundary marks a RESET - a segment that
    opened at the base with no carry - and that is what makes section 5.6
    rule 5 withhold a change figure across it.
    """

    at: date
    reason: str
    from_methodology_version: int | None = None
    to_methodology_version: int | None = None
    from_index_version: int | None = None
    to_index_version: int | None = None
    from_source_semantics_version: int | None = None
    to_source_semantics_version: int | None = None
    carried: bool | None = None
    carried_level: Decimal | None = None
    carried_from_point_date: date | None = None
    prior_point_date: date | None = None
    step_days: int | None = None


@dataclass(frozen=True)
class IndexSeriesOut:
    scope_kind: str
    scope_key: str
    methodology_version: int
    index_version: int | None
    source_semantics_version: int | None
    requested_window: str
    window_start: date | None
    available_from: date | None
    available_to: date | None
    covers_requested_window: bool
    points: tuple[IndexPointOut, ...]
    starting_value: Decimal | None
    current_value: Decimal | None
    low_value: Decimal | None
    high_value: Decimal | None
    change: ChangeResult | None
    change_unavailable_reason: str | None
    # --- section 12.1 server-authored metadata, added by TASK INDEX 2A-B ---
    # Appended rather than woven in, so every existing field keeps its meaning
    # and its position in the payload.
    windows: tuple[WindowAvailability, ...] = ()
    default_window: str = FALLBACK_DEFAULT_WINDOW
    breaks: tuple[IndexBreak, ...] = ()


class UnknownWindowError(ValueError):
    """A window token outside the published grammar."""


def resolve_window(window: str | None) -> str | None:
    """Normalise a supplied window token, or refuse it.

    `None` in means `None` out: "the caller supplied no window", which is a
    question this function cannot answer. It used to answer it - with `3m` -
    and that was the second notion of default TASK INDEX 2A-C removed. Which
    window an unsupplied request means is section 13.1's rule, it depends on
    how much history exists, and it is decided in `get_index_series` where the
    extent is known.

    An empty string is NOT the same as absence: the caller DID supply a window
    and supplied nothing usable, which is a client error rather than a silent
    fallback. Case and surrounding whitespace are normalised away, because the
    grammar is a closed vocabulary and `1M` and `1m` cannot mean different
    things.
    """
    if window is None:
        return None
    token = window.strip().lower()
    if token not in WINDOW_DAYS:
        raise UnknownWindowError(
            f"unknown window {window!r}; expected one of "
            f"{', '.join(sorted(WINDOW_DAYS))}"
        )
    return token


def _to_draft(row, carried_from: date | None) -> PointDraft:
    """A stored row as the estimator's own value object.

    Lifting rather than re-implementing is the whole point: `compute_change`
    then works on persisted history without a second copy of section 5.6's
    rules living in the read path.
    """
    return PointDraft(
        scope_kind=row.scope_kind,
        scope_key=row.scope_key,
        methodology_version=row.methodology_version,
        index_version=row.index_version,
        source_semantics_version=row.source_semantics_version,
        point_date=row.point_date,
        index_value=row.index_value,
        is_base=row.is_base,
        carried_from_key=carried_from,
        prior_point_date=row.prior_point_date,
        step_days=row.step_days,
        chain_link_log_return=row.chain_link_log_return,
        constituent_count=row.constituent_count,
        eligible_print_count=row.eligible_print_count,
        movers_up=row.movers_up,
        movers_down=row.movers_down,
        movers_flat=row.movers_flat,
        capped_count=row.capped_count,
        unpublishable_reason=row.unpublishable_reason,
    )


def build_windows(
    *,
    available_from: date | None,
    anchor: date | None,
) -> tuple[WindowAvailability, ...]:
    """The section 12.1 `windows` map, in the frozen order of the grammar.

    A tuple rather than a dict because ORDER IS PART OF THE CONTRACT: the
    control renders 2W/1M/3M/6M/1Y/2Y/All left to right, and a client that had
    to re-impose that order from a bare mapping would be re-deciding a display
    rule the document already froze. `WINDOW_DAYS` is the single source of both
    the token set and the order.

    `covered_days` is a SPAN, inclusive, from the later of `available_from` and
    the window start through the newest published day - the same measure
    `available` tests, so the two can never disagree. It is deliberately not a
    point count: section 12.2 rule 4 says sparse history that spans a window
    still covers it, and a count would report a four-point year as four days.
    """
    rows: list[WindowAvailability] = []
    for token, days in WINDOW_DAYS.items():
        if available_from is None or anchor is None:
            rows.append(WindowAvailability(token, False, 0, days))
            continue
        if days is None:
            # `all` asks for no span at all, so it is covered by definition -
            # section 12.1's own example has it available on four days of data.
            start = available_from
            available = True
        else:
            start = anchor - timedelta(days=days)
            available = available_from <= start
        covered_from = max(available_from, start)
        covered = (anchor - covered_from).days + 1 if anchor >= covered_from else 0
        rows.append(WindowAvailability(token, available, covered, days))
    return tuple(rows)


def resolve_default_window(windows: tuple[WindowAvailability, ...]) -> str:
    """Section 13.1's ladder, decided on the server so one rule exists.

    "`All` is the default while less than 3 months of history exists. Once 3M
    is available (`windows["3m"].available == true`), 3M becomes the default."
    That is the whole rule, and it is read off the map built above rather than
    from dates, so the published `default_window` can never disagree with the
    published availability beside it.
    """
    for row in windows:
        if row.token == PREFERRED_DEFAULT_WINDOW and row.available:
            return PREFERRED_DEFAULT_WINDOW
    return FALLBACK_DEFAULT_WINDOW


def build_breaks(rows: list) -> tuple[IndexBreak, ...]:
    """Boundaries between adjacent PERSISTED rows, in ascending date order.

    Four reasons, all read off the stored columns:

      `methodology_version_change`        the ruleset that produced the level
      `index_version_change`              changed. The level is continuous
      `source_semantics_version_change`   across it (section 5.1 rule 4), so
                                          section 13.4 draws the line straight
                                          through and marks the date.
      `snapshot_gap`                      `step_days > 1`: the archive holds
                                          nothing in between, so 13.4 dashes
                                          the join and names the missing days.

    A single response is filtered to one `methodology_version` by
    `get_index_series`'s scope filter, so `methodology_version_change` cannot
    currently arise within one payload. The branch exists anyway rather than
    being asserted away: the filter is a query decision, and a break kind that
    silently disappeared if it were relaxed would be a trap rather than a
    simplification.

    Version changes are emitted before a gap for the same date, because a
    boundary that is both is first a methodology fact and second a cadence one.
    """
    breaks: list[IndexBreak] = []
    for prev_row, cur_row in zip(rows, rows[1:]):
        prev, cur = prev_row[0], cur_row[0]
        # The carry is what makes a version boundary continuous. `carried:
        # False` is a RESET, and section 5.6 rule 5 is what withholds a change
        # figure across one - so it is published, not inferred from the level.
        carried = cur.carried_from_point_id is not None
        for reason, before, after in (
            ("methodology_version_change", prev.methodology_version, cur.methodology_version),
            ("index_version_change", prev.index_version, cur.index_version),
            (
                "source_semantics_version_change",
                prev.source_semantics_version,
                cur.source_semantics_version,
            ),
        ):
            if before == after:
                continue
            fields: dict = {
                "at": cur.point_date,
                "reason": reason,
                "carried": carried,
                # Section 5.1 rule 4: the level is continuous across a carry,
                # so the new segment's own level IS the level that was carried.
                # Read from the row rather than joined back to the target,
                # which may sit outside the requested window.
                "carried_level": cur.index_value if carried else None,
                "carried_from_point_date": cur_row[1],
                "prior_point_date": prev.point_date,
            }
            if reason == "methodology_version_change":
                fields["from_methodology_version"] = before
                fields["to_methodology_version"] = after
            elif reason == "index_version_change":
                fields["from_index_version"] = before
                fields["to_index_version"] = after
            else:
                fields["from_source_semantics_version"] = before
                fields["to_source_semantics_version"] = after
            breaks.append(IndexBreak(**fields))

        if cur.step_days is not None and cur.step_days > 1:
            breaks.append(
                IndexBreak(
                    at=cur.point_date,
                    reason="snapshot_gap",
                    prior_point_date=prev.point_date,
                    step_days=cur.step_days,
                )
            )
    return tuple(breaks)


def get_index_series(
    db: Session,
    *,
    window: str | None = None,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    methodology_version: int = METHODOLOGY_VERSION,
    today: date | None = None,
) -> IndexSeriesOut:
    """The published series for one scope over one window.

    Reads `card_pirate_index_points` only. A window narrows which stored rows
    are returned; it never invents a point outside the archive, pads the axis,
    forward-fills a gap or recomputes a level. A request reaching further back
    than the history goes is answered with the history that exists, and
    `covers_requested_window` says so rather than the response pretending.

    `window=None` means the caller supplied none, and is answered with the
    SERVER'S OWN `default_window` - section 13.1's ladder, resolved below once
    the extent is known. It is not a synonym for any particular token: on a
    short archive it is `all`, and it becomes `3m` the day three months of
    history exists, with no client change and no second request. Everything
    downstream - `requested_window`, `window_start`, `covers_requested_window`,
    the points, the change - then describes the window actually selected, so an
    implicit request and the explicit request for the same token return
    identical payloads.
    """
    # Validation happens here, on the supplied value, so an explicit bad token
    # is still a 400 - the deferral below is about which window an ABSENT one
    # means, never about whether a present one is legal.
    token = resolve_window(window)

    target = aliased(CardPirateIndexPoint)
    scope_filter = (
        CardPirateIndexPoint.scope_kind == scope_kind,
        CardPirateIndexPoint.scope_key == scope_key,
        CardPirateIndexPoint.methodology_version == methodology_version,
    )

    # The full published extent of the scope, independent of the window - what
    # `available_from`/`available_to` report, and what decides whether the
    # requested window is actually covered.
    extent = db.execute(
        select(
            CardPirateIndexPoint.point_date,
        )
        .where(*scope_filter, CardPirateIndexPoint.index_value.is_not(None))
        .order_by(CardPirateIndexPoint.point_date)
    ).scalars().all()

    if not extent:
        # Still publishes the full window grammar and a default. A client that
        # got an empty map here would have nothing to render its control from
        # and would fall back to a hardcoded list - which is the frontend
        # re-owning the token set this endpoint exists to own.
        empty_windows = build_windows(available_from=None, anchor=None)
        empty_default = resolve_default_window(empty_windows)
        return IndexSeriesOut(
            scope_kind=scope_kind, scope_key=scope_key,
            methodology_version=methodology_version,
            index_version=None, source_semantics_version=None,
            requested_window=token or empty_default, window_start=None,
            available_from=None, available_to=None,
            covers_requested_window=False, points=(),
            starting_value=None, current_value=None,
            low_value=None, high_value=None, change=None,
            change_unavailable_reason="no_published_point_in_window",
            windows=empty_windows,
            default_window=empty_default,
            breaks=(),
        )

    available_from, available_to = extent[0], extent[-1]

    # The window is measured back from the newest PUBLISHED day, not from the
    # wall clock. A reader asking for "3m" wants three months of the series
    # that exists; anchoring on today would silently empty the window the
    # moment the writer paused, which is a different and much worse answer
    # than "here is what there is".
    anchor = today or available_to

    # Built from the extent and the same anchor, so every row of the map
    # answers the same question `covers_requested_window` below answers, and
    # the two can never disagree for the window that was actually requested.
    windows = build_windows(available_from=available_from, anchor=anchor)
    default_window = resolve_default_window(windows)

    # The ONE place a request with no window acquires one. Nothing above this
    # line knows a token, and nothing below it can tell an implicit request
    # from the explicit request for the same window - which is the point: the
    # two must be indistinguishable in the payload.
    token = token or default_window
    days = WINDOW_DAYS[token]
    window_start = None if days is None else anchor - timedelta(days=days)

    # LEFT JOIN so the carry resolves to its target's DATE. The surrogate id
    # never leaves this query.
    stmt = (
        select(CardPirateIndexPoint, target.point_date.label("carried_from_date"))
        .join(target, CardPirateIndexPoint.carried_from_point_id == target.id,
              isouter=True)
        .where(*scope_filter, CardPirateIndexPoint.index_value.is_not(None))
        .order_by(CardPirateIndexPoint.point_date)
    )
    if window_start is not None:
        stmt = stmt.where(CardPirateIndexPoint.point_date >= window_start)

    rows = db.execute(stmt).all()
    drafts = [_to_draft(r[0], r[1]) for r in rows]
    points = tuple(
        IndexPointOut(
            point_date=r[0].point_date,
            index_value=r[0].index_value,
            is_base=r[0].is_base,
            prior_point_date=r[0].prior_point_date,
            step_days=r[0].step_days,
            chain_link_log_return=r[0].chain_link_log_return,
            constituent_count=r[0].constituent_count,
            eligible_print_count=r[0].eligible_print_count,
            movers_up=r[0].movers_up,
            movers_down=r[0].movers_down,
            movers_flat=r[0].movers_flat,
            capped_count=r[0].capped_count,
        )
        for r in rows
    )

    if not points:
        return IndexSeriesOut(
            scope_kind=scope_kind, scope_key=scope_key,
            methodology_version=methodology_version,
            index_version=None, source_semantics_version=None,
            requested_window=token, window_start=window_start,
            available_from=available_from, available_to=available_to,
            covers_requested_window=False, points=(),
            starting_value=None, current_value=None,
            low_value=None, high_value=None, change=None,
            change_unavailable_reason="no_published_point_in_window",
            windows=windows, default_window=default_window, breaks=(),
        )

    # Section 5.6, delegated verbatim - never re-derived here.
    change = compute_change(drafts, window_start=window_start)

    values = [p.index_value for p in points]
    latest = rows[-1][0]
    return IndexSeriesOut(
        scope_kind=scope_kind,
        scope_key=scope_key,
        methodology_version=methodology_version,
        # Carried from the newest published point: the versions that produced
        # the number a reader is looking at, not a constant re-read from the
        # code, which could describe a ruleset the row never used.
        index_version=latest.index_version,
        source_semantics_version=latest.source_semantics_version,
        requested_window=token,
        window_start=window_start,
        available_from=available_from,
        available_to=available_to,
        covers_requested_window=(
            True if window_start is None else available_from <= window_start
        ),
        points=points,
        starting_value=points[0].index_value,
        current_value=points[-1].index_value,
        low_value=min(values),
        high_value=max(values),
        change=change if change.unavailable_reason is None else None,
        change_unavailable_reason=change.unavailable_reason,
        windows=windows,
        default_window=default_window,
        # Over the RETURNED rows, because `breaks` describes the series this
        # payload actually draws. A boundary older than `window_start` is not
        # part of the chart the client is about to render, and publishing it
        # would put a marker on a date the axis does not contain.
        breaks=build_breaks(rows),
    )


__all__ = [
    "FALLBACK_DEFAULT_WINDOW",
    "IndexBreak",
    "PREFERRED_DEFAULT_WINDOW",
    "WindowAvailability",
    "build_breaks",
    "build_windows",
    "resolve_default_window",
    "IndexPointOut",
    "IndexSeriesOut",
    "UnknownWindowError",
    "WINDOW_DAYS",
    "get_index_series",
    "resolve_window",
]
