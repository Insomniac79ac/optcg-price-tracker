"""Reconstruct retained execution evidence using mock captures and local PG only."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select, text
from freshness_offline import offline_only
from test_freshness_queue_postgres import db, mapping, plan
from app.models import (
    AppLogEvent,
    FreshnessAttempt,
    FreshnessWork,
    SourceDispatchBudget,
)
from app.services.freshness_integration import drain, CaptureResult
from app.services.operational_health import classify, validate
from app.services.operational_health_sql import DUE_SQL, EVENT_SQL


def test_execution_evidence_survives_completion_and_enforces_total_bound(
    db, monkeypatch
):
    factory, source, mid, pid = db
    now = datetime.now(timezone.utc)
    mids = [mid, mapping(factory, source, pid, 456), mapping(factory, source, pid, 789)]
    for item in mids:
        plan(factory, item, at=now)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "05d1eac2-510d-4bd3-999e-fea9ead766b7")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "fixture-deployment")
    calls = []

    def runner(session, mapping_id, *, freshness):
        calls.append(mapping_id)
        freshness.admit()
        freshness.result = CaptureResult(
            "transient_failure", category_outcomes={"raw": "parsing_failure"}
        )
        return SimpleNamespace(
            stage="transient_failure",
            source_denied=False,
            reasons=[],
            classification=None,
        )

    with factory() as session:
        result = drain(
            session,
            source,
            "snkrdunk-due",
            runner,
            runtime_seconds=100,
            mapping_seconds=1,
            max_work=2,
            delay_seconds=0,
            sleep=lambda _: None,
            clock=lambda: now,
        )
    assert len(result) == len(calls) == 2
    with factory() as session:
        events = session.scalars(select(AppLogEvent).order_by(AppLogEvent.id)).all()
        assert [e.event_type for e in events] == [
            "raw_execution_started",
            "raw_execution_finished",
        ]
        summary = events[-1].context_json
        validate(summary)
        assert summary["work"]["claimed"] == 2
        assert summary["failure"]["parsing"] == 2
        assert summary["safety"]["reservations_remaining"] == 0
        assert summary["safety"]["claims_remaining"] == 0
        assert summary["exit"]["stopped_reason"] == "work_bound"
        assert summary["identity"]["trigger"] == "unknown"
        assert summary["identity"]["scheduled_at"] is None
        assert summary["exit"]["exit_code"] is None
        assert classify(summary)["status"] == "DEGRADED"
        assert len(set(session.scalars(select(FreshnessAttempt.claimed_by)))) == 1
        assert summary["identity"]["execution_id"] == session.scalar(
            select(FreshnessAttempt.claimed_by)
        )
        rows = session.execute(text(DUE_SQL)).mappings().all()
        assert len(rows) == 1  # SNKRDUNK does not split into mapping-id shard groups
        assert rows[0]["eligible"] == 3 and rows[0]["never_checked"] == 3
        assert rows[0]["backoff"] == 2 and rows[0]["retries"] == 2
        assert summary in [
            r["context_json"] for r in session.execute(text(EVENT_SQL)).mappings()
        ]
        budget = session.scalar(select(SourceDispatchBudget))
        assert budget.reserved_requests == 0


def test_production_or_unproven_destination_emits_no_event(db, monkeypatch):
    factory, source, mid, _ = db
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "production-or-unknown")
    with factory() as session:
        assert (
            drain(
                session,
                source,
                "test",
                lambda *a: None,
                runtime_seconds=1,
                mapping_seconds=2,
            )
            == []
        )
        assert session.scalar(select(AppLogEvent)) is None


def test_crash_retains_start_and_refuses_healthy(db, monkeypatch):
    factory, source, mid, _ = db
    now = datetime.now(timezone.utc)
    plan(factory, mid, at=now)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "05d1eac2-510d-4bd3-999e-fea9ead766b7")

    def runner(*args, **kwargs):
        raise RuntimeError("fixture crash")

    with factory() as session:
        with pytest.raises(RuntimeError):
            drain(
                session,
                source,
                "test",
                runner,
                runtime_seconds=100,
                mapping_seconds=1,
                clock=lambda: now,
            )
    with factory() as session:
        summaries = session.scalars(select(AppLogEvent).order_by(AppLogEvent.id)).all()
        assert len(summaries) == 2
        receipt = summaries[-1].context_json
        assert receipt["exit"]["terminal_state"] == "interrupted"
        assert receipt["safety"]["claims_remaining"] == 1
        assert classify(receipt)["status"] == "DEGRADED"
        assert session.scalar(select(FreshnessWork)).state == "claimed"


def test_epoch_decimal_metrics_can_be_retained(db, monkeypatch):
    from app.models import FreshnessPriceState

    factory, source, mid, _ = db
    now = datetime.now(timezone.utc)
    plan(factory, mid, at=now)
    with factory.begin() as session:
        session.scalar(select(FreshnessPriceState)).last_successfully_checked_at = (
            now - timedelta(hours=25)
        )
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "05d1eac2-510d-4bd3-999e-fea9ead766b7")

    def runner(session, mapping_id, *, freshness):
        freshness.admit()
        freshness.result = CaptureResult("transient_failure")
        return SimpleNamespace(
            stage="transient_failure", source_denied=False, reasons=[]
        )

    with factory() as session:
        drain(
            session,
            source,
            "test",
            runner,
            runtime_seconds=100,
            mapping_seconds=1,
            max_work=1,
            clock=lambda: now,
            delay_seconds=0,
        )
    with factory() as session:
        receipt = (
            session.scalars(select(AppLogEvent).order_by(AppLogEvent.id.desc()))
            .first()
            .context_json
        )
        assert receipt["exit"]["terminal_state"] == "completed"
        assert receipt["freshness"]["successful_check_age_max"] > 86400
        assert classify(receipt)["status"] == "DEGRADED"


def test_revisit_gap_uses_capture_not_completion_or_old_price(db):
    from test_freshness_queue_postgres import claim, admit, snapshot, finish

    factory, source, mid, _ = db
    now = datetime.now(timezone.utc)
    first = now - timedelta(hours=48)
    second = first + timedelta(hours=24, minutes=5)
    plan(factory, mid, at=first)
    for at, delay in [(first, timedelta(seconds=10)), (second, timedelta(seconds=1))]:
        token = claim(factory, source, at)[0].claim_token
        admit(factory, token, at)
        raw_id = snapshot(factory, source, at)
        finish(
            factory,
            token,
            at + delay,
            outcome="no_listing",
            actual_request_cost=1,
            raw_snapshot_id=raw_id,
            no_listing_categories={"raw"},
            category_outcomes={"raw": "no_listing"},
        )
    with factory() as session:
        row = session.execute(text(DUE_SQL)).mappings().one()
        assert (
            row["maximum_successful_revisit_gap_seconds"]
            == (second - first).total_seconds()
        )


def test_budget_accounting_detects_orphan_reservation(db):
    from app.services.operational_health_sql import BUDGET_SQL

    factory, source, _, _ = db
    with factory.begin() as session:
        session.scalar(select(SourceDispatchBudget)).reserved_requests = 1
    with factory() as session:
        row = session.execute(text(BUDGET_SQL)).mappings().one()
        assert row["reservation_mismatch"] is True
        assert row["open_reservations"] == 0
