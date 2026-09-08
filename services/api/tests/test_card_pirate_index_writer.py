"""The daily writer: what it writes, what it refuses, and what it never touches.

The estimator has its own tests, and so does the replay. This file is about
the writer's ONE job - deciding which days are missing from the head of the
series - and about its two hard guarantees:

  * FORWARD ONLY. It writes strictly after the persisted head, and it refuses
    to run at all if the persisted range does not already reconcile with a
    replay. A hole behind the head is an alarm, not a gap to fill.
  * INSERT ONLY, OR NOTHING. Every abort path leaves the table byte-identical,
    ids and clocks included.

Seeds are COMMITTED rather than flushed, unlike the replay suite's. The writer
rolls back on its no-op and dry-run paths (deliberately - a read-only path must
be unable to leave anything behind), which would discard a merely-flushed
fixture and make the test measure the fixture instead of the writer.
"""

import pathlib
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.card_pirate_index_writer import (
    LOCK_NAME,
    EXTENSION_ALREADY_STORED,
    EXTENSION_BASE_SHAPE,
    EXTENSION_BEYOND_ARCHIVE,
    EXTENSION_CARRY_LEVEL_MISMATCH,
    EXTENSION_CARRY_NOT_INCREASING,
    EXTENSION_CARRY_UNRESOLVABLE,
    EXTENSION_INCONSISTENT_UNPUBLISHABLE,
    EXTENSION_NOT_AFTER_HEAD,
    EXTENSION_OUT_OF_ORDER,
    EXTENSION_STEP_SHAPE,
    ExtensionResult,
    PlannedPoint,
    WriterAbort,
    WriterPlan,
    plan_write,
    review_persisted,
    run_writer,
    verify_persisted,
    verify_planned_extension,
)
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import (
    BASE_VALUE,
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS,
    V1_OVERALL_SEED,
)
from app.services.job_locks import LockHeldError, acquire_lock
from app.services.card_pirate_index_replay import (
    DISCREPANCY_MISSING_POINT,
    Discrepancy,
    VerifyResult,
    replay_scope,
)

D3, D4, D5, D6, D7, D8 = (date(2026, 9, d) for d in (3, 4, 5, 6, 7, 8))
STAMP = datetime(2026, 9, 7, 20, tzinfo=timezone.utc)

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


def seed_archive(db, days: dict, *, iv: int = 3, ssv: int = 2) -> None:
    """`days` maps date -> {card_print_id: index_value_jpy}. Commits."""
    for values in days.values():
        for print_id in sorted(values):
            _seed_print(db, print_id)
    for point_date, values in sorted(days.items()):
        for print_id, value in sorted(values.items()):
            db.add(
                MarketIndexSnapshot(
                    card_print_id=print_id,
                    calculated_at=STAMP,
                    snapshot_date=point_date,
                    index_value_jpy=value,
                    calculation_method="median",
                    source_count=1,
                    coverage_status="full",
                    confidence="high",
                    index_version=iv,
                    source_semantics_version=ssv,
                    provenance=PROVENANCE,
                )
            )
    db.commit()


def flat_archive(db, dates, *, n: int = 50, value: int = 100) -> None:
    seed_archive(db, {d: {i: value for i in range(n)} for d in dates})


def stored(db) -> list[CardPirateIndexPoint]:
    db.expire_all()
    return list(
        db.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    )


def fingerprint(db) -> list[tuple]:
    """Everything about every row, ids and clocks included - the comparison
    that proves a run neither updated nor deleted anything."""
    return [
        (
            r.id,
            r.scope_kind,
            r.scope_key,
            r.methodology_version,
            r.index_version,
            r.source_semantics_version,
            r.point_date,
            r.index_value,
            r.is_base,
            r.carried_from_point_id,
            r.prior_point_date,
            r.step_days,
            r.chain_link_log_return,
            r.constituent_count,
            r.eligible_print_count,
            r.movers_up,
            r.movers_down,
            r.movers_flat,
            r.capped_count,
            r.unpublishable_reason,
            r.calculated_at,
            r.created_at,
        )
        for r in stored(db)
    ]


def seed_staging_equivalent_head(db) -> list[tuple]:
    """The four rows staging holds today, structurally: 2026-09-03 opens the
    series at 1000 as a base, 09-04/05/06 are ordinary same-version steps,
    all at methodology 1 / index 3 / semantics 2.

    The LEVELS are not staging's - those are a function of ~300 real prints -
    but every property the writer's contract turns on is: the dates, the
    versions, the base-then-step shape, and the fact that 09-06 is the head.
    """
    flat_archive(db, (D3, D4, D5, D6))
    replay_scope(
        db,
        history_start=V1_OVERALL_SEED.history_start,
        calculated_at=STAMP,
    )
    db.commit()
    rows = stored(db)
    assert [r.point_date for r in rows] == [D3, D4, D5, D6]
    assert rows[0].is_base is True and rows[0].index_value == BASE_VALUE
    return fingerprint(db)


# --- A. empty table -> the initial series ----------------------------------


