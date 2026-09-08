"""What moved the Card Pirate Index on one published day.

READ-ONLY, ARCHIVE-ONLY, AND ARITHMETIC-FREE ABOUT PRICING. Every JPY value
here is an archived `market_index_snapshots.index_value_jpy` read as stored.
Nothing calls the live resolver, recomputes a Market Index, reads
`price_observations`, or substitutes a present-day price. The only arithmetic
this module performs is the frozen estimator's own: a log ratio, the
unconditional cap, and a division by n.

TWO RANKINGS, BECAUSE THERE ARE TWO QUESTIONS
---------------------------------------------
On 2026-09-07 the archive holds the case that makes this non-negotiable.
OP01-047 fell 41.18 % and ST01-007 fell 25.00 %; both exceed the methodology's
unconditional +/-25 % daily cap, so both entered the index at exactly
-ln(1.25). By raw move one is a far bigger loser than the other. By index
contribution they are EXACTLY TIED. A single ranking would have to discard one
of those two true statements, so `move_rank` and `impact_rank` are both
computed here, on the server, and the client sorts nothing.

The same day shows it from the other side: OP01-016 rose 23.33 %, just under
the cap, so it was not capped at all - and it therefore contributes MORE than
either of the two larger falls did, in magnitude terms it sits between them.
Raw order and impact order are genuinely different orders.

WHY `contribution_log_return` IS THE CANONICAL FIELD
----------------------------------------------------
Every constituent carries exactly 1/n of the step (section 2.1's plain
arithmetic mean), so `capped / n` is the quantity that literally entered the
published number. Summed over the whole constituent set it equals
`chain_link_log_return` to the last digit - which is asserted here at runtime,
not merely hoped for. `approx_index_points` is a rendering of it and is
documented as such below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical_card import CanonicalCard
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.card_print import CardPrint
from app.services.card_pirate_index import (
    CAP_RATIO,
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    ConstituentObservation,
    SnapshotDay,
    constituent_print_ids,
)
from app.services.card_pirate_index_replay import load_snapshot_days
from app.services.display_image import get_display_images_for_prints
from app.services.print_catalogue import effective_rarity_sql
from app.services.rarity_facets import facet_value

# The estimator's own working precision, imported rather than restated so the
# cap and the returns are computed in the same context the writer used.
from app.services.card_pirate_index import _WORKING_PRECISION  # noqa: PLC2701

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_FLAT = "flat"

# How many mover rows the payload will carry. The integrity arithmetic below
# always runs over the FULL constituent set; this bounds only what is
# serialised, so a day on which most of 296 constituents move cannot turn one
# analytics panel into a several-hundred-row response.
MAX_MOVERS = 20

_PCT_PLACES = Decimal("0.01")
_POINTS_PLACES = Decimal("0.0001")
_LOG_PLACES = Decimal("0.000000000001")
# What the WIRE carries for a log-space field. The estimator works at 40+
# significant digits, and serialising that raw put a 43-digit string in the
# payload for a number whose published step is quoted to twelve places.
#
# Eighteen places is chosen, not rounded to taste: the reconciliation the
# contract promises is that the movers' contributions sum to
# `chain_link_log_return`, which is stored at twelve places. Rounding each of
# at most `MAX_MOVERS` contributions to eighteen places can move their sum by
# at most 20 x 5e-19 = 1e-17, six orders of magnitude below the twelfth place,
# so the sum still lands on the published value exactly. The integrity guard
# above deliberately runs on the UNROUNDED values - it checks the arithmetic,
# not the formatting.
_WIRE_PLACES = Decimal("0.000000000000000001")


class MoversIntegrityError(RuntimeError):
    """The reconstruction contradicts the published point.

    FAIL CLOSED, for the same reason the composition route does: this module
    re-derives from `market_index_snapshots` what the writer derived from those
    same rows, and the two agreeing is the entire basis for deriving at read
    time rather than persisting. A movers list whose constituents sum to a
    different step than the index published is not a degraded answer, it is a
    contradiction, and the endpoint publishes neither half of it.
    """


@dataclass(frozen=True)
class Mover:
    card_print_id: int
    card_code: str | None
    name: str | None
    rarity: str | None
    display_image_url: str | None
    treatment: str | None
    language: str | None
    prior_value_jpy: int
    current_value_jpy: int
    direction: str
    raw_pct: Decimal
    capped_log_return: Decimal
    was_capped: bool
    contribution_log_return: Decimal
    approx_index_points: Decimal
    move_rank: int
    impact_rank: int


@dataclass(frozen=True)
class IndexMoversOut:
    as_of: date
    prior_point_date: date | None
    constituent_count: int
    movers_count: int
    unchanged_count: int
    chain_link_log_return: Decimal | None
    movers: tuple[Mover, ...]
    truncated: bool


@dataclass(frozen=True)
class _Raw:
    """One constituent's arithmetic, before identity is attached."""

    card_print_id: int
    prior: int
    current: int
    direction: str
    raw_pct: Decimal
    capped: Decimal
    was_capped: bool
    contribution: Decimal


