"""Yuyu-Tei one-shot source probe (owner 2026-10-26): disposable PostgreSQL, no source sockets."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from opcg_source_identity import canonical_source_listing_identity

from app.models import (FreshnessAttempt, FreshnessWork, RawSnapshot, Source, SourceCardMapping,
                        SourceDispatchBudget)
from app.services.freshness_queue import admit_request, complete_claim, pause_source
from app.services.source_recovery import (
    YUYU_PROBE_MAX_REQUESTS,
    claim_yuyu_probe,
    plan_yuyu_probe,
    resume_after_yuyu_probe,
)
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
        snap = RawSnapshot(source_id=work.source_id, source_url="https://yuyu-tei.jp/sell/opc/card/x/1",
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


def test_plan_reserves_nothing_and_is_never_replayed(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        work = plan_yuyu_probe(session, source, mapping_id, denial, clock=lambda: T1)
        assert (work.state, work.attempt_count) == ("pending", 0)
        assert work.resume_cursor["scheduled_recovery_authorized"] is True
    assert budget(factory) == ("source_denial", 0)
    with factory.begin() as session, pytest.raises(ValueError, match="never replayed"):
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


def test_a_probe_that_meets_a_challenge_stays_paused_and_cannot_be_reused(db):
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
    assert budget(factory)[0] == "source_denial"
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "again", clock=lambda: T1 + timedelta(hours=1)) is None
        # the probe's own denial cannot authorize another probe
        latest = session.scalar(select(FreshnessAttempt.id).order_by(FreshnessAttempt.id.desc()))
        with pytest.raises(ValueError, match="cannot authorize"):
            plan_yuyu_probe(session, source, mapping_id, latest, clock=lambda: T1 + timedelta(hours=1))


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