def test_a_empty_table_and_seed_archive_writes_the_initial_series(db_session):
    flat_archive(db_session, (D3, D4, D5, D6))

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 4
    assert result.verified is True
    assert [r.point_date for r in stored(db_session)] == [D3, D4, D5, D6]
    assert stored(db_session)[0].index_value == BASE_VALUE
    assert stored(db_session)[0].is_base is True
    assert verify_persisted(db_session).ok


def test_a_writer_never_publishes_the_v1_v2_era_before_history_start(db_session):
    """The pre-2026-09-03 archive is retained and queryable but deliberately
    unpublished (methodology section 6). The writer reads history_start from
    the seed and must not open the series on the older era."""
    seed_archive(
        db_session,
        {date(2026, 9, 1): {i: 100 for i in range(50)}},
        iv=1,
        ssv=1,
    )
    flat_archive(db_session, (D3, D4))

    run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert [r.point_date for r in stored(db_session)] == [D3, D4]


# --- B. nothing new --------------------------------------------------------


def test_b_head_level_with_the_archive_writes_nothing(db_session):
    seed_staging_equivalent_head(db_session)
    before = fingerprint(db_session)

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 0
    assert result.plan.latest_persisted_point_date == D6
    assert result.plan.latest_archive_day == D6
    assert result.plan.planned == ()
    assert fingerprint(db_session) == before


# --- C. exactly one new archived day ---------------------------------------


def test_c_one_new_archive_day_inserts_exactly_that_day(db_session):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    rows = stored(db_session)
    assert [r.point_date for r in rows] == [D3, D4, D5, D6, D7]
    assert rows[-1].prior_point_date == D6
    assert rows[-1].step_days == 1
    # J, stated where it is actually at risk: the four pre-existing rows are
    # byte-identical afterwards, ids and clocks included.
    assert fingerprint(db_session)[:4] == before
    assert verify_persisted(db_session).ok


# --- D. rerun --------------------------------------------------------------


def test_d_immediate_rerun_inserts_nothing_and_changes_nothing(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    run_writer(db_session, calculated_at=STAMP, skip_lock=True)
    after_first = fingerprint(db_session)

    second = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert second.inserted == 0
    assert fingerprint(db_session) == after_first


# --- E. catch-up -----------------------------------------------------------


def test_e_several_missed_days_are_caught_up_in_ascending_order(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 2
    rows = stored(db_session)
    assert [r.point_date for r in rows] == [D3, D4, D5, D6, D7, D8]
    # Ascending insertion is a requirement, not a coincidence: the carry FK is
    # immediate. Ids rising with dates is the observable form of it.
    assert [r.id for r in rows] == sorted(r.id for r in rows)
    assert rows[-1].prior_point_date == D7
    assert verify_persisted(db_session).ok


def test_e_being_offline_does_not_reset_the_chain(db_session):
    """A catch-up run must reproduce the points the daily runs would have
    written - same levels, carries intact - not open a new base at 1000."""
    flat_archive(db_session, (D3, D4))
    run_writer(db_session, calculated_at=STAMP, skip_lock=True)
    seed_archive(db_session, {D5: {i: 110 for i in range(50)}})
    seed_archive(db_session, {D6: {i: 110 for i in range(50)}})

    run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    rows = stored(db_session)
    assert [r.is_base for r in rows] == [True, False, False, False]
    assert rows[2].index_value > rows[1].index_value
    assert verify_persisted(db_session).ok


# --- F. a gap in the archive -----------------------------------------------


def test_f_a_missing_archive_day_is_not_fabricated_or_forward_filled(db_session):
    seed_staging_equivalent_head(db_session)
    # 2026-09-07 was never archived; 09-08 was.
    flat_archive(db_session, (D8,))

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    rows = stored(db_session)
    assert [r.point_date for r in rows] == [D3, D4, D5, D6, D8]
    assert D7 not in {r.point_date for r in rows}
    # The gap is REPORTED, not smoothed: a real two-day return, honestly
    # labelled, rather than a repeat of 09-06.
    assert rows[-1].prior_point_date == D6
    assert rows[-1].step_days == 2


def test_f_a_day_of_pure_absences_is_not_a_day(db_session):
    """coverage_status='none' rows carry no value. A day made only of them is
    an absence and must not become a point."""
    seed_staging_equivalent_head(db_session)
    for print_id in range(50):
        db_session.add(
            MarketIndexSnapshot(
                card_print_id=print_id,
                calculated_at=STAMP,
                snapshot_date=D7,
                index_value_jpy=None,
                calculation_method="none",
                source_count=0,
                coverage_status="none",
                confidence="low",
                index_version=3,
                source_semantics_version=2,
                provenance=PROVENANCE,
            )
        )
    db_session.commit()

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 0
    assert result.plan.latest_archive_day == D6
    assert [r.point_date for r in stored(db_session)] == [D3, D4, D5, D6]


def test_f_an_unpublishable_day_is_still_a_row_not_a_skip(db_session):
    """Below MIN_CONSTITUENTS is a measured, published-as-unpublishable fact.
    Writing nothing would be indistinguishable from the job not running."""
    seed_staging_equivalent_head(db_session)
    seed_archive(db_session, {D7: {i: 100 for i in range(5)}})

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    row = stored(db_session)[-1]
    assert row.point_date == D7
    assert row.index_value is None
    assert row.unpublishable_reason == UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS


# --- G. the persisted series disagrees with the archive ---------------------


def test_g_a_tampered_historical_point_aborts_with_zero_writes(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == D4)
        .values(index_value=Decimal("1234.5678"))
    )
    db_session.commit()
    before = fingerprint(db_session)

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "does not reconcile" in str(exc.value)
    assert fingerprint(db_session) == before
    assert len(stored(db_session)) == 4


def test_g_a_hole_behind_the_head_is_never_silently_backfilled(db_session):
    """A missing interior day means something already went wrong. Filling it
    unattended would destroy the evidence and publish a level nobody checked."""
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        CardPirateIndexPoint.__table__.delete().where(
            CardPirateIndexPoint.point_date == D5
        )
    )
    db_session.commit()
    before = fingerprint(db_session)
    flat_archive(db_session, (D7,))

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "missing_point" in str(exc.value)
    assert fingerprint(db_session) == before