def _published_point(
    db: Session,
    *,
    on: date | None,
    scope_kind: str,
    scope_key: str,
    methodology_version: int,
) -> CardPirateIndexPoint | None:
    """The point this answer is about, or None for a 404.

    Identical selection to the composition route: `index_value IS NOT NULL`,
    and a supplied date selects EXACTLY that day rather than the nearest one.
    """
    stmt = select(CardPirateIndexPoint).where(
        CardPirateIndexPoint.scope_kind == scope_kind,
        CardPirateIndexPoint.scope_key == scope_key,
        CardPirateIndexPoint.methodology_version == methodology_version,
        CardPirateIndexPoint.index_value.is_not(None),
    )
    if on is not None:
        stmt = stmt.where(CardPirateIndexPoint.point_date == on)
    else:
        stmt = stmt.order_by(CardPirateIndexPoint.point_date.desc())
    return db.execute(stmt.limit(1)).scalars().first()


def _measure(
    print_ids: tuple[int, ...],
    prior: SnapshotDay,
    current: SnapshotDay,
) -> tuple[list[_Raw], Decimal]:
    """The frozen estimator's arithmetic, per constituent.

    Returns every constituent (flat ones included, because they are part of
    the sum that has to reconcile) and the summed contribution. The cap is
    `ln(1.25)` computed in the estimator's own working precision from its own
    `CAP_RATIO`; direction is decided from the INTEGER values rather than from
    the rounded log, exactly as `compute_step` does - capping never changes a
    sign, but comparing integers is exact where comparing a log is merely
    almost always right.
    """
    prior_by = prior.by_print()
    current_by = current.by_print()
    n = len(print_ids)
    rows: list[_Raw] = []

    with localcontext() as ctx:
        ctx.prec = _WORKING_PRECISION
        cap = +CAP_RATIO.ln()
        total = Decimal(0)
        for card_print_id in print_ids:
            before = prior_by[card_print_id]
            now = current_by[card_print_id]
            prior_v = Decimal(before.index_value_jpy)
            current_v = Decimal(now.index_value_jpy)

            raw = (current_v / prior_v).ln()
            was_capped = raw > cap or raw < -cap
            capped = cap if raw > cap else (-cap if raw < -cap else raw)
            contribution = capped / Decimal(n)
            total += contribution

            if now.index_value_jpy > before.index_value_jpy:
                direction = DIRECTION_UP
            elif now.index_value_jpy < before.index_value_jpy:
                direction = DIRECTION_DOWN
            else:
                direction = DIRECTION_FLAT

            rows.append(
                _Raw(
                    card_print_id=card_print_id,
                    prior=before.index_value_jpy,
                    current=now.index_value_jpy,
                    direction=direction,
                    # The card's OWN move, in the units a collector reads.
                    # Derived from the two archived integers, never from the
                    # capped log - the cap is an index rule, not a claim about
                    # what the card did.
                    raw_pct=((current_v / prior_v - 1) * 100).quantize(
                        _PCT_PLACES, rounding=ROUND_HALF_EVEN
                    ),
                    capped=capped,
                    was_capped=was_capped,
                    contribution=contribution,
                )
            )
        summed = total.quantize(_LOG_PLACES, rounding=ROUND_HALF_EVEN)
    return rows, summed


