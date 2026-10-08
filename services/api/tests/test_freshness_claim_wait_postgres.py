"""Bounded contention recovery with mock outcomes and disposable localhost DB."""

from datetime import timedelta
from types import SimpleNamespace
from collections import defaultdict

import pytest
from sqlalchemy import func, select

from test_freshness_queue_postgres import db, T0, plan
from app.models import (
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_integration import CaptureResult, _drain
from app.services.freshness_queue import claim_due, complete_claim, plan_discovery_scope


def occupied(db):
    factory, source, mapping, _ = db
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        session.flush()
        session.get(SourceCardMapping, mapping).source_url = (
            "https://yuyu-tei.jp/sell/opc/card/op01/10001"
        )
        for i in range(4):
            plan_discovery_scope(
                session, source, f"held:{i}", due_at=T0, estimated_request_cost=10
            )
    with factory.begin() as session:
        holders = claim_due(
            session,
            source,
            "existing",
            limit=4,
            lease=timedelta(minutes=3),
            clock=lambda: T0,
            supported_kinds={"discovery"},
        )
    assert len(holders) == 4
    own = plan(factory, mapping, cost=20)
    return factory, source, mapping, own, holders


@pytest.mark.parametrize(
    "case",
    [
        "released",
        "held",
        "deadline",
        "disabled",
        "ownership_lost",
        "unsharded",
        "disabled_on_retry",
        "empty",
        "unaffordable",
        "wrong_shard",
    ],
)
def test_wait_never_bypasses_claim_budget_ownership_or_deadline(db, case):
    factory, source, mapping, own, holders = occupied(db)
    elapsed = [0]
    waits, calls, checks = [], [], []
    telemetry = defaultdict(int)
    if case == "disabled":
        with factory.begin() as session:
            session.get(SourceDispatchBudget, source).enabled = False
    if case in {"empty", "unaffordable"}:
        with factory.begin() as session:
            if case == "empty":
                session.get(FreshnessWork, own).state = "blocked"
            else:
                session.get(SourceDispatchBudget, source).request_limit = 40

    def sleep(seconds):
        if not seconds:
            return
        waits.append(seconds)
        elapsed[0] += seconds
        if case in {"released", "disabled_on_retry"}:
            with factory.begin() as session:
                complete_claim(
                    session,
                    holders[0].claim_token,
                    outcome="transient_failure",
                    actual_request_cost=0,
                    clock=lambda: T0 + timedelta(seconds=elapsed[0]),
                )
                if case == "disabled_on_retry":
                    session.get(SourceDispatchBudget, source).enabled = False

    def ownership(session):
        checks.append(elapsed[0])
        if case == "ownership_lost" and elapsed[0]:
            raise RuntimeError("mock owner lost")

    def runner(session, mapping_id, *, freshness):
        calls.append(mapping_id)
        assert (
            session.scalar(
                select(func.count())
                .select_from(FreshnessWork)
                .where(FreshnessWork.state == "claimed")
            )
            <= 4
        )
        freshness.result = CaptureResult(
            "transient_failure", failure="mock no transport"
        )
        return SimpleNamespace(source_denied=False, reasons=[], stage="mock")

    with factory() as session:
        kwargs = dict(
            runtime_seconds=182 if case == "deadline" else 1020,
            mapping_seconds=180,
            shard_index=(
                None if case == "unsharded" else (mapping + (case == "wrong_shard")) % 9
            ),
            max_work=1,
            delay_seconds=0,
            clock=lambda: T0 + timedelta(seconds=elapsed[0]),
            monotonic=lambda: elapsed[0],
            sleep=sleep,
            ownership_check=ownership,
            telemetry=telemetry,
        )
        if case == "ownership_lost":
            with pytest.raises(RuntimeError, match="owner lost"):
                _drain(session, source, "waiting", runner, **kwargs)
        else:
            result = _drain(session, source, "waiting", runner, **kwargs)
            assert len(result) == (1 if case == "released" else 0)
    assert calls == ([mapping] if case == "released" else [])
    expected_waits = (
        [5] * 6
        if case == "held"
        else [5] if case in {"released", "ownership_lost", "disabled_on_retry"} else []
    )
    assert waits == expected_waits
    assert sum(waits) <= 30
    with factory() as session:
        work = session.get(FreshnessWork, own)
        assert work.attempt_count == (1 if case == "released" else 0)
        assert work.state == ("blocked" if case == "empty" else "pending")
        price_state = session.scalar(
            select(FreshnessPriceState).where(FreshnessPriceState.work_id == own)
        )
        assert price_state.last_successfully_checked_at is None
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        reserved = session.scalar(select(SourceDispatchBudget.reserved_requests))
        assert reserved == (30 if case in {"released", "disabled_on_retry"} else 40)
        unfinished = session.scalar(
            select(func.count())
            .select_from(FreshnessAttempt)
            .where(FreshnessAttempt.outcome.is_(None))
        )
        assert unfinished == (3 if case in {"released", "disabled_on_retry"} else 4)