def test_g_a_stored_point_the_archive_no_longer_supports_aborts(db_session):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        MarketIndexSnapshot.__table__.delete().where(
            MarketIndexSnapshot.snapshot_date == D5
        )
    )
    db_session.commit()
    before = fingerprint(db_session)

    with pytest.raises(WriterAbort):
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert fingerprint(db_session) == before


def test_g_an_archive_that_no_longer_reaches_the_head_aborts(db_session):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        MarketIndexSnapshot.__table__.delete().where(
            MarketIndexSnapshot.snapshot_date >= D4
        )
    )
    db_session.commit()
    before = fingerprint(db_session)

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "unavailable" in str(exc.value)
    assert fingerprint(db_session) == before


def test_g_a_foreign_methodology_version_in_the_scope_aborts(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    db_session.add(
        CardPirateIndexPoint(
            scope_kind=SCOPE_OVERALL,
            scope_key="",
            methodology_version=METHODOLOGY_VERSION + 1,
            index_version=3,
            source_semantics_version=2,
            point_date=D7,
            index_value=BASE_VALUE,
            is_base=True,
            constituent_count=0,
            eligible_print_count=50,
            calculated_at=STAMP,
        )
    )
    db_session.commit()
    before = fingerprint(db_session)

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "methodology_version" in str(exc.value)
    assert fingerprint(db_session) == before


def test_g_a_point_before_history_start_aborts(db_session):
    seed_staging_equivalent_head(db_session)
    db_session.add(
        CardPirateIndexPoint(
            scope_kind=SCOPE_OVERALL,
            scope_key="",
            methodology_version=METHODOLOGY_VERSION,
            index_version=1,
            source_semantics_version=1,
            point_date=date(2026, 8, 21),
            index_value=BASE_VALUE,
            is_base=True,
            constituent_count=0,
            eligible_print_count=20,
            calculated_at=STAMP,
        )
    )
    db_session.commit()
    before = fingerprint(db_session)

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "predate" in str(exc.value)
    assert fingerprint(db_session) == before


# --- H. verification fails after the insert, before the commit --------------


def test_h_a_failing_final_verification_rolls_the_whole_write_back(
    db_session, monkeypatch
):
    """The commit gate is the last statement. If verification of the WRITTEN
    series fails, the inserts that were already issued must not survive."""
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))

    def failing_verify(db, seed=V1_OVERALL_SEED):
        return VerifyResult(
            scope_kind=SCOPE_OVERALL,
            scope_key="",
            stored_points=6,
            expected_points=6,
            discrepancies=[
                Discrepancy(
                    kind="field_mismatch",
                    scope_kind=SCOPE_OVERALL,
                    scope_key="",
                    point_date=D7,
                    field="index_value",
                    stored=1,
                    expected=2,
                )
            ],
        )

    monkeypatch.setattr(
        "app.card_pirate_index_writer.verify_persisted", failing_verify
    )

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "verification of the written series failed" in str(exc.value)
    assert fingerprint(db_session) == before
    assert [r.point_date for r in stored(db_session)] == [D3, D4, D5, D6]


def test_h_a_pre_existing_row_modified_mid_write_rolls_back(
    db_session, monkeypatch
):
    """The append-only guard is a runtime fact, not a convention. Simulate a
    concurrent rewrite of a published point and prove the run refuses."""
    import app.card_pirate_index_writer as writer

    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    real_replay = writer.replay_scope

    def tampering_replay(db, **kwargs):
        out = real_replay(db, **kwargs)
        # D4, not D3: rewriting the base's level would trip
        # ck_cpi_points_initial_base_is_base_value at the statement, and the
        # point here is to get a *legal* rewrite past the schema and prove the
        # writer catches it anyway.
        db.execute(
            update(CardPirateIndexPoint)
            .where(CardPirateIndexPoint.point_date == D4)
            .values(index_value=Decimal("999.0000"))
        )
        return out

    monkeypatch.setattr(
        "app.card_pirate_index_writer.replay_scope", tampering_replay
    )

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "were modified during the write" in str(exc.value)
    assert fingerprint(db_session) == before