def _identity(db: Session, card_print_ids: list[int]) -> dict[int, dict]:
    """Catalogue identity for the movers, in TWO batched queries.

    No N+1, by construction: one join for the catalogue row and one call into
    the existing display-image authority, which is itself a single mapping
    query. Both are keyed by `card_print_id` - NOT by `card_code`, which does
    not identify a print. OP01-016 has seven prints in the catalogue and only
    one of them moved on 2026-09-07; a row keyed by the code would be
    ambiguous across all seven, which is also why the display image is part of
    the contract rather than a nicety.

    Everything here is CURRENT catalogue metadata. The prices beside it in the
    payload are archived. That split is deliberate: a rarity correction moves
    the label on a historical mover and never its prices.
    """
    if not card_print_ids:
        return {}

    rarity = effective_rarity_sql()
    rows = db.execute(
        select(
            CardPrint.id,
            CanonicalCard.card_code,
            # The catalogue's own preferred-name convention, reused rather
            # than re-decided - `coalesce(name_en, name_jp)` is what /prints
            # orders and displays by.
            CanonicalCard.name_en,
            CanonicalCard.name_jp,
            rarity,
            CardPrint.treatment,
            CardPrint.language,
        )
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(CardPrint.id.in_(card_print_ids))
    ).all()

    prints = db.execute(
        select(CardPrint).where(CardPrint.id.in_(card_print_ids))
    ).scalars().all()
    images = get_display_images_for_prints(db, prints)

    out: dict[int, dict] = {}
    for pid, code, name_en, name_jp, rarity_value, treatment, language in rows:
        image = images.get(pid)
        out[pid] = {
            "card_code": code,
            "name": name_en or name_jp,
            # Folded through the same aliasing the catalogue's own rarity
            # facet uses, so a mover's rarity and a `?rarity=` filter agree.
            "rarity": None if rarity_value is None else facet_value(rarity_value),
            "display_image_url": image.url if image is not None else None,
            "treatment": treatment,
            "language": language,
        }
    return out


