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
# history exist, then `3m`. This module serves the API's own default, which the
# route declares; the surface-level ladder is a frontend concern and is not
# decided here.
DEFAULT_WINDOW = "3m"


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


class UnknownWindowError(ValueError):
    """A window token outside the published grammar."""


def resolve_window(window: str | None) -> str:
    """Normalise a window token, or refuse it.

    `None` means "not supplied" and takes the default. An empty string means
    the caller DID supply a window and supplied nothing usable, which is a
    client error rather than a silent fallback. Case and surrounding
    whitespace are normalised away: the grammar is a closed vocabulary, so
    `1M` and `1m` cannot mean different things and rejecting one would be
    pedantry rather than safety.
    """
    if window is None:
        return DEFAULT_WINDOW
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
    """
    token = resolve_window(window)
    days = WINDOW_DAYS[token]

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
        return IndexSeriesOut(
            scope_kind=scope_kind, scope_key=scope_key,
            methodology_version=methodology_version,
            index_version=None, source_semantics_version=None,
            requested_window=token, window_start=None,
            available_from=None, available_to=None,
            covers_requested_window=False, points=(),
            starting_value=None, current_value=None,
            low_value=None, high_value=None, change=None,
            change_unavailable_reason="no_published_point_in_window",
        )

    available_from, available_to = extent[0], extent[-1]

    # The window is measured back from the newest PUBLISHED day, not from the
    # wall clock. A reader asking for "3m" wants three months of the series
    # that exists; anchoring on today would silently empty the window the
    # moment the writer paused, which is a different and much worse answer
    # than "here is what there is".
    anchor = today or available_to
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
    )


__all__ = [
    "DEFAULT_WINDOW",
    "IndexPointOut",
    "IndexSeriesOut",
    "UnknownWindowError",
    "WINDOW_DAYS",
    "get_index_series",
    "resolve_window",
]
