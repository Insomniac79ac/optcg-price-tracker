"""Collector v1 S4: recorded collection value history and the day-one preview.

SQLite suite. The Postgres proofs (constraints, REPEATABLE READ, the producer
guard) are in test_collection_value_history_postgres.py.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction

import pytest
from sqlalchemy import DateTime, delete, select, update
from sqlalchemy.orm import sessionmaker

from app import market_index_daily_pipeline as pipeline
from app.accounts import valuation, value_history
from app.accounts.config import FLAG
from app.accounts.models import CollectionEntryEvent, CollectionValuePoint
from app.db import Base
from app.models import MarketIndexSnapshot, User
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_point import MarketValuePoint
from app.services.job_locks import with_job_lock
from app.services.print_market_index import get_market_index_for_prints
from app.snapshot_market_index import SnapshotRunResult, build_snapshot_row
from tests import _market_value_publication_helpers as mv_fixture
from tests.accounts_helpers import archive, hold, receipt
from tests._auth_helpers import TEST_USER_ID
from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_observation,
    make_print,
    make_release_product,
    make_source,
)

D0 = date(2026, 9, 1)


def day(n: int) -> date:
    return D0 + timedelta(days=n)


def cutoff(d: date) -> datetime:
    return datetime.combine(d, time(20, 2), tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_receipt_cache():
    valuation.clear_receipt_cache()
    yield
    valuation.clear_receipt_cache()


@pytest.fixture
def prints(db_session):
    make_release_product(db_session, "OP-02")
    made = {}
    for code, release in [("A", "OP-01"), ("B", "OP-01"), ("C", "OP-02"), ("D", "OP-02"), ("E", "OP-01")]:
        canonical = make_canonical(db_session, card_code=f"OP01-0{ord(code)}")
        made[code] = make_print(
            db_session, canonical, artwork_key=f"art-{code}", release_product_code=release
        ).id
    return made


def close_day(db, d: date, values: dict[int, int | None], *, receipted=True):
    """One archived day with a real receipt completed at 20:02 UTC that day."""
    archive(db, d, values, receipted=receipted)
    if receipted:
        db.execute(
            update(MarketIndexSnapshotCompletion)
            .where(MarketIndexSnapshotCompletion.snapshot_date == d)
            .values(completed_at=cutoff(d))
        )
        db.commit()


def second_user(db, sub="second") -> int:
    user = User(google_sub=sub, email=f"{sub}@example.com", name=sub)
    db.add(user)
    db.commit()
    return user.id


def stored(db, user_id=TEST_USER_ID) -> list[CollectionValuePoint]:
    db.expire_all()
    return value_history.list_points(db, user_id)


def run(db, d: date):
    valuation.clear_receipt_cache()
    return value_history.run_stage(db, d)


# --------------------------------------------------------------------------
# Oracle: an independent restatement of PLAN C3 with exact fractions.
# --------------------------------------------------------------------------


def oracle_held(events, at: datetime) -> dict[int, int]:
    held: dict[int, int] = {}
    for when, print_id, quantity in sorted(events, key=lambda e: e[0]):
        if when < at:
            held[print_id] = quantity
    return {p: q for p, q in held.items() if q > 0}


def oracle(prices, events, days):
    """prices: {day: {pid: value|None}} for receipted days. -> {day: dict}."""
    out = {}
    for d in days:
        held = oracle_held(events, cutoff(d))
        if not held:
            continue
        priced = {p: q for p, q in held.items() if prices[d].get(p)}
        value = sum(q * prices[d][p] for p, q in priced.items())
        point = {"value": value or None, "priced_cards": sum(priced.values()), "total": sum(held.values())}
        prior = d - timedelta(days=1)
        if prior in prices:
            before = oracle_held(events, cutoff(prior))
            prior_priced = sum(q * prices[prior][p] for p, q in before.items() if prices[prior].get(p))
            P = Q = 0
            for p in set(before) & set(held):
                if prices[prior].get(p) and prices[d].get(p):
                    units = min(before[p], held[p])
                    P += units * prices[prior][p]
                    Q += units * prices[d][p]
            ok = (
                P > 0
                and Fraction(P, prior_priced) >= Fraction(4, 5)
                and Fraction(Q, value) >= Fraction(4, 5)
            )
            point.update(P=P if P else None, Q=Q if P else None, ok=ok)
        else:
            point.update(P=None, Q=None, ok=False)
        out[d] = point
    return out


def oracle_pct(points, start: date, end: date) -> str | None:
    ratio = Fraction(1)
    d = start + timedelta(days=1)
    while d <= end:
        if d not in points or not points[d]["ok"]:
            return None
        ratio *= Fraction(points[d]["Q"], points[d]["P"])
        d += timedelta(days=1)
    if start not in points:
        return None
    with localcontext() as context:
        context.prec = 60
        pct = (Decimal(ratio.numerator) / Decimal(ratio.denominator) - 1) * 100
        return str(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def test_steps_and_windows_match_the_oracle(db_session, prints):
    A, B, C, D, E = (prints[k] for k in "ABCDE")
    other = second_user(db_session)
    prices = {}
    for n in range(12):
        prices[day(n)] = {
            A: 1000 + 37 * n,
            B: 5000 - 111 * n,
            C: 300 + (n % 3) * 50,
            D: 90 if n % 2 else None,  # unpriced on even days
            E: 40000 + 999 * n,
        }
    events = {TEST_USER_ID: [], other: []}

    def change(user, print_id, quantity, when, before=0):
        # A removal is a ledger event; the entry row itself is deleted by the API.
        hold(db_session, user, print_id, quantity, when, before=before, entry=quantity > 0)
        events[user].append((when, print_id, quantity))

    change(TEST_USER_ID, A, 2, cutoff(day(0)) - timedelta(hours=3))
    change(TEST_USER_ID, B, 1, cutoff(day(0)) - timedelta(hours=3))
    change(TEST_USER_ID, D, 1, cutoff(day(0)) - timedelta(hours=3))
    change(TEST_USER_ID, A, 3, cutoff(day(3)) - timedelta(hours=1), before=2)
    change(TEST_USER_ID, C, 4, cutoff(day(5)) - timedelta(minutes=1))
    change(TEST_USER_ID, B, 0, cutoff(day(7)) - timedelta(hours=5), before=1)
    # After the cutoff: belongs to the next day.
    change(TEST_USER_ID, C, 5, cutoff(day(9)) + timedelta(minutes=30), before=4)
    change(other, B, 1, cutoff(day(4)) - timedelta(hours=2))
    change(other, E, 1, cutoff(day(6)) - timedelta(hours=2))  # breaks the 80% guard

    for n in range(12):
        close_day(db_session, day(n), prices[day(n)])
        result = run(db_session, day(n))
        assert result.users == (2 if n >= 4 else 1)

    for user in (TEST_USER_ID, other):
        expected = oracle(prices, events[user], [day(n) for n in range(12)])
        points = {p.point_date: p for p in stored(db_session, user)}
        assert set(points) == set(expected)
        for d, want in expected.items():
            got = points[d]
            assert got.value_jpy == want["value"], d
            assert got.priced_cards == want["priced_cards"], d
            assert got.total_cards == want["total"], d
            assert got.step_publishable is want["ok"], (d, got.step_reason)
            if want["ok"]:
                assert (got.prior_comparable_jpy, got.current_comparable_jpy) == (want["P"], want["Q"])
        series = list(points.values())
        end = day(11)
        for window, start in (("7d", end - timedelta(days=7)), ("all", min(points))):
            got = value_history.recorded_change(series, window, end)
            want = oracle_pct(expected, start, end)
            assert got.change_pct == want, (user, window, got)
            assert got.available is (want is not None)
        thirty = value_history.recorded_change(series, "30d", end)
        assert not thirty.available and thirty.reason == "not_enough_history"

    # The other user's E purchase is a guard failure, not a gain.
    guard = {p.point_date: p for p in stored(db_session, other)}[day(6)]
    assert guard.step_publishable is False
    assert guard.step_reason == "insufficient_comparable_value_coverage"


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def test_quantity_changes_never_count_as_gain_or_loss(db_session, prints):
    A, B, C = prints["A"], prints["B"], prints["C"]
    flat = {A: 1000, B: 1200, C: 900}
    hold(db_session, TEST_USER_ID, A, 5, cutoff(day(0)) - timedelta(hours=1))
    hold(db_session, TEST_USER_ID, B, 5, cutoff(day(0)) - timedelta(hours=1))
    hold(db_session, TEST_USER_ID, C, 5, cutoff(day(0)) - timedelta(hours=1))
    for n in range(8):
        if n:
            # Every day the collection changes size, never the prices.
            hold(db_session, TEST_USER_ID, [A, B, C][n % 3], 5 + (1 if n % 2 else -1),
                 cutoff(day(n)) - timedelta(hours=1), before=5, entry=True)
        close_day(db_session, day(n), flat)
        run(db_session, day(n))
    points = stored(db_session)
    assert len({p.value_jpy for p in points}) > 1  # the total did move
    for point in points[1:]:
        assert point.step_publishable, point.step_reason
        assert point.prior_comparable_jpy == point.current_comparable_jpy
    change = value_history.recorded_change(points, "7d", day(7))
    assert change.available and change.change_pct == "0.00"


def test_a_missing_day_is_a_break_never_zero(db_session, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    for n in range(10):
        close_day(db_session, day(n), {A: 1000}, receipted=n != 6)  # day 6: no receipt
        if n != 6:
            run(db_session, day(n))
        else:
            with pytest.raises(value_history.StageAbort):
                run(db_session, day(n))
    points = {p.point_date: p for p in stored(db_session)}
    assert day(6) not in points
    after = points[day(7)]
    assert after.step_publishable is False and after.step_reason == "prior_day_missing"
    assert after.prior_point_date is None and after.prior_comparable_jpy is None
    assert after.segment_number == points[day(5)].segment_number + 1
    for window in ("7d", "all"):
        change = value_history.recorded_change(list(points.values()), window, day(9))
        assert not change.available and change.change_pct is None
        assert change.reason == "history_missing" and change.missing_dates == (day(6),)
    # Three receipted, continuous days after the break still chain.
    tail = value_history.recorded_change(list(points.values()), "all", day(9))
    assert tail.change_pct is None


def test_a_day_the_stage_did_not_run_is_also_a_break(db_session, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    for n in range(9):
        close_day(db_session, day(n), {A: 1000 + n})
        if n != 4:
            run(db_session, day(n))
    points = stored(db_session)
    # Day 5's own step is computed from the archive and is publishable ...
    assert {p.point_date: p for p in points}[day(5)].step_publishable
    # ... but the recorded window has a hole on day 4.
    change = value_history.recorded_change(points, "7d", day(8))
    assert change.reason == "history_missing" and change.missing_dates == (day(4),)


def test_eighty_percent_guard_with_no_minimum_card_count(db_session, prints):
    A, E = prints["A"], prints["E"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    for n in range(3):
        close_day(db_session, day(n), {A: 1000 + 10 * n, E: 9000})
        run(db_session, day(n))
    one_card = stored(db_session)
    # A single card is enough: Market Value's 300-version floor does not apply.
    assert one_card[-1].step_publishable and one_card[-1].comparable_cards == 1
    assert value_history.recorded_change(one_card, "all", day(2)).change_pct == "2.00"

    # 1000-yen comparable vs 1030 + 9000 priced today: below 80%.
    hold(db_session, TEST_USER_ID, E, 1, cutoff(day(3)) - timedelta(hours=1))
    close_day(db_session, day(3), {A: 1030, E: 9000})
    run(db_session, day(3))
    guarded = stored(db_session)[-1]
    assert guarded.step_publishable is False
    assert guarded.step_reason == "insufficient_comparable_value_coverage"
    assert guarded.value_jpy == 10030
    change = value_history.recorded_change(stored(db_session), "all", day(3))
    assert not change.available and change.failed_step_date == day(3)

    # Exactly 80% passes (>= rule): 4 x 1000 held vs 1 x 1000 added.
    other = second_user(db_session)
    B = prints["B"]
    hold(db_session, other, B, 4, cutoff(day(3)) - timedelta(hours=1))
    close_day(db_session, day(4), {A: 1030, E: 9000, B: 1000})
    run(db_session, day(4))
    hold(db_session, other, prints["C"], 1, cutoff(day(5)) - timedelta(hours=1))
    close_day(db_session, day(5), {A: 1030, E: 9000, B: 1000, prints["C"]: 1000})
    run(db_session, day(5))
    edge = stored(db_session, other)[-1]
    assert edge.step_publishable, edge.step_reason


def test_unpriced_cards_are_never_zero(db_session, prints):
    A, B = prints["A"], prints["B"]
    hold(db_session, TEST_USER_ID, A, 2, cutoff(day(0)) - timedelta(hours=1))
    close_day(db_session, day(0), {A: None, B: 500})
    run(db_session, day(0))
    point = stored(db_session)[0]
    assert point.value_jpy is None and point.priced_cards == 0 and point.total_cards == 2
    hold(db_session, TEST_USER_ID, B, 1, cutoff(day(1)) - timedelta(hours=1))
    close_day(db_session, day(1), {A: None, B: 500})
    run(db_session, day(1))
    point = stored(db_session)[-1]
    assert point.value_jpy == 500 and point.priced_cards == 1 and point.total_cards == 3
    assert point.step_publishable is False and point.step_reason == "no_comparable_cards"
    assert point.prior_comparable_jpy is None  # not a 0-yen comparable basket


def test_users_with_no_exact_cards_get_no_point(db_session, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    hold(db_session, TEST_USER_ID, A, 0, cutoff(day(1)) - timedelta(hours=1), before=1, entry=False)
    close_day(db_session, day(0), {A: 100})
    close_day(db_session, day(1), {A: 100})
    assert run(db_session, day(0)).inserted == 1
    assert run(db_session, day(1)).users == 0
    assert [p.point_date for p in stored(db_session)] == [day(0)]


@pytest.fixture
def sale_print(db_session):
    canonical = make_canonical(db_session, card_code="OP04-099")
    legacy = make_legacy_card(db_session, card_code="OP04-099")
    printing = make_print(db_session, canonical, artwork_key="art-sale")
    yuyu = make_source(db_session, "yuyutei")
    snkr = make_source(db_session, "snkrdunk")
    now = datetime.now(timezone.utc)
    make_observation(db_session, legacy, yuyu, make_mapping(db_session, legacy, yuyu, printing), printing,
                     price_jpy=80, promotion_state="sale", observed_at=now)
    make_observation(db_session, legacy, snkr, make_mapping(db_session, legacy, snkr, printing), printing,
                     price_type="floor", price_jpy=1500, observed_at=now)
    only = make_canonical(db_session, card_code="OP04-100")
    only_legacy = make_legacy_card(db_session, card_code="OP04-100")
    sale_only = make_print(db_session, only, artwork_key="art-sale-only")
    make_observation(db_session, only_legacy, yuyu, make_mapping(db_session, only_legacy, yuyu, sale_only),
                     sale_only, price_jpy=120, promotion_state="sale", observed_at=now)
    return printing, sale_only


def test_yuyu_sale_prices_are_excluded_from_recorded_points(db_session, sale_print):
    printing, sale_only = sale_print
    computed = get_market_index_for_prints(db_session, [printing.id, sale_only.id])
    rows = [build_snapshot_row(computed[p.id]) for p in (printing, sale_only)]
    for row in rows:
        db_session.add(MarketIndexSnapshot(**row))
    db_session.commit()
    today = rows[0]["snapshot_date"]
    hold(db_session, TEST_USER_ID, printing.id, 2, datetime.now(timezone.utc) - timedelta(minutes=5))
    hold(db_session, TEST_USER_ID, sale_only.id, 1, datetime.now(timezone.utc) - timedelta(minutes=5))
    receipt(db_session, today)  # completed now, after the holdings
    run(db_session, today)
    point = stored(db_session)[0]
    assert point.value_jpy == 3000  # 2 x SNKRDUNK floor; never the 80 or 120 sale
    assert point.priced_cards == 2 and point.total_cards == 3


# --------------------------------------------------------------------------
# Idempotency and fail-closed conflicts
# --------------------------------------------------------------------------


def test_rerun_is_idempotent_and_ignores_later_changes(db_session, prints):
    A, B = prints["A"], prints["B"]
    second_user(db_session)
    hold(db_session, TEST_USER_ID, A, 2, cutoff(day(0)) - timedelta(hours=1))
    close_day(db_session, day(0), {A: 1000, B: 300})
    first = run(db_session, day(0))
    before = [(p.point_date, p.value_jpy, p.created_at) for p in stored(db_session)]
    # A change after the receipt cutoff belongs to tomorrow.
    hold(db_session, TEST_USER_ID, B, 3, datetime.now(timezone.utc))
    second = run(db_session, day(0))
    assert (first.inserted, first.existing) == (1, 0)
    assert (second.inserted, second.existing) == (0, 1)
    assert [(p.point_date, p.value_jpy, p.created_at) for p in stored(db_session)] == before


def test_a_contradicting_stored_point_fails_closed(db_session, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 2, cutoff(day(0)) - timedelta(hours=1))
    close_day(db_session, day(0), {A: 1000})
    run(db_session, day(0))
    db_session.execute(update(CollectionValuePoint).values(value_jpy=1))
    db_session.commit()
    with pytest.raises(value_history.CollectionValuePointConflict, match="value_jpy"):
        run(db_session, day(0))
    assert stored(db_session)[0].value_jpy == 1  # nothing rewritten


def test_rollback_by_methodology_version_removes_only_s4_rows(db_session, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    close_day(db_session, day(0), {A: 1000})
    run(db_session, day(0))
    db_session.execute(
        delete(CollectionValuePoint).where(
            CollectionValuePoint.methodology_version == value_history.METHODOLOGY_VERSION
        )
    )
    db_session.commit()
    assert stored(db_session) == []
    assert db_session.scalar(select(CollectionEntryEvent.id)) is not None


# --------------------------------------------------------------------------
# Pipeline: an independent last stage
# --------------------------------------------------------------------------


def _snapshot_result():
    d = mv_fixture.D29
    return SnapshotRunResult(
        snapshot_date=d,
        calculated_at=datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc),
        prints_selected=4,
        rows_created=0,
        rows_skipped_existing=4,
        dry_run=False,
        completion_status="verified_existing",
        completion_verified=True,
    )


def _fresh_pipeline_world(engine, monkeypatch, *, collectors: bool):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    db.add(User(id=TEST_USER_ID, google_sub="pipeline", email="p@example.com", name="p"))
    db.commit()
    mv_fixture.seed(db)
    if collectors:
        other = second_user(db)
        hold(db, TEST_USER_ID, 1, 2, mv_fixture.stamp(mv_fixture.D28) - timedelta(hours=1))
        hold(db, other, 3, 1, mv_fixture.stamp(mv_fixture.D29) - timedelta(hours=1))
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(
        pipeline.snapshot_market_index, "snapshot_market_index", lambda db: _snapshot_result()
    )
    valuation.clear_receipt_cache()
    return db


def _index_outputs(db):
    """Every stored column except run-time timestamps."""
    out = {}
    for name, model in (("market_value", MarketValuePoint), ("card_pirate_index", CardPirateIndexPoint)):
        columns = [c for c in model.__table__.columns if not isinstance(c.type, DateTime)]
        out[name] = tuple(tuple(row) for row in db.execute(select(*columns).order_by(model.id)))
    db.rollback()
    return out


def _no_stage(db, d, **kwargs):
    return value_history.StageResult(point_date=d, users=0, inserted=0, existing=0)


def _broken_stage(db, d, **kwargs):
    raise RuntimeError("collection history unavailable")


@pytest.mark.parametrize(
    "variant", ["real_with_collectors", "real_without_collectors", "failing", "locked"]
)
def test_market_value_and_index_outputs_are_unchanged_by_the_stage(db_session, monkeypatch, variant):
    """Fixture comparison: MV and CPI rows, statuses and counts with the stage
    stubbed out (the pre-S4 pipeline) equal those with the stage present,
    failing or locked."""
    engine = db_session.get_bind()
    _fresh_pipeline_world(engine, monkeypatch, collectors=True)
    real_stage = value_history.run_stage
    monkeypatch.setattr(value_history, "run_stage", _no_stage)
    baseline = pipeline.run_pipeline()
    with sessionmaker(bind=engine)() as db:
        baseline_rows = _index_outputs(db)

    db = _fresh_pipeline_world(engine, monkeypatch, collectors=variant != "real_without_collectors")
    monkeypatch.setattr(value_history, "run_stage", _broken_stage if variant == "failing" else real_stage)
    if variant == "locked":
        with with_job_lock(value_history.LOCK_NAME):
            result = pipeline.run_pipeline()
    else:
        result = pipeline.run_pipeline()
    with sessionmaker(bind=engine)() as fresh:
        assert _index_outputs(fresh) == baseline_rows
    assert result.market_value == baseline.market_value
    assert result.card_pirate_index == baseline.card_pirate_index
    assert baseline.market_value.inserted == 2 and baseline.card_pirate_index.inserted > 0

    stage = result.collection_value
    if variant == "real_with_collectors":
        assert (stage.status, stage.inserted, stage.dates) == ("succeeded", 2, (mv_fixture.D29,))
        assert result.exit_code == 0
    elif variant == "real_without_collectors":
        # Staging today: no users, so the stage reports a no-op and writes 0 rows.
        assert (stage.status, stage.inserted) == ("no_op", 0)
        assert result.exit_code == 0
    elif variant == "failing":
        assert stage.status == "failed" and stage.reason == "collection history unavailable"
        assert result.exit_code == 1
    else:
        assert stage.status == "locked" and result.exit_code == 2
    db.close()


def test_report_lists_the_stage_and_gate_failure_skips_it(db_session, monkeypatch, capsys):
    db = _fresh_pipeline_world(db_session.get_bind(), monkeypatch, collectors=False)
    assert pipeline.main() == 0
    report = capsys.readouterr().out
    assert '"collection_value": {"dates": ["2026-09-29"], "inserted": 0, "reason": null, "status": "no_op"}' in report
    db.execute(delete(MarketIndexSnapshotCompletion).where(MarketIndexSnapshotCompletion.snapshot_date == mv_fixture.D29))
    db.commit()
    result = pipeline.run_pipeline()
    assert result.receipt.status == "failed"
    assert result.collection_value.status == "skipped"
    db.close()


def test_stage_rerun_through_the_pipeline_is_a_no_op(db_session, monkeypatch):
    db = _fresh_pipeline_world(db_session.get_bind(), monkeypatch, collectors=True)
    first = pipeline.run_pipeline()
    valuation.clear_receipt_cache()
    second = pipeline.run_pipeline()
    assert first.collection_value.inserted == 2
    assert second.collection_value.status == "no_op" and second.collection_value.inserted == 0
    db.close()


# --------------------------------------------------------------------------
# API: 7D / 30D / ALL and the labelled preview
# --------------------------------------------------------------------------


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(FLAG, "true")


def test_value_endpoint_reads_recorded_history_and_a_labelled_preview(client, db_session, enabled, prints):
    A, B = prints["A"], prints["B"]
    hold(db_session, TEST_USER_ID, A, 2, cutoff(day(0)) - timedelta(hours=1))
    hold(db_session, TEST_USER_ID, B, 1, cutoff(day(0)) - timedelta(hours=1))
    for n in range(32):
        close_day(db_session, day(n), {A: 1000 + 10 * n, B: 2000})
        if n >= 29:  # the collection's own history starts on day 29
            run(db_session, day(n))
    valuation.clear_receipt_cache()

    body = client.get("/me/collection/value", params={"window": "all"}).json()
    assert body["window"] == "all" and body["as_of"] == day(31).isoformat()
    history = body["history"]
    assert history["kind"] == "recorded"
    assert [p["date"] for p in history["points"]] == [day(n).isoformat() for n in (29, 30, 31)]
    expected = Fraction(2 * 1310 + 2000, 2 * 1290 + 2000) - 1
    assert history["change"]["available"] is True
    assert Decimal(history["change"]["change_pct"]) == round(Decimal(expected.numerator * 100) / expected.denominator, 2)
    assert body["movers"]["from_date"] == day(29).isoformat()

    seven = client.get("/me/collection/value", params={"window": "7d"}).json()["history"]
    assert seven["change"]["available"] is False
    assert seven["change"]["reason"] == "not_enough_history"
    assert seven["change"]["change_pct"] is None

    preview = body["preview"]
    assert preview["kind"] == "preview"
    assert "Preview" in preview["label"] and "not your collection's recorded history" in preview["label"]
    assert preview["from_date"] == day(1).isoformat() and preview["to_date"] == day(31).isoformat()
    assert len(preview["points"]) == 31 and preview["total_cards"] == 3
    assert preview["change"]["available"] is True
    assert preview["change"]["change_pct"] == value_history.percent_from_ratio(2 * 1310 + 2000, 2 * 1010 + 2000)


def test_preview_breaks_on_a_missing_day_and_history_is_empty_on_day_one(client, db_session, enabled, prints):
    A = prints["A"]
    hold(db_session, TEST_USER_ID, A, 1, cutoff(day(0)) - timedelta(hours=1))
    for n in range(32):
        close_day(db_session, day(n), {A: 1000 + n}, receipted=n != 20)
    body = client.get("/me/collection/value", params={"window": "30d"}).json()
    assert body["history"]["points"] == []
    assert body["history"]["change"]["reason"] == "not_enough_history"
    preview = body["preview"]
    assert day(20).isoformat() not in [p["date"] for p in preview["points"]]
    assert preview["change"]["available"] is False
    assert preview["change"]["reason"] == "history_missing"
    assert preview["change"]["missing_dates"] == [day(20).isoformat()]


def test_value_endpoint_with_no_cards_or_prices(client, db_session, enabled):
    body = client.get("/me/collection/value", params={"window": "all"}).json()
    assert body["history"]["change"]["reason"] == "no_prices_yet"
    assert body["preview"]["change"]["reason"] == "no_prices_yet"
    assert body["preview"]["points"] == []
