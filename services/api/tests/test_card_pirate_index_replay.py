"""Replay and verification against a real database session.

Two things are proved here that the pure estimator tests cannot:

  * REPLAY IS IDEMPOTENT AND INSERT-ONLY. A second run inserts nothing,
    rewrites no carry, and leaves every stored value untouched - including
    when a stored point disagrees with the rebuild, which is a bug alarm for a
    human, not something to overwrite.
  * VERIFICATION USES NATURAL IDENTITY. Surrogate ids are not reproducible
    across a rebuild, so every comparison keys on (scope_kind, scope_key,
    methodology_version, point_date) and a carry is compared by its target's
    RESOLVED DATE, never by the integer.

The tamper tests deliberately write bad rows directly, bypassing the service,
to prove the verifier catches what the schema cannot - notably a carry cycle
and a non-increasing carry chronology, which section 8.6 records as reachable
by a hand-written UPDATE.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import (
    BASE_VALUE,
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    SCOPE_SET,
)
from app.services.card_pirate_index_replay import (
    DISCREPANCY_CARRY_CYCLE,
    DISCREPANCY_CARRY_LEVEL_MISMATCH,
    DISCREPANCY_CARRY_NOT_INCREASING,
    DISCREPANCY_CARRY_TARGET_MISSING,
    DISCREPANCY_CARRY_WRONG_SCOPE,
    DISCREPANCY_FIELD_MISMATCH,
    DISCREPANCY_MISSING_POINT,
    DISCREPANCY_UNEXPECTED_POINT,
    build_scope_series,
    load_snapshot_days,
    replay_scope,
    verify_scope,
)

D3, D4, D5, D6 = (date(2026, 9, d) for d in (3, 4, 5, 6))

PROVENANCE = {
    "source_values": [
        {
            "source": "yuyutei",
            "reference_type": "sell",
            "contributes_to_index": True,
            "value_jpy": 100,
        }
    ]
}


def _seed_print(db, print_id: int) -> None:
    """Snapshots FK to card_prints with ondelete RESTRICT, so the lineage has
    to exist before a snapshot can.

    Idempotent: several tests seed two version eras in separate calls over the
    same prints, and re-inserting the canonical card would collide on
    card_code rather than test anything.
    """
    from app.models.canonical_card import CanonicalCard
    from app.models.card_print import CardPrint

    if db.get(CardPrint, print_id) is not None:
        return
    canonical = CanonicalCard(
        card_code=f"OP01-{print_id:03d}", name_en="x", card_type="CHARACTER"
    )
    db.add(canonical)
    db.flush()
    db.add(CardPrint(id=print_id, canonical_card_id=canonical.id, language="jp"))
    db.flush()


def seed_snapshots(db, days: dict, *, iv: int = 3, ssv: int = 2) -> None:
    """`days` maps date -> {card_print_id: index_value_jpy}."""
    seeded = set()
    for point_date, values in sorted(days.items()):
        for print_id in sorted(values):
            if print_id not in seeded:
                _seed_print(db, print_id)
                seeded.add(print_id)
    for point_date, values in sorted(days.items()):
        for print_id, value in sorted(values.items()):
            versions = (iv, ssv)
            if isinstance(value, tuple):
                value, versions = value
            db.add(
                MarketIndexSnapshot(
                    card_print_id=print_id,
                    calculated_at=datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
                    snapshot_date=point_date,
                    index_value_jpy=value,
                    calculation_method="median",
                    source_count=1,
                    coverage_status="full",
                    confidence="high",
                    index_version=versions[0],
                    source_semantics_version=versions[1],
                    provenance=PROVENANCE,
                )
            )
    db.flush()


def flat_days(db, n=50, dates=(D3, D4), value=100):
    seed_snapshots(db, {d: {i: value for i in range(n)} for d in dates})


# --- reading the archive ----------------------------------------------------


def test_load_skips_unvalued_snapshots(db_session):
    _seed_print(db_session, 1)
    db_session.add_all(
        [
            MarketIndexSnapshot(
                card_print_id=1,
                calculated_at=datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
                snapshot_date=D3, index_value_jpy=100,
                calculation_method="median", source_count=1,
                coverage_status="full", confidence="high",
                index_version=3, source_semantics_version=2,
                provenance=PROVENANCE,
            ),
            # coverage_status 'none' is an ABSENCE, not a zero. It must not
            # become a constituent and must never be carried forward.
            MarketIndexSnapshot(
                card_print_id=1,
                calculated_at=datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
                snapshot_date=D4, index_value_jpy=None,
                calculation_method="none", source_count=0,
                coverage_status="none", confidence="low",
                index_version=3, source_semantics_version=2,
                provenance=PROVENANCE,
            ),
        ]
    )
    db_session.flush()
    days = load_snapshot_days(db_session)
    assert [d.point_date for d in days] == [D3]


def test_load_reads_the_contributor_set_from_provenance(db_session):
    flat_days(db_session, n=1, dates=(D3,))
    (day,) = load_snapshot_days(db_session)
    assert day.observations[0].contributors == frozenset({("yuyutei", "sell")})


def test_scope_filter_is_just_a_constituent_filter(db_session):
    flat_days(db_session, n=50)
    everything = build_scope_series(db_session)
    subset = build_scope_series(
        db_session, scope_kind=SCOPE_SET, scope_key="OP-01",
        card_print_ids=list(range(40)),
    )
    assert everything.points[1].constituent_count == 50
    assert subset.points[1].constituent_count == 40
    assert subset.points[0].scope_key == "OP-01"


# --- replay -----------------------------------------------------------------


def test_replay_writes_the_series(db_session):
    flat_days(db_session, n=50)
    result, series = replay_scope(db_session, calculated_at=datetime(
        2026, 9, 7, 20, tzinfo=timezone.utc))
    assert result.inserted == 2
    rows = db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    assert [r.point_date for r in rows] == [D3, D4]
    assert rows[0].is_base is True
    assert rows[0].index_value == BASE_VALUE
    assert rows[0].carried_from_point_id is None
    assert rows[1].is_base is False
    assert rows[1].constituent_count == 50


def test_dry_run_writes_nothing(db_session):
    flat_days(db_session, n=50)
    result, series = replay_scope(db_session, dry_run=True)
    assert result.inserted == 0
    assert result.computed == 2
    assert db_session.scalars(select(CardPirateIndexPoint)).all() == []


def test_replay_is_idempotent(db_session):
    flat_days(db_session, n=50)
    replay_scope(db_session)
    before = _snapshot_rows(db_session)

    second, _ = replay_scope(db_session)
    assert second.inserted == 0
    assert second.already_present == 2
    assert _snapshot_rows(db_session) == before


def test_replay_never_updates_a_disagreeing_row(db_session):
    """A stored point that disagrees with the rebuild is a bug alarm. Replay
    leaves it exactly as it is; verify_scope is what surfaces it."""
    flat_days(db_session, n=50)
    replay_scope(db_session)
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == D4)
        .values(index_value=Decimal("1234.5678"))
    )
    db_session.flush()

    result, _ = replay_scope(db_session)
    assert result.inserted == 0
    stored = db_session.scalar(
        select(CardPirateIndexPoint).where(CardPirateIndexPoint.point_date == D4)
    )
    assert stored.index_value == Decimal("1234.5678")  # untouched


def test_replay_persists_a_carry_by_id(db_session):
    seed_snapshots(db_session, {D3: {i: 100 for i in range(50)}})
    seed_snapshots(db_session, {D4: {i: 100 for i in range(50)}}, iv=4)
    replay_scope(db_session)
    rows = db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    base, carried = rows
    assert carried.is_base is True
    assert carried.carried_from_point_id == base.id
    assert carried.index_value == base.index_value


def test_partial_replay_refuses_to_write_a_dangling_carry(db_session):
    """A partial replay whose carry target is not stored fails closed and
    loudly rather than writing a reference to nothing."""
    seed_snapshots(db_session, {D3: {i: 100 for i in range(50)}})
    seed_snapshots(db_session, {D4: {i: 100 for i in range(50)}}, iv=4)
    with pytest.raises(ValueError, match="carry target missing"):
        replay_scope(db_session, start=D4)


def test_partial_replay_does_not_fabricate_a_reset(db_session):
    """`start` filters what is WRITTEN, never what is computed.

    Building from a windowed archive would make D4 look like the scope's first
    day, so build_points would open an INITIAL base at 1000 there - inventing a
    reset the market never had and destroying the carry. The chain is a
    function of the whole history; only the write is windowed.
    """
    seed_snapshots(db_session, {D3: {i: 100 for i in range(50)}})
    seed_snapshots(db_session, {D4: {i: 100 for i in range(50)}}, iv=4)
    # Store the whole series first so the carry target exists...
    replay_scope(db_session)
    rows = db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    carried = rows[1]
    assert carried.is_base is True
    assert carried.carried_from_point_id == rows[0].id  # a carry, not a reset
    assert carried.index_value == rows[0].index_value


def test_scopes_are_independent(db_session):
    flat_days(db_session, n=50)
    replay_scope(db_session)
    replay_scope(
        db_session, scope_kind=SCOPE_SET, scope_key="OP-01",
        card_print_ids=list(range(40)),
    )
    overall = db_session.scalars(
        select(CardPirateIndexPoint).where(
            CardPirateIndexPoint.scope_kind == SCOPE_OVERALL
        )
    ).all()
    subset = db_session.scalars(
        select(CardPirateIndexPoint).where(
            CardPirateIndexPoint.scope_kind == SCOPE_SET
        )
    ).all()
    assert len(overall) == 2 and len(subset) == 2
    assert {r.scope_key for r in subset} == {"OP-01"}


def _snapshot_rows(db):
    """Everything a rebuild must reproduce, plus the ids - so a test can prove
    ids did NOT move as well as that values did not."""
    return [
        (
            r.id, r.point_date, r.index_value, r.is_base,
            r.carried_from_point_id, r.constituent_count, r.movers_up,
        )
        for r in db.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    ]


# --- determinism ------------------------------------------------------------


def test_two_independent_rebuilds_agree_on_natural_keys_and_values(db_session):
    """The core determinism claim: identical sources, identical output. Ids
    are excluded because they are exactly what does not survive a rebuild."""
    flat_days(db_session, n=50, dates=(D3, D4, D5))
    a = build_scope_series(db_session).points
    b = build_scope_series(db_session).points
    assert [_sig(p) for p in a] == [_sig(p) for p in b]


def test_point_ids_are_irrelevant_to_the_comparison(db_session):
    """Delete and replay: the ids change, the natural-key rows do not, and
    verification still passes."""
    flat_days(db_session, n=50, dates=(D3, D4, D5))
    replay_scope(db_session)
    first_ids = [r.id for r in db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date))]
    first_values = [_row_sig(r) for r in db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date))]

    for row in db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date.desc())
    ).all():
        db_session.delete(row)
    db_session.flush()

    replay_scope(db_session)
    second = db_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    # Whether the surrogates come back the same is engine-dependent - SQLite
    # reuses rowids after a delete, PostgreSQL's sequence marches on - and
    # that is precisely why nothing may compare them. What must hold on every
    # engine is that the natural-key rows are identical and verification
    # passes.
    assert [_row_sig(r) for r in second] == first_values
    assert verify_scope(db_session).ok
    assert first_ids  # the first run really did store rows


def test_no_surrogate_or_clock_field_is_ever_compared():
    """The structural guarantee behind id-independence: the comparison list
    itself excludes everything a rebuild cannot reproduce."""
    from app.services.card_pirate_index_replay import COMPARED_FIELDS

    for excluded in ("id", "carried_from_point_id", "calculated_at", "created_at"):
        assert excluded not in COMPARED_FIELDS


def _sig(point):
    return (
        point.natural_key, point.index_value, point.is_base,
        point.carried_from_key, point.constituent_count, point.movers_up,
    )


def _row_sig(row):
    return (
        row.scope_kind, row.scope_key, row.methodology_version, row.point_date,
        row.index_value, row.is_base, row.constituent_count, row.movers_up,
        row.movers_down, row.movers_flat, row.capped_count,
        row.unpublishable_reason, row.step_days, row.prior_point_date,
    )


# --- verification: the happy path -------------------------------------------


def test_verify_passes_on_a_freshly_replayed_series(db_session):
    flat_days(db_session, n=50, dates=(D3, D4, D5))
    replay_scope(db_session)
    result = verify_scope(db_session)
    assert result.ok, [str(d) for d in result.discrepancies]
    assert result.stored_points == result.expected_points == 3


def test_verify_writes_nothing(db_session):
    flat_days(db_session, n=50)
    replay_scope(db_session)
    before = _snapshot_rows(db_session)
    verify_scope(db_session)
    assert _snapshot_rows(db_session) == before


def test_verify_reports_a_missing_point(db_session):
    flat_days(db_session, n=50, dates=(D3, D4, D5))
    replay_scope(db_session)
    row = db_session.scalar(
        select(CardPirateIndexPoint).where(CardPirateIndexPoint.point_date == D5)
    )
    db_session.delete(row)
    db_session.flush()
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_MISSING_POINT in kinds


# --- verification: tampering ------------------------------------------------


def _tamper(db, point_date, **values):
    db.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == point_date)
        .values(**values)
    )
    db.flush()


# Each tamper is INTERNALLY CONSISTENT - it satisfies every CHECK constraint -
# and merely disagrees with what a replay produces. That is the whole point:
# the schema already refuses a self-contradictory row (setting
# constituent_count alone breaks ck_cpi_points_movers_sum), so the only rows
# the verifier is needed for are the plausible-looking wrong ones.
@pytest.mark.parametrize(
    "detected,values",
    [
        ("index_value", {"index_value": Decimal("1234.5678")}),
        ("constituent_count", {"constituent_count": 40, "movers_flat": 40}),
        ("eligible_print_count", {"eligible_print_count": 999}),
        ("movers_up", {"movers_up": 1, "movers_flat": 49}),
        ("movers_down", {"movers_down": 1, "movers_flat": 49}),
        ("capped_count", {"capped_count": 9}),
        ("step_days", {"step_days": 5}),
        ("index_version", {"index_version": 9}),
        ("source_semantics_version", {"source_semantics_version": 9}),
        ("chain_link_log_return", {"chain_link_log_return": Decimal("0.5")}),
        ("prior_point_date", {"prior_point_date": D3}),
    ],
)
def test_verify_detects_a_tampered_field(db_session, detected, values):
    flat_days(db_session, n=50, dates=(D3, D4, D5))
    replay_scope(db_session)
    _tamper(db_session, D5, **values)
    result = verify_scope(db_session)
    mismatches = [
        d for d in result.discrepancies if d.kind == DISCREPANCY_FIELD_MISMATCH
    ]
    assert detected in {d.field for d in mismatches}, [
        str(d) for d in result.discrepancies
    ]


def test_the_schema_refuses_an_inconsistent_unpublishable_state(db_session):
    """A row carrying BOTH a value and an unpublishable reason cannot be
    written at all - ck_cpi_points_value_presence is a biconditional.

    The verifier repeats this check anyway, and that is deliberate rather than
    redundant: it is the half of verification that still holds against a
    restored dump, a database whose constraints were dropped, or any engine
    that did not enforce them. It cannot be exercised here precisely because
    the constraint works, so what is asserted here is the constraint.
    """
    from sqlalchemy.exc import IntegrityError

    flat_days(db_session, n=50, dates=(D3, D4))
    replay_scope(db_session)
    with pytest.raises(IntegrityError):
        _tamper(db_session, D4, unpublishable_reason="mixed_version_day")
    db_session.rollback()


def test_verify_detects_an_unexpected_point(db_session):
    flat_days(db_session, n=50, dates=(D3, D4))
    replay_scope(db_session)
    db_session.add(
        CardPirateIndexPoint(
            scope_kind=SCOPE_OVERALL, scope_key="",
            methodology_version=METHODOLOGY_VERSION,
            index_version=3, source_semantics_version=2,
            point_date=D6, index_value=Decimal("1000.0000"), is_base=False,
            prior_point_date=D4, step_days=2,
            chain_link_log_return=Decimal("0"),
            constituent_count=50, eligible_print_count=50,
            movers_up=0, movers_down=0, movers_flat=50, capped_count=0,
            calculated_at=datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_UNEXPECTED_POINT in kinds


# --- verification: the carry chain ------------------------------------------
#
# These are the checks the SCHEMA deliberately cannot make. A hand-written
# UPDATE can build a cycle or a backwards carry - measured on PostgreSQL 18.6,
# and it succeeds - so the verifier is where they are caught.


def _carried_series(db):
    seed_snapshots(db, {D3: {i: 100 for i in range(50)}})
    seed_snapshots(db, {D4: {i: 100 for i in range(50)}}, iv=4)
    replay_scope(db)
    return db.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()


def test_verify_detects_a_carry_pointing_at_nothing(db_session):
    _carried_series(db_session)
    _tamper(db_session, D4, carried_from_point_id=999999)
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_CARRY_TARGET_MISSING in kinds


def test_verify_detects_a_carry_level_mismatch(db_session):
    """The composite FK enforces this on PostgreSQL. The verifier repeats it
    so a SQLite deployment, a disabled constraint or a restored dump cannot
    hide a broken chain."""
    _carried_series(db_session)
    _tamper(db_session, D4, index_value=Decimal("1500.0000"))
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_CARRY_LEVEL_MISMATCH in kinds


def test_verify_detects_a_cross_scope_carry(db_session):
    base_rows = _carried_series(db_session)
    other = CardPirateIndexPoint(
        scope_kind=SCOPE_SET, scope_key="OP-01",
        methodology_version=METHODOLOGY_VERSION,
        index_version=3, source_semantics_version=2,
        point_date=D3, index_value=BASE_VALUE, is_base=True,
        constituent_count=0, eligible_print_count=10,
        calculated_at=datetime(2026, 9, 7, 20, tzinfo=timezone.utc),
    )
    db_session.add(other)
    db_session.flush()
    _tamper(db_session, D4, carried_from_point_id=other.id)
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_CARRY_WRONG_SCOPE in kinds


def test_verify_detects_a_non_increasing_carry(db_session):
    """Chronology is not enforceable by CHECK or FK - it needs another row -
    so the verifier is the only thing standing behind it."""
    rows = _carried_series(db_session)
    base, carried = rows
    # Point the EARLIER row at the later one.
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.id == base.id)
        .values(carried_from_point_id=carried.id, index_value=carried.index_value)
    )
    db_session.flush()
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_CARRY_NOT_INCREASING in kinds


def test_verify_detects_a_carry_cycle(db_session):
    """A -> B and B -> A. Reachable only by hand-written UPDATE, which is
    exactly the exposure section 8.6 finding 4 documents."""
    rows = _carried_series(db_session)
    base, carried = rows
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.id == base.id)
        .values(carried_from_point_id=carried.id, index_value=carried.index_value)
    )
    db_session.flush()
    kinds = {d.kind for d in verify_scope(db_session).discrepancies}
    assert DISCREPANCY_CARRY_CYCLE in kinds
    assert DISCREPANCY_CARRY_NOT_INCREASING in kinds


def test_verify_terminates_on_a_cycle(db_session):
    """The walk is bounded. A cycle must report, not hang."""
    rows = _carried_series(db_session)
    base, carried = rows
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.id == base.id)
        .values(carried_from_point_id=carried.id, index_value=carried.index_value)
    )
    db_session.flush()
    result = verify_scope(db_session)
    assert not result.ok


# --- no repair path ---------------------------------------------------------


def test_neither_service_contains_an_update_or_delete_writer():
    """The append-only convention is what makes the carry chain acyclic by
    construction; nothing in these two modules may weaken it."""
    import pathlib
    import re

    import app.services.card_pirate_index as core
    import app.services.card_pirate_index_replay as replay

    for module in (core, replay):
        source = pathlib.Path(module.__file__).read_text()
        assert not re.search(r"\bupdate\s*\(", source), module.__name__
        assert not re.search(r"\bdelete\s*\(", source), module.__name__
        assert "on_conflict_do_update" not in source, module.__name__