def test_h_a_carry_in_the_write_window_resolves_against_the_stored_head(
    db_session,
):
    """A version boundary carries a level from a point an EARLIER run stored.
    `start` bounds the write, not the chain, so the carry resolves against a
    row that is already in the table - which is why the writer can never hit
    replay's dangling-reference guard while the pre-verify passes."""
    flat_archive(db_session, (D3, D4))
    run_writer(db_session, calculated_at=STAMP, skip_lock=True)
    head_id = stored(db_session)[-1].id
    head_level = stored(db_session)[-1].index_value
    seed_archive(db_session, {D5: {i: 100 for i in range(50)}}, iv=4)

    result = run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    carried = stored(db_session)[-1]
    assert carried.is_base is True
    assert carried.carried_from_point_id == head_id
    assert carried.index_value == head_level
    assert verify_persisted(db_session).ok


def test_h_any_exception_from_the_replay_leaves_the_table_unchanged(
    db_session, monkeypatch
):
    """Replay fails closed on a missing carry target, a boundary violation and
    anything else. Whatever it raises, the writer's transaction is discarded -
    there is no partially-written day."""
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))

    def exploding_replay(db, **kwargs):
        db.execute(
            CardPirateIndexPoint.__table__.insert().values(
                scope_kind=SCOPE_OVERALL,
                scope_key="",
                methodology_version=METHODOLOGY_VERSION,
                index_version=3,
                source_semantics_version=2,
                point_date=D7,
                index_value=Decimal("1000.0000"),
                is_base=False,
                constituent_count=50,
                eligible_print_count=50,
                movers_up=0,
                movers_down=0,
                movers_flat=50,
                capped_count=0,
                prior_point_date=D6,
                step_days=1,
                chain_link_log_return=Decimal("0"),
                calculated_at=STAMP,
            )
        )
        raise ValueError("carry target missing for overall/- 2026-09-08")

    monkeypatch.setattr(
        "app.card_pirate_index_writer.replay_scope", exploding_replay
    )

    with pytest.raises(ValueError):
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert fingerprint(db_session) == before


# --- dry run ----------------------------------------------------------------


def test_dry_run_reports_the_plan_and_writes_nothing(db_session):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))

    result = run_writer(db_session, dry_run=True, skip_lock=True)

    assert result.dry_run is True
    assert result.inserted == 0
    assert [p.point_date for p in result.plan.planned] == [D7, D8]
    assert result.plan.latest_persisted_point_date == D6
    assert result.plan.latest_archive_day == D8
    assert fingerprint(db_session) == before


def test_dry_run_plan_equals_what_the_write_actually_produces(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))
    planned = run_writer(db_session, dry_run=True, skip_lock=True).plan.planned

    run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    written = [r for r in stored(db_session) if r.point_date > D6]
    assert [p.point_date for p in planned] == [r.point_date for r in written]
    assert [p.index_value for p in planned] == [r.index_value for r in written]
    assert [p.step_days for p in planned] == [r.step_days for r in written]


def test_dry_run_on_an_empty_scope_plans_the_whole_series(db_session):
    flat_archive(db_session, (D3, D4, D5, D6))

    plan, _ = plan_write(db_session)

    assert plan.latest_persisted_point_date is None
    assert plan.stored_point_count == 0
    assert [p.point_date for p in plan.planned] == [D3, D4, D5, D6]
    assert len(stored(db_session)) == 0


# --- I / K / L. static guarantees about the module itself -------------------


WRITER_SOURCE = pathlib.Path(
    __import__("app.card_pirate_index_writer", fromlist=["__file__"]).__file__
).read_text()


