"""Yuyu-Tei one-shot source probe (owner 2026-10-26): disposable PostgreSQL, no source sockets."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from opcg_source_identity import canonical_source_listing_identity

from app.models import (FreshnessAttempt, FreshnessWork, RawSnapshot, Source, SourceCardMapping,
                        SourceDispatchBudget)
from app.services.freshness_queue import admit_request, complete_claim, pause_source
from app.services.source_recovery import (
    YUYU_PROBE_COOLDOWN,
    YUYU_PROBE_MAX_REQUESTS,
    YUYU_PROBES_PER_DENIAL,
    claim_yuyu_probe,
    close_yuyu_probe,
    plan_yuyu_probe as _plan_yuyu_probe,
    resume_after_yuyu_probe,
)


def plan_yuyu_probe(*args, request_bound=80, **kwargs):
    return _plan_yuyu_probe(*args, request_bound=request_bound, **kwargs)
from test_freshness_queue_postgres import T0, admit, claim, db, plan  # noqa: F401 - fixture

T1 = T0 + timedelta(hours=1)


def yuyu_denial(factory, source, mapping_id):
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        row = session.get(SourceCardMapping, mapping_id)
        row.source_url = "https://yuyu-tei.jp/sell/opc/card/op01/10001"
        row.canonical_source_listing_identity = canonical_source_listing_identity("yuyutei", row.source_url)
        assert row.canonical_source_listing_identity
    plan(factory, mapping_id, cost=30)
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    with factory.begin() as session:
        pause_source(session, picked.claim_token, clock=lambda: T0)
        complete_claim(session, picked.claim_token, outcome="source_denial", actual_request_cost=1,
                       clock=lambda: T0)
        return session.scalar(select(FreshnessAttempt.id).order_by(FreshnessAttempt.id.desc()))


def budget(factory):
    with factory() as session:
        b = session.scalar(select(SourceDispatchBudget))
        return b.pause_reason, b.reserved_requests


def probe_capture(factory, token, *, at=T1, status=200, verified=True):
    with factory.begin() as session:
        assert admit_request(session, token, ordinal=1, cost=5, clock=lambda: at)
    with factory.begin() as session:
        work = session.scalar(select(FreshnessWork).where(FreshnessWork.claim_token == token))
        snap = RawSnapshot(source_id=work.source_id, source_url="https://yuyu-tei.jp/sell/opc/card/op01/10001",
                           fetched_at=at + timedelta(seconds=20), http_status=status,
                           content_hash="b" * 64, raw_content="page")
        session.add(snap)
        session.flush()
        complete_claim(
            session, token, outcome="completed" if verified else "identity_refusal",
            actual_request_cost=5, raw_snapshot_id=snap.id,
            resume_cursor={**work.resume_cursor, "identity_verified": verified,
                           "product_page_verified": True} if verified else None,
            failure=None if verified else "identity_mismatch",
            next_due_at=at + timedelta(days=36500) if verified else None,
            clock=lambda: at + timedelta(minutes=1),
        )


def test_plan_reserves_nothing_and_one_open_probe_at_a_time(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        work = plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
        assert (work.state, work.attempt_count, work.scope_key) == (
            "pending", 0, f"source-recovery:yuyutei:{denial}:1")
        assert work.resume_cursor["scheduled_recovery_authorized"] is True
    assert budget(factory) == ("source_denial", 0)
    with factory.begin() as session, pytest.raises(ValueError, match="still open"):
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)


def test_a_failed_probe_can_be_followed_by_a_new_approval_up_to_the_limit(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    for number in range(1, YUYU_PROBES_PER_DENIAL + 1):
        with factory.begin() as session:
            work = plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
            assert work.resume_cursor["probe_number"] == number
        with factory.begin() as session:
            probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
        probe_capture(factory, probe.claim_token, verified=False)
        with factory.begin() as session:
            close_yuyu_probe(session, probe.work_id, clock=lambda: T1)
    with factory.begin() as session, pytest.raises(ValueError, match="limit"):
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)


def test_plan_refuses_without_a_current_denial_or_out_of_bounds(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session, pytest.raises(ValueError):
        plan_yuyu_probe(session, source, mapping_id, denial + 999, clock=lambda: T1)
    with factory.begin() as session, pytest.raises(ValueError):
        plan_yuyu_probe(session, source, mapping_id, denial, request_bound=YUYU_PROBE_MAX_REQUESTS + 1,
                        clock=lambda: T1)


def test_one_claim_ordinary_work_stays_paused_and_a_verified_capture_resumes(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
    assert claim(factory, source, at=T1) == []  # ordinary dispatch still paused
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "yuyutei-probe-0", clock=lambda: T1)
    assert probe is not None and probe.resume_cursor["mapping_id"] == mapping_id
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "yuyutei-probe-1", clock=lambda: T1) is None
    probe_capture(factory, probe.claim_token)
    with factory.begin() as session:
        resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=2))
    assert budget(factory) == (None, 0)


def test_an_unverified_or_late_probe_never_resumes(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    probe_capture(factory, probe.claim_token, verified=False)
    with factory.begin() as session, pytest.raises(ValueError):
        resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=2))
    assert budget(factory)[0] == "source_denial"


def test_a_probe_that_meets_a_challenge_stays_paused_and_waits_for_the_cool_down(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:
        assert admit_request(session, probe.claim_token, ordinal=1, cost=1, clock=lambda: T1)
        pause_source(session, probe.claim_token, clock=lambda: T1)
        complete_claim(session, probe.claim_token, outcome="source_denial", actual_request_cost=1,
                       clock=lambda: T1 + timedelta(seconds=30))
    with factory.begin() as session:
        close_yuyu_probe(session, probe.work_id, clock=lambda: T1)
    assert budget(factory)[0] == "source_denial"
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "again", clock=lambda: T1 + timedelta(hours=1)) is None
        latest = session.scalar(select(FreshnessAttempt.id).order_by(FreshnessAttempt.id.desc()))
        with pytest.raises(ValueError, match="cool-down"):
            plan_yuyu_probe(session, source, mapping_id, latest, clock=lambda: T1 + timedelta(hours=1))
    with factory.begin() as session:
        later = T1 + YUYU_PROBE_COOLDOWN + timedelta(minutes=1)
        work = plan_yuyu_probe(session, source, mapping_id, latest, clock=lambda: later)
        assert work.scope_key == f"source-recovery:yuyutei:{latest}:1"


def test_a_newer_denial_makes_a_planned_probe_stale(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
        session.add(FreshnessAttempt(
            work_id=session.scalar(select(FreshnessWork.id).where(FreshnessWork.kind == "refresh")),
            claim_token="later", claimed_by="x", claimed_at=T1, started_at=T1, finished_at=T1,
            reserved_request_cost=1, request_costs=[1], actual_request_cost=1, charged_request_cost=1,
            outcome="source_denial"))
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1) is None
    with factory() as session:  # closed, so it can never stall ordinary claims
        assert session.scalar(select(FreshnessWork.state).where(FreshnessWork.kind == "validation")) == "blocked"


def test_a_probe_for_a_mapping_that_became_ineligible_is_closed_not_raised(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
        session.get(SourceCardMapping, mapping_id).is_active = False
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1) is None
    with factory() as session:
        assert session.scalar(select(FreshnessWork.state).where(FreshnessWork.kind == "validation")) == "blocked"


def test_an_expired_probe_is_closed_on_the_next_turn(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p2", clock=lambda: T1 + timedelta(minutes=10)) is None
    with factory() as session:
        row = session.get(FreshnessWork, probe.work_id)
        assert (row.state, row.attempt_count) == ("blocked", 1)