def get_index_movers(
    db: Session,
    *,
    on: date | None = None,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    methodology_version: int = METHODOLOGY_VERSION,
    limit: int = MAX_MOVERS,
) -> IndexMoversOut | None:
    """Which constituents moved on one published day, and by how much.

    `None` means no published point for the request - a 404 at the route,
    never a substituted neighbouring day.
    """
    point = _published_point(
        db,
        on=on,
        scope_kind=scope_kind,
        scope_key=scope_key,
        methodology_version=methodology_version,
    )
    if point is None:
        return None

    # A BASE POINT ANSWERS 200 WITH AN EMPTY LIST, NOT AN ERROR.
    #
    # It opens a segment: it came from no step, so by `ck_cpi_points_base_
    # has_no_step` it has no prior day and zero constituents. "Nothing moved,
    # because there was nothing yet to compare against" is a true and complete
    # answer, so refusing with a 409 would report an absence of DATA where
    # there is only an absence of MOVEMENT. It stays distinguishable from an
    # ordinary quiet day by `constituent_count: 0` and a null
    # `prior_point_date`; 2026-09-06 is the other case - 296 constituents,
    # none of which moved.
    if point.prior_point_date is None or point.constituent_count == 0:
        if point.constituent_count != 0:
            raise MoversIntegrityError(
                f"point {point.point_date} has no prior day but "
                f"constituent_count={point.constituent_count}"
            )
        return IndexMoversOut(
            as_of=point.point_date,
            prior_point_date=point.prior_point_date,
            constituent_count=0,
            movers_count=0,
            unchanged_count=0,
            chain_link_log_return=point.chain_link_log_return,
            movers=(),
            truncated=False,
        )

    days = {
        day.point_date: day
        for day in load_snapshot_days(
            db, history_start=point.prior_point_date, end=point.point_date
        )
    }
    current = days.get(point.point_date)
    prior = days.get(point.prior_point_date)
    if current is None or prior is None:
        raise MoversIntegrityError(
            f"archived snapshots missing for {point.prior_point_date} -> "
            f"{point.point_date}; cannot reconstruct the constituent set"
        )

    print_ids = constituent_print_ids(prior, current)

    # GUARD ONE: the population must be the population the index published.
    if len(print_ids) != point.constituent_count:
        raise MoversIntegrityError(
            f"derived {len(print_ids)} constituents for {point.point_date} but "
            f"the published point carries {point.constituent_count}"
        )

    measured, summed = _measure(print_ids, prior, current)

    # GUARD TWO: the arithmetic must be the arithmetic the index published.
    # Every constituent's contribution, summed, IS the step - so a mismatch
    # means this module and the writer disagree about the same archived rows.
    if point.chain_link_log_return is not None and summed != point.chain_link_log_return:
        raise MoversIntegrityError(
            f"contributions for {point.point_date} sum to {summed} but the "
            f"published chain_link_log_return is {point.chain_link_log_return}"
        )

    non_flat = [row for row in measured if row.direction != DIRECTION_FLAT]
    unchanged_count = len(measured) - len(non_flat)

    # GUARD THREE: the counts the payload asserts must hold over the FULL set,
    # before any truncation.
    if len(non_flat) + unchanged_count != point.constituent_count:
        raise MoversIntegrityError(
            f"movers {len(non_flat)} + unchanged {unchanged_count} != "
            f"constituent_count {point.constituent_count}"
        )

    # Ranks are assigned over EVERY mover, then the list is truncated - so a
    # truncated payload still carries true ranks rather than positions within
    # the visible slice.
    by_move = sorted(non_flat, key=lambda r: (-abs(r.raw_pct), r.card_print_id))
    move_rank = {r.card_print_id: i + 1 for i, r in enumerate(by_move)}
    by_impact = sorted(
        non_flat,
        key=lambda r: (-abs(r.contribution), -abs(r.raw_pct), r.card_print_id),
    )
    impact_rank = {r.card_print_id: i + 1 for i, r in enumerate(by_impact)}

    truncated = len(by_move) > limit
    visible = by_move[:limit]
    identity = _identity(db, [r.card_print_id for r in visible])

    prior_level = _prior_index_value(db, point, scope_kind, scope_key, methodology_version)

    movers = tuple(
        Mover(
            card_print_id=r.card_print_id,
            card_code=identity.get(r.card_print_id, {}).get("card_code"),
            name=identity.get(r.card_print_id, {}).get("name"),
            rarity=identity.get(r.card_print_id, {}).get("rarity"),
            display_image_url=identity.get(r.card_print_id, {}).get("display_image_url"),
            treatment=identity.get(r.card_print_id, {}).get("treatment"),
            language=identity.get(r.card_print_id, {}).get("language"),
            prior_value_jpy=r.prior,
            current_value_jpy=r.current,
            direction=r.direction,
            raw_pct=r.raw_pct,
            capped_log_return=r.capped.quantize(
                _WIRE_PLACES, rounding=ROUND_HALF_EVEN
            ),
            was_capped=r.was_capped,
            contribution_log_return=r.contribution.quantize(
                _WIRE_PLACES, rounding=ROUND_HALF_EVEN
            ),
            # DISPLAY ASSISTANCE ONLY. See the schema for the full caveat: the
            # index chains multiplicatively in level space, so these do not sum
            # to the actual level change and are never used to reconcile
            # anything or to rank anything.
            approx_index_points=(
                (prior_level * r.contribution).quantize(
                    _POINTS_PLACES, rounding=ROUND_HALF_EVEN
                )
                if prior_level is not None
                else Decimal(0)
            ),
            move_rank=move_rank[r.card_print_id],
            impact_rank=impact_rank[r.card_print_id],
        )
        for r in visible
    )

    return IndexMoversOut(
        as_of=point.point_date,
        prior_point_date=point.prior_point_date,
        constituent_count=point.constituent_count,
        movers_count=len(non_flat),
        unchanged_count=unchanged_count,
        chain_link_log_return=point.chain_link_log_return,
        movers=movers,
        truncated=truncated,
    )


def _prior_index_value(
    db: Session,
    point: CardPirateIndexPoint,
    scope_kind: str,
    scope_key: str,
    methodology_version: int,
) -> Decimal | None:
    """The published level the step moved FROM.

    Only `approx_index_points` uses it, and only as a scale factor. A missing
    prior row is not an integrity failure for the same reason that field is
    not canonical - the exact answer is `contribution_log_return`, which does
    not depend on it.
    """
    return db.execute(
        select(CardPirateIndexPoint.index_value).where(
            CardPirateIndexPoint.scope_kind == scope_kind,
            CardPirateIndexPoint.scope_key == scope_key,
            CardPirateIndexPoint.methodology_version == methodology_version,
            CardPirateIndexPoint.point_date == point.prior_point_date,
        )
    ).scalars().first()


__all__ = [
    "DIRECTION_DOWN",
    "DIRECTION_FLAT",
    "DIRECTION_UP",
    "MAX_MOVERS",
    "IndexMoversOut",
    "Mover",
    "MoversIntegrityError",
    "get_index_movers",
]