def test_i_the_writer_has_no_update_or_delete_path():
    """There is no repair flag and no rewrite, by construction. The only
    statement that changes stored data anywhere beneath this module is
    replay_scope's INSERT ... ON CONFLICT DO NOTHING."""
    body = WRITER_SOURCE.split('"""', 2)[2]
    for forbidden in (
        r"\bupdate\s*\(",
        r"\bdelete\s*\(",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\.merge\s*\(",
        r"on_conflict_do_update",
    ):
        assert not re.search(forbidden, body), f"{forbidden!r} in the writer"


def test_i_the_writer_issues_exactly_one_commit():
    body = WRITER_SOURCE.split('"""', 2)[2]
    assert len(re.findall(r"db\.commit\(\)", body)) == 1


def test_k_the_writer_imports_no_collector_source_or_network_code():
    """The index is derived from the archive alone. Nothing here may reach a
    resolver, a collector, a browser or the network - a point must never
    depend on what a website said at the moment the job happened to run."""
    import ast

    tree = ast.parse(WRITER_SOURCE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = ("httpx", "requests", "urllib", "socket", "playwright", "aiohttp")
    assert not [m for m in imported if m.split(".")[0] in forbidden]
    assert not [
        m
        for m in imported
        if "collector" in m or "resolver" in m or "browser" in m or "scrap" in m
    ]
    # The only application modules it may touch: the archive model, the point
    # model, the estimator, the replay, the session factory and the locks.
    app_modules = sorted(m for m in imported if m.startswith("app."))
    assert app_modules == [
        "app.db",
        "app.models.card_pirate_index_point",
        "app.models.market_index_snapshot",
        "app.services.card_pirate_index",
        "app.services.card_pirate_index_replay",
        "app.services.job_locks",
    ]


def test_k_the_writer_reimplements_no_methodology():
    """Every constant and every piece of arithmetic stays in the estimator.
    A number spelled out here would be a second methodology."""
    body = WRITER_SOURCE.split('"""', 2)[2]
    for forbidden in (
        r"\bcompute_step\b",
        r"\bbuild_points\b",
        r"\bchain\s*\(",
        r"\bCAP_RATIO\b",
        r"\bMIN_CONSTITUENTS\b",
        r"\bBASE_VALUE\b",
        r"\bDecimal\s*\(",
        r"\bln\s*\(",
        r"timedelta",
    ):
        assert not re.search(forbidden, body), f"{forbidden!r} in the writer"


def test_l_index_and_source_semantics_versions_are_untouched():
    from app.services.market_index import INDEX_VERSION
    from app.services.source_semantics import SOURCE_SEMANTICS_VERSION

    assert INDEX_VERSION == 3
    assert SOURCE_SEMANTICS_VERSION == 2
    assert "INDEX_VERSION" not in WRITER_SOURCE.split('"""', 2)[2]
    assert "SOURCE_SEMANTICS_VERSION" not in WRITER_SOURCE.split('"""', 2)[2]


def test_l_the_writer_reads_the_seed_rather_than_restating_it():
    assert V1_OVERALL_SEED.history_start == date(2026, 9, 3)
    assert V1_OVERALL_SEED.methodology_version == 1
    body = WRITER_SOURCE.split('"""', 2)[2]
    assert not re.search(r"date\(\s*2026", body)


# --- CLI --------------------------------------------------------------------


def test_cli_dry_run_exits_zero_and_writes_nothing(db_session, monkeypatch, capsys):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    import app.card_pirate_index_writer as writer

    monkeypatch.setattr(writer, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert writer.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "planned_inserts: 1" in out
    assert "dry_run: True" in out
    assert fingerprint(db_session) == before


def test_cli_verify_exits_one_when_the_series_disagrees(
    db_session, monkeypatch, capsys
):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == D5)
        .values(index_value=Decimal("1.0000"))
    )
    db_session.commit()

    import app.card_pirate_index_writer as writer

    monkeypatch.setattr(writer, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert writer.main(["--verify"]) == 1
    # The mismatch is in the PERSISTED range, so plan_write refuses before
    # the classifier is ever reached - a louder path to the same exit code.
    assert "field_mismatch" in capsys.readouterr().err


def test_cli_abort_exits_one_without_writing(db_session, monkeypatch, capsys):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == D5)
        .values(index_value=Decimal("1.0000"))
    )
    db_session.commit()
    flat_archive(db_session, (D7,))
    before = fingerprint(db_session)

    import app.card_pirate_index_writer as writer

    monkeypatch.setattr(writer, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    assert writer.main([]) == 1
    assert "ABORTED, nothing written" in capsys.readouterr().err
    assert fingerprint(db_session) == before


# --- exit-code semantics ----------------------------------------------------
#
# The contradiction this section exists to pin down: a dry run that says
# "1 planned insert, everything checks out" standing next to a verification
# command that exits 1 for the same reason. Pending work is not a fault, and
# the two commands must now agree about that - without `verify_persisted`
# itself being softened, which these tests also assert.


@pytest.fixture
def cli(db_session, monkeypatch):
    """`main()` bound to the test session, so exit codes can be asserted."""
    import app.card_pirate_index_writer as writer

    monkeypatch.setattr(writer, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    return writer.main


def test_dry_run_exits_zero_when_a_planned_point_is_pending(cli, db_session, capsys):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    assert cli(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "planned_inserts: 1" in out
    assert "persisted_verified: True" in out
    assert "planned_extension_verified: True" in out


def test_verify_exits_zero_when_a_planned_point_is_pending(cli, db_session, capsys):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    assert cli(["--verify"]) == 0

    out = capsys.readouterr().out
    assert "persisted_faults: 0" in out
    assert "pending_inserts: 1" in out
    assert "pending 2026-09-07 (planned, not yet written)" in out


def test_verify_exits_zero_when_nothing_is_pending(cli, db_session, capsys):
    seed_staging_equivalent_head(db_session)

    assert cli(["--verify"]) == 0

    out = capsys.readouterr().out
    assert "stored_points: 4" in out
    assert "persisted_faults: 0" in out
    assert "pending_inserts: 0" in out


def test_verify_persisted_itself_is_not_softened(db_session):
    """The service still calls the un-written day a `missing_point`. The
    reclassification is a reporting decision made ON TOP of that, not a change
    to what verification means - otherwise the write path's commit gate, which
    uses the same function, would have been weakened too."""
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    result = verify_persisted(db_session)

    assert not result.ok
    assert [d.kind for d in result.discrepancies] == [DISCREPANCY_MISSING_POINT]
    assert result.discrepancies[0].point_date == D7


def test_review_splits_pending_work_from_faults(db_session):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7, D8))

    review, plan = review_persisted(db_session)

    assert review.ok is True
    assert review.faults == ()
    assert review.pending == (D7, D8)
    assert [p.point_date for p in plan.planned] == [D7, D8]
    # Nothing was thrown away: every discrepancy is accounted for on one side.
    assert len(review.pending) + len(review.faults) == len(
        review.verify.discrepancies
    )


def test_review_never_swallows_a_discrepancy_it_did_not_plan(
    db_session, monkeypatch
):
    """The classifier promotes exactly one kind, for exactly the dates the
    plan intends to write. Anything else stays a fault, even if it arrives at
    a date beyond the head."""
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    real = verify_persisted

    def noisier(db, seed=V1_OVERALL_SEED):
        result = real(db, seed)
        result.discrepancies.append(
            Discrepancy(
                kind="unexpected_point",
                scope_kind=SCOPE_OVERALL,
                scope_key="",
                point_date=D7,
                detail="synthetic",
            )
        )
        return result

    monkeypatch.setattr(
        "app.card_pirate_index_writer.verify_persisted", noisier
    )

    review, _ = review_persisted(db_session)

    assert review.pending == (D7,)
    assert [d.kind for d in review.faults] == ["unexpected_point"]
    assert review.ok is False


def test_verify_exits_non_zero_on_a_mismatch_in_persisted_history(
    cli, db_session, capsys
):
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    db_session.execute(
        update(CardPirateIndexPoint)
        .where(CardPirateIndexPoint.point_date == D4)
        .values(index_value=Decimal("1234.5678"))
    )
    db_session.commit()

    assert cli(["--verify"]) == 1
    assert "field_mismatch" in capsys.readouterr().err


def test_verify_exits_non_zero_on_a_hole_behind_the_head(cli, db_session, capsys):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        CardPirateIndexPoint.__table__.delete().where(
            CardPirateIndexPoint.point_date == D5
        )
    )
    db_session.commit()
    flat_archive(db_session, (D7,))

    assert cli(["--verify"]) == 1
    assert "missing_point" in capsys.readouterr().err


