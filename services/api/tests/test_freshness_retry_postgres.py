"""Advancing-clock simulations, never measurements of source throughput."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    FreshnessPriceState,
    FreshnessWork,
    RawSnapshot,
    SourceCardMapping,
)
from test_freshness_queue_postgres import (
    T0,
    URL,
    db,
    plan,
    claim,
    admit,
    finish,
    observation,
    mapping,
)


from freshness_offline import offline_only


def capture(factory, source, job, at, outcomes):
    admit(factory, job.claim_token, at)
    with factory.begin() as session:
        mapping = session.get(SourceCardMapping, job.source_card_mapping_id)
        raw = RawSnapshot(
            source_id=source,
            source_url=mapping.source_url,
            fetched_at=at,
            http_status=200,
            content_hash="a" * 64,
            raw_content="synthetic category fixture",
        )
        session.add(raw)
        session.flush()
        raw_id = raw.id
    ids = {
        category: observation(
            factory, job.source_card_mapping_id, raw_id, at, category=category
        )
        for category, outcome in outcomes.items()
        if outcome == "captured"
    }
    unlisted = {
        category for category, outcome in outcomes.items() if outcome == "no_listing"
    }
    result = dict(
        outcome=(
            "captured" if ids else "no_listing" if unlisted else "transient_failure"
        ),
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        observation_ids=ids,
        no_listing_categories=unlisted,
        category_outcomes=outcomes,
    )
    assert finish(factory, job.claim_token, at, **result)
    # Redelivery after a new worker/session must not change retry state or prices.
    assert not finish(factory, job.claim_token, at, **result)


def simulate(factory, source, outcomes, *, hours=48):
    times = []
    # Inclusive [0h,48h], dispatch every 15m, fresh sessions on every operation.
    for tick in range(hours * 4 + 1):
        at = T0 + timedelta(minutes=tick * 15)
        jobs = claim(factory, source, at, owner=f"restarted-worker-{tick}")
        for job in jobs:
            capture(factory, source, job, at, outcomes)
            times.append(tick / 4)
    return times


@pytest.mark.parametrize("missing", ["raw", "psa10"])
@pytest.mark.parametrize("failure", ["absent", "parsing_failure"])
def test_persistent_absence_advancing_clock(db, missing, failure):
    factory, source, mapping_id, _ = db
    work_id = plan(factory, mapping_id, categories={"raw", "psa10"})
    outcomes = {
        category: failure if category == missing else "captured"
        for category in ("raw", "psa10")
    }
    times = simulate(factory, source, outcomes)
    print(
        f"SIMULATED missing={missing}, failure={failure}: captures={len(times)}, hours={times}"
    )
    assert times == (
        [0, 23, 46]
        if failure == "absent"
        else [0, 0.25, 0.75, 1.75, 3.75, 7.75, 15.75, 31.75]
    )
    with factory() as session:
        state = session.scalar(
            select(FreshnessPriceState).where(
                FreshnessPriceState.work_id == work_id,
                FreshnessPriceState.price_category == missing,
            )
        )
        assert state.next_due_at == T0
        assert state.last_valid_price_observed_at is None
        assert state.availability == "unknown"


def test_mixed_population_48_hours(db):
    from collections import Counter
    from app.services.freshness_queue import plan_discovery_scope

    factory, source, mid, print_id = db
    kinds = {}
    old = T0 - timedelta(hours=23)
    for index in range(8):
        product = mid if index == 0 else mapping(factory, source, print_id, 123 + index)
        kind = "affected" if index < 3 else "ordinary" if index < 6 else "coverage"
        work = plan(factory, product, categories={"raw", "psa10"}, at=old)
        kinds[work] = kind
        if kind != "coverage":
            job = claim(factory, source, old)[0]
            capture(factory, source, job, old, {"raw": "captured", "psa10": "captured"})
    with factory.begin() as session:
        for index in range(2):
            work = plan_discovery_scope(session, source, f"fixture-{index}", due_at=T0)
            kinds[work.id] = "discovery"
    counts = Counter()
    product_times = {}
    for tick in range(193):
        at = T0 + timedelta(minutes=15 * tick)
        for job in claim(factory, source, at, owner=f"restart-{tick}"):
            kind = kinds[job.work_id]
            counts[kind] += 1
            product_times.setdefault(job.work_id, []).append(tick / 4)
            if kind == "discovery":
                admit(factory, job.claim_token, at)
                from test_freshness_queue_postgres import snapshot

                raw = snapshot(factory, source, at)
                finish(
                    factory,
                    job.claim_token,
                    at,
                    outcome="completed",
                    actual_request_cost=1,
                    raw_snapshot_id=raw,
                    next_due_at=at + timedelta(hours=23),
                )
            else:
                capture(
                    factory,
                    source,
                    job,
                    at,
                    {
                        "raw": "captured",
                        "psa10": "absent" if kind == "affected" else "captured",
                    },
                )
    print(f"SIMULATED mixed population: {dict(counts)}")
    assert counts == {"affected": 9, "ordinary": 8, "coverage": 6, "discovery": 6}
    for work, times in product_times.items():
        assert times[0] <= 2.5  # first coverage and ordinary/discovery all served
        assert max(b - a for a, b in zip(times, times[1:])) <= 25.5
        assert times[-1] + 25.5 > 48  # no catalogue tail forgotten/starved

    from app.services.freshness_integration import price_facts

    with factory() as session:
        for work, kind in kinds.items():
            if kind == "affected":
                facts = {
                    r["category"]: r
                    for r in price_facts(
                        session, work, clock=lambda: T0 + timedelta(hours=48)
                    )
                }
                assert facts["psa10"]["captured_at"] == old
                assert facts["psa10"]["checked_at"] == old
                assert facts["psa10"]["next_due_at"] == T0
                assert facts["psa10"]["category_outcome"] == "absent"
                assert facts["psa10"]["freshness"] == "stale"
                assert facts["psa10"]["availability"] == "listed"


@pytest.mark.parametrize("high,interval", [(False, 23), (True, 3)])
def test_absent_category_appears_after_restart_and_replanning(db, high, interval):
    factory, source, mid, _ = db
    work = plan(factory, mid, categories={"raw", "psa10"}, high=high)
    times = []
    for tick in range(193):
        at = T0 + timedelta(minutes=15 * tick)
        # Continuous demand reconciliation must preserve durable retry state.
        plan(factory, mid, categories={"raw", "psa10"}, high=high, at=at)
        for job in claim(factory, source, at):
            capture(
                factory,
                source,
                job,
                at,
                {"raw": "captured", "psa10": "absent" if tick == 0 else "captured"},
            )
            times.append(tick / 4)
    assert times == list(range(0, 49, interval))
    with factory() as session:
        states = list(session.scalars(select(FreshnessPriceState)))
        assert all(
            s.consecutive_failures == 0 and s.retry_not_before_at is None
            for s in states
        )
        assert all(
            s.last_valid_price_observed_at == T0 + timedelta(hours=times[-1])
            for s in states
        )


@pytest.mark.parametrize("missing", ["raw", "psa10"])
def test_failure_streak_recovery_and_another_category_deadline(db, missing):
    factory, source, mid, _ = db
    other = "psa10" if missing == "raw" else "raw"
    work = plan(factory, mid, categories={"raw", "psa10"})
    # Establish genuine old evidence, then fail one category. Only that category
    # retains its overdue deadline and old price while the other succeeds.
    capture(
        factory,
        source,
        claim(factory, source)[0],
        T0,
        {"raw": "captured", "psa10": "captured"},
    )
    times = []
    for tick in range(23 * 4, 48 * 4 + 1):
        at = T0 + timedelta(minutes=15 * tick)
        # New demand can become due inside a long category retry delay. Use the
        # existing other category's legitimate deadline (no evidence rewrite).
        if tick == 31 * 4:
            with factory.begin() as session:
                from app.services.freshness_queue import plan_refresh

                # Interest escalation brings the last healthy capture's deadline
                # forward; the absent category must not impose its later gate.
                plan_refresh(
                    session, mid, {"raw", "psa10"}, high_interest=True, clock=lambda: at
                )
        for job in claim(factory, source, at):
            capture(
                factory,
                source,
                job,
                at,
                {
                    other: "captured",
                    missing: (
                        "parsing_failure"
                        if at < T0 + timedelta(hours=35)
                        else "captured"
                    ),
                },
            )
            times.append(tick / 4)
            with factory() as session:
                state = session.scalar(
                    select(FreshnessPriceState).where(
                        FreshnessPriceState.price_category == missing
                    )
                )
                if at < T0 + timedelta(hours=35):
                    assert state.last_valid_price_observed_at == T0
                    assert state.next_due_at == T0 + timedelta(
                        hours=3 if at >= T0 + timedelta(hours=31) else 23
                    )
                    assert state.consecutive_failures == min(len(times), 8)
                else:
                    assert state.consecutive_failures == 0
                    assert state.retry_not_before_at is None
    assert times[:6] == [23, 23.25, 23.75, 24.75, 26.75, 30.75]
    # Healthy category last checked 30.75h, due at 33.75h with high-interest.
    # Failed category's existing retry was 38.75h, clamped at escalation to34h.
    assert times[6:] == [33.75, 36.75, 39.75, 42.75, 45.75]


def test_transient_failures_without_page_use_durable_bounded_streaks(db):
    factory, source, mid, _ = db
    plan(factory, mid, categories={"raw", "psa10"})
    times = []
    for tick in range(193):
        at = T0 + timedelta(minutes=tick * 15)
        for job in claim(factory, source, at):
            admit(factory, job.claim_token, at)
            result = dict(outcome="transient_failure", actual_request_cost=1)
            assert finish(factory, job.claim_token, at, **result)
            assert not finish(factory, job.claim_token, at, **result)
            times.append(tick / 4)
    assert times == [0, 0.25, 0.75, 1.75, 3.75, 7.75, 15.75, 31.75]
    with factory() as session:
        for state in session.scalars(select(FreshnessPriceState)):
            assert state.consecutive_failures == 8
            assert state.retry_not_before_at == T0 + timedelta(hours=54.75)
            assert state.next_due_at == T0
            assert state.last_valid_price_observed_at is None


@pytest.mark.parametrize("restore_version", [17, 18, 19])
def test_retry_backup_preserves_streaks_and_legacy_archives(db, restore_version):
    from copy import deepcopy
    from app.services.backup import export_backup, restore_backup, validate_backup
    from app.services.freshness_backup import prepare_restore

    factory, source, mid, _ = db
    plan(factory, mid, categories={"raw", "psa10"})
    capture(
        factory,
        source,
        claim(factory, source)[0],
        T0,
        {"raw": "captured", "psa10": "parsing_failure"},
    )
    with factory() as session:
        archive = export_backup(
            session, include_prices=True, include_raw_snapshots=True
        )
    assert archive["metadata"]["backup_version"] == 19
    assert validate_backup(archive).valid
    restored, _ = prepare_restore(archive["tables"], T0)
    assert (
        restored["freshness_price_states"]
        == archive["tables"]["freshness_price_states"]
    )
    failed = next(
        s for s in restored["freshness_price_states"] if s["price_category"] == "psa10"
    )
    assert failed["consecutive_failures"] == 1
    assert failed["retry_not_before_at"] is not None
    for value in [-1, 9, True]:
        bad = deepcopy(archive)
        bad["tables"]["freshness_price_states"][0]["consecutive_failures"] = value
        assert not validate_backup(bad).valid
    for version in (16, 17):
        old = deepcopy(archive)
        old["metadata"]["backup_version"] = version
        for state in old["tables"]["freshness_price_states"]:
            del state["consecutive_failures"], state["retry_not_before_at"]
        assert validate_backup(old).valid

    from app.db import Base
    from app.models import SourceDispatchBudget

    to_restore = deepcopy(archive)
    to_restore["metadata"]["backup_version"] = restore_version
    if restore_version < 19:
        to_restore["tables"].pop("raw_snapshot_dictionaries", None)
    if restore_version < 18:
        for state in to_restore["tables"]["freshness_price_states"]:
            del state["consecutive_failures"], state["retry_not_before_at"]
    assert validate_backup(to_restore).valid
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with factory() as session:
        result = restore_backup(
            session,
            to_restore,
            dry_run=False,
            mode="replace",
            confirm="RESTORE",
            skip_lock=True,
        )
        assert result.valid, result.errors
    with factory() as session:
        state = session.scalar(
            select(FreshnessPriceState).where(
                FreshnessPriceState.price_category == "psa10"
            )
        )
        assert state.consecutive_failures == (1 if restore_version >= 18 else None)
        assert state.retry_not_before_at == (
            T0 + timedelta(minutes=15) if restore_version >= 18 else None
        )
        assert not session.scalar(select(SourceDispatchBudget.enabled))


@pytest.mark.parametrize("missing", ["raw", "psa10"])
def test_persistent_absence_high_interest_48_hours(db, missing):
    factory, source, mid, _ = db
    plan(factory, mid, categories={"raw", "psa10"}, high=True)
    times = simulate(
        factory,
        source,
        {c: "absent" if c == missing else "captured" for c in ("raw", "psa10")},
    )
    assert times == list(range(0, 49, 3))


def test_new_category_demand_during_retry_delay_is_immediate(db):
    factory, source, mid, _ = db
    plan(factory, mid, categories={"raw"})
    capture(factory, source, claim(factory, source)[0], T0, {"raw": "absent"})
    at = T0 + timedelta(hours=1)
    plan(factory, mid, categories={"psa10"}, at=at)
    jobs = claim(factory, source, at)
    assert len(jobs) == 1 and jobs[0].price_categories == ("psa10", "raw")
    capture(factory, source, jobs[0], at, {"raw": "absent", "psa10": "captured"})
    assert claim(factory, source, at) == []


def test_offline_boundary_blocks_real_transports_and_nonlocal_db():
    import socket
    import urllib.request
    import httpx
    import psycopg
    from playwright.sync_api import sync_playwright

    with pytest.raises(AssertionError, match="blocked"):
        httpx.get("https://source.invalid/")
    with pytest.raises(AssertionError, match="blocked"):
        urllib.request.urlopen("https://source.invalid/")
    with pytest.raises(AssertionError, match="blocked"):
        socket.getaddrinfo("source.invalid", 443)
    with pytest.raises(AssertionError, match="blocked"):
        with socket.socket() as sock:
            sock.connect(("192.0.2.1", 443))
    with pytest.raises(AssertionError, match="blocked"):
        sync_playwright().start()
    with pytest.raises(AssertionError, match="blocked"):
        psycopg.connect(host="source.invalid", dbname="opcg_test")