def test_verify_exits_non_zero_on_a_foreign_methodology_version(
    cli, db_session, capsys
):
    seed_staging_equivalent_head(db_session)
    db_session.add(
        CardPirateIndexPoint(
            scope_kind=SCOPE_OVERALL,
            scope_key="",
            methodology_version=METHODOLOGY_VERSION + 1,
            index_version=3,
            source_semantics_version=2,
            point_date=D7,
            index_value=BASE_VALUE,
            is_base=True,
            constituent_count=0,
            eligible_print_count=50,
            calculated_at=STAMP,
        )
    )
    db_session.commit()

    assert cli(["--verify"]) == 1
    assert "methodology_version" in capsys.readouterr().err


def test_verify_exits_non_zero_when_the_archive_no_longer_reaches_the_head(
    cli, db_session, capsys
):
    seed_staging_equivalent_head(db_session)
    db_session.execute(
        MarketIndexSnapshot.__table__.delete().where(
            MarketIndexSnapshot.snapshot_date >= D4
        )
    )
    db_session.commit()

    assert cli(["--verify"]) == 1
    assert "unavailable" in capsys.readouterr().err


def test_dry_run_exits_non_zero_when_the_extension_is_not_insertable(
    cli, db_session, capsys, monkeypatch
):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    monkeypatch.setattr(
        "app.card_pirate_index_writer.verify_planned_extension",
        lambda db, plan, seed=V1_OVERALL_SEED: ExtensionResult(
            scope_kind=SCOPE_OVERALL,
            scope_key="",
            planned_points=1,
            discrepancies=[
                Discrepancy(
                    kind=EXTENSION_CARRY_UNRESOLVABLE,
                    scope_kind=SCOPE_OVERALL,
                    scope_key="",
                    point_date=D7,
                    detail="synthetic",
                )
            ],
        ),
    )

    assert cli(["--dry-run"]) == 1
    assert "planned_extension_verified: False" in capsys.readouterr().out
    assert fingerprint(db_session) == before


def test_a_non_insertable_extension_stops_the_write_before_the_first_insert(
    db_session, monkeypatch
):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    def exploding_replay(db, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("replay_scope was reached despite a bad extension")

    monkeypatch.setattr(
        "app.card_pirate_index_writer.replay_scope", exploding_replay
    )
    monkeypatch.setattr(
        "app.card_pirate_index_writer.verify_planned_extension",
        lambda db, plan, seed=V1_OVERALL_SEED: ExtensionResult(
            scope_kind=SCOPE_OVERALL, scope_key="", planned_points=1,
            discrepancies=[
                Discrepancy(
                    kind=EXTENSION_CARRY_LEVEL_MISMATCH, scope_kind=SCOPE_OVERALL,
                    scope_key="", point_date=D7, stored=1, expected=2,
                )
            ],
        ),
    )

    with pytest.raises(WriterAbort) as exc:
        run_writer(db_session, calculated_at=STAMP, skip_lock=True)

    assert "not insertable" in str(exc.value)
    assert fingerprint(db_session) == before


def test_neither_read_only_command_creates_a_job_lock_row(cli, db_session):
    from app.models import JobLock

    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    assert cli(["--dry-run"]) == 0
    assert cli(["--verify"]) == 0

    assert db_session.scalars(select(JobLock)).all() == []


# --- the planned-extension checks themselves --------------------------------


def a_plan(*planned, head=D6, archive=D8):
    return WriterPlan(
        scope_kind=SCOPE_OVERALL,
        scope_key="",
        methodology_version=METHODOLOGY_VERSION,
        history_start=V1_OVERALL_SEED.history_start,
        latest_persisted_point_date=head,
        latest_archive_day=archive,
        stored_point_count=4,
        planned=tuple(planned),
    )


def a_point(point_date, **kw):
    fields = dict(
        point_date=point_date,
        index_value=Decimal("1000.9577"),
        is_base=False,
        carried_from_point_date=None,
        prior_point_date=point_date - timedelta(days=1),
        step_days=1,
        chain_link_log_return=Decimal("0.000000000000"),
        constituent_count=50,
        eligible_print_count=50,
        unpublishable_reason=None,
    )
    fields.update(kw)
    return PlannedPoint(**fields)


def kinds(db_session, plan):
    return [d.kind for d in verify_planned_extension(db_session, plan).discrepancies]


def test_extension_accepts_a_well_formed_plan(db_session):
    seed_staging_equivalent_head(db_session)
    assert kinds(db_session, a_plan(a_point(D7), a_point(D8))) == []


def test_extension_rejects_a_date_that_is_already_stored(db_session):
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_ALREADY_STORED in kinds(
        db_session, a_plan(a_point(D5), head=D4)
    )


def test_extension_rejects_a_date_at_or_behind_the_head(db_session):
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_NOT_AFTER_HEAD in kinds(db_session, a_plan(a_point(D6)))


def test_extension_rejects_points_out_of_order(db_session):
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_OUT_OF_ORDER in kinds(
        db_session, a_plan(a_point(D8), a_point(D7))
    )


def test_extension_rejects_a_point_the_archive_does_not_reach(db_session):
    """The one rule that stops a fabricated day: no archived snapshot, no
    point, no matter what else is coherent about it."""
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_BEYOND_ARCHIVE in kinds(
        db_session, a_plan(a_point(D8), archive=D7)
    )


def test_extension_rejects_a_carry_that_resolves_to_nothing(db_session):
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(
            D7, is_base=True, carried_from_point_date=date(2026, 9, 2),
            prior_point_date=None, step_days=None,
            chain_link_log_return=None, constituent_count=0,
        )
    )
    assert EXTENSION_CARRY_UNRESOLVABLE in kinds(db_session, plan)


def test_extension_rejects_a_carry_at_a_different_level(db_session):
    """Exactly what the composite carry foreign key refuses at INSERT time,
    caught before the INSERT rather than as an IntegrityError."""
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(
            D7, index_value=Decimal("1234.5678"), is_base=True,
            carried_from_point_date=D6, prior_point_date=None, step_days=None,
            chain_link_log_return=None, constituent_count=0,
        )
    )
    assert EXTENSION_CARRY_LEVEL_MISMATCH in kinds(db_session, plan)


def test_extension_accepts_a_carry_from_an_earlier_planned_point(db_session):
    """A catch-up spanning a version boundary carries from a row this same run
    is about to write, so the resolver has to see the plan, not just the
    table."""
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(D7, index_value=Decimal("1005.0000")),
        a_point(
            D8, index_value=Decimal("1005.0000"), is_base=True,
            carried_from_point_date=D7, prior_point_date=None, step_days=None,
            chain_link_log_return=None, constituent_count=0,
        ),
    )
    assert kinds(db_session, plan) == []


def test_extension_rejects_a_carry_that_does_not_move_forward(db_session):
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(D7, index_value=Decimal("1005.0000")),
        a_point(
            D8, index_value=Decimal("1005.0000"), is_base=True,
            carried_from_point_date=D8, prior_point_date=None, step_days=None,
            chain_link_log_return=None, constituent_count=0,
        ),
    )
    assert EXTENSION_CARRY_NOT_INCREASING in kinds(db_session, plan)


def test_extension_rejects_a_broken_value_reason_biconditional(db_session):
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_INCONSISTENT_UNPUBLISHABLE in kinds(
        db_session,
        a_plan(a_point(D7, unpublishable_reason="insufficient_constituents")),
    )


def test_extension_rejects_a_base_carrying_step_fields(db_session):
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(D7, is_base=True, carried_from_point_date=None)
    )
    assert EXTENSION_BASE_SHAPE in kinds(db_session, plan)


def test_extension_rejects_a_published_step_with_no_step(db_session):
    seed_staging_equivalent_head(db_session)
    assert EXTENSION_STEP_SHAPE in kinds(
        db_session, a_plan(a_point(D7, step_days=None))
    )


def test_extension_accepts_an_unpublishable_day(db_session):
    seed_staging_equivalent_head(db_session)
    plan = a_plan(
        a_point(
            D7, index_value=None,
            unpublishable_reason=UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS,
            chain_link_log_return=None, constituent_count=5,
        )
    )
    assert kinds(db_session, plan) == []


# --- concurrency ------------------------------------------------------------
#
# The lock is what stops two containers writing the same day. `acquire_lock`
# is non-blocking by design, so the second caller must FAIL, immediately and
# visibly, rather than wait its turn - and there is deliberately no retry
# anywhere in this module. A daily job that lost the race has nothing to do:
# the run that holds the lock is writing exactly the day it would have.


def test_the_write_path_holds_the_card_pirate_index_lock(db_session):
    from app.models import JobLock

    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    seen = {}
    real_replay = run_writer.__globals__["replay_scope"]

    def observing_replay(db, **kwargs):
        seen["locks"] = [
            (lock.lock_name, lock.status)
            for lock in db_session.scalars(select(JobLock))
        ]
        return real_replay(db, **kwargs)

    import app.card_pirate_index_writer as writer

    original = writer.replay_scope
    writer.replay_scope = observing_replay
    try:
        result = run_writer(db_session, calculated_at=STAMP)
    finally:
        writer.replay_scope = original

    assert result.inserted == 1
    assert seen["locks"] == [(LOCK_NAME, "active")]
    assert LOCK_NAME == "card_pirate_index"


def test_a_second_write_cannot_enter_while_the_lock_is_held(db_session):
    """Held by someone else, the second invocation never reaches the write
    transaction at all - proved by a replay that would fail the test if it
    ran - and raises LockHeldError rather than waiting."""
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    acquire_lock(LOCK_NAME, f"{LOCK_NAME}:someone-else", 600)

    import app.card_pirate_index_writer as writer

    original = writer.replay_scope

    def must_not_run(db, **kwargs):  # pragma: no cover - the point of the test
        raise AssertionError("entered the write transaction while locked out")

    writer.replay_scope = must_not_run
    try:
        with pytest.raises(LockHeldError) as exc:
            run_writer(db_session, calculated_at=STAMP)
    finally:
        writer.replay_scope = original

    assert exc.value.lock_name == LOCK_NAME
    assert fingerprint(db_session) == before


def test_the_locked_out_cli_exits_two_and_writes_nothing(cli, db_session, capsys):
    before = seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))
    acquire_lock(LOCK_NAME, f"{LOCK_NAME}:someone-else", 600)

    assert cli([]) == 2

    assert "Job already running: card_pirate_index" in capsys.readouterr().err
    assert fingerprint(db_session) == before


def test_a_serialised_second_run_adds_no_duplicate_row(db_session):
    """The lock serialises; idempotency is what makes the serialised second
    run harmless. Both properties are needed - a lock alone would leave a
    duplicate if the loser retried later, and this proves it does not."""
    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    first = run_writer(db_session, calculated_at=STAMP)
    after_first = fingerprint(db_session)
    second = run_writer(db_session, calculated_at=STAMP)

    assert (first.inserted, second.inserted) == (1, 0)
    assert fingerprint(db_session) == after_first
    assert [r.point_date for r in stored(db_session)] == [D3, D4, D5, D6, D7]


def test_the_lock_is_released_for_the_next_day(db_session):
    from app.models import JobLock

    seed_staging_equivalent_head(db_session)
    flat_archive(db_session, (D7,))

    run_writer(db_session, calculated_at=STAMP)

    active = [
        lock.status
        for lock in db_session.scalars(select(JobLock))
        if lock.lock_name == LOCK_NAME
    ]
    assert active == ["released"]


def test_the_writer_contains_no_retry(db_session):
    """No back-off, no re-acquire loop, no second attempt. A lost race is a
    no-op, not something to work around."""
    body = WRITER_SOURCE.split('"""', 2)[2]
    for forbidden in (r"\bretry\b", r"\bretries\b", r"\bsleep\b", r"\bbackoff\b",
                      r"\bwhile\s+True\b", r"\bfor\s+attempt\b"):
        assert not re.search(forbidden, body, re.IGNORECASE), forbidden
    # LockHeldError appears exactly twice - the import, and main()'s handler,
    # which prints and returns. It is never caught anywhere that could lead
    # back into another acquisition.
    assert WRITER_SOURCE.count("LockHeldError") == 2
    handler = WRITER_SOURCE.split("except LockHeldError", 1)[1].split("except", 1)[0]
    assert "run_writer" not in handler and "with_job_lock" not in handler
