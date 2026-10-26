"""Yuyu-Tei one-shot source probe (owner 2026-10-26): disposable PostgreSQL, no source sockets."""

from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from opcg_source_identity import canonical_source_listing_identity

from app.models import (FreshnessAttempt, FreshnessWork, RawSnapshot, Source, SourceCardMapping,
                        SourceDispatchBudget)
from app.services.freshness_queue import (admit_request, complete_claim, pause_source,
                                          plan_discovery_scope, plan_validation)
from app.services.source_recovery import (
    YUYU_PROBE_COOLDOWN,
    YUYU_PROBE_MAX_LEASE,
    YUYU_PROBES_PER_PAUSE,
    claim_yuyu_probe as _claim_yuyu_probe,
    close_yuyu_probe,
    plan_yuyu_probe,
    preview_yuyu_probe,
    resume_after_yuyu_probe,
    yuyu_probe_ready,
)
from test_freshness_queue_postgres import T0, admit, claim, db, plan  # noqa: F401 - fixture

T1 = T0 + timedelta(hours=1)
URL = "https://yuyu-tei.jp/sell/opc/card/op01/10001"


def claim_yuyu_probe(*args, lease=timedelta(minutes=4), **kwargs):
    return _claim_yuyu_probe(*args, lease=lease, **kwargs)


def yuyu_denial(factory, source, mapping_id):
    """A refresh denial pauses Yuyu-Tei; the mapping's refresh had captured cleanly before."""
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        row = session.get(SourceCardMapping, mapping_id)
        row.source_url = URL
        row.canonical_source_listing_identity = canonical_source_listing_identity("yuyutei", row.source_url)
        assert row.canonical_source_listing_identity
    plan(factory, mapping_id, cost=30)
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    with factory.begin() as session:
        pause_source(session, picked.claim_token, clock=lambda: T0)
        complete_claim(session, picked.claim_token, outcome="source_denial", actual_request_cost=1,
                       clock=lambda: T0)
        refresh = session.scalar(select(FreshnessWork).where(FreshnessWork.kind == "refresh"))
        refresh.last_outcome, refresh.last_successfully_checked_at = "captured", T0 - timedelta(hours=2)
        refresh.state = "pending"
        return session.scalar(select(FreshnessAttempt.id).order_by(FreshnessAttempt.id.desc()))


def latest_denial(session):
    return session.scalar(select(FreshnessAttempt.id).where(FreshnessAttempt.outcome == "source_denial")
                          .order_by(FreshnessAttempt.id.desc()))


def approve(factory, source, at=T1):
    with factory.begin() as session:
        p, problems, _ = preview_yuyu_probe(session, source, clock=lambda: at)
        assert problems == [], problems
        return plan_yuyu_probe(session, source, p, clock=lambda: at)


def problems_at(factory, source, at):
    with factory() as session:
        return preview_yuyu_probe(session, source, clock=lambda: at)[1]


def budget(factory):
    with factory() as session:
        b = session.scalar(select(SourceDispatchBudget))
        return b.pause_reason, b.reserved_requests


def probe_capture(factory, token, *, at=T1, status=200, verified=True):
    with factory.begin() as session:
        assert admit_request(session, token, ordinal=1, cost=5, clock=lambda: at)
    with factory.begin() as session:
        work = session.scalar(select(FreshnessWork).where(FreshnessWork.claim_token == token))
        snap = RawSnapshot(source_id=work.source_id, source_url=URL,
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


def challenge(factory, source, at):
    """One probe that meets a challenge, settled and closed as the collector does."""
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: at)
    with factory.begin() as session:
        assert admit_request(session, probe.claim_token, ordinal=1, cost=1, clock=lambda: at)
        pause_source(session, probe.claim_token, clock=lambda: at)
        complete_claim(session, probe.claim_token, outcome="source_denial", actual_request_cost=1,
                       clock=lambda: at + timedelta(seconds=30))
    with factory.begin() as session:
        close_yuyu_probe(session, probe.work_id, challenged=True, clock=lambda: at + timedelta(minutes=1))
    return probe


def test_plan_reserves_nothing_and_one_open_probe_at_a_time(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    work = approve(factory, source)
    assert (work.state, work.attempt_count, work.scope_key) == ("pending", 0, f"source-recovery:yuyutei:{denial}:1")
    assert work.resume_cursor["scheduled_recovery_authorized"] is True
    assert work.resume_cursor["root_denial_attempt_id"] == denial
    assert budget(factory) == ("source_denial", 0)
    assert any("still open" in p for p in problems_at(factory, source, T1))


def test_the_preview_is_read_only_and_reports_the_chain_and_mapping(db):
    factory, source, mapping_id, _ = db
    denial = yuyu_denial(factory, source, mapping_id)
    with factory() as session:
        session.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
        p, problems, facts = preview_yuyu_probe(session, source, clock=lambda: T1)
    assert problems == []
    assert p == {"source_id": source, "root_denial_attempt_id": denial, "denial_attempt_id": denial,
                 "probe_number": 1, "mapping_id": mapping_id, "card_print_id": p["card_print_id"],
                 "product_identity": canonical_source_listing_identity("yuyutei", URL), "request_bound": 60}
    assert (facts["denial"]["work_kind"], facts["mapping"]["source_url"]) == ("refresh", URL)


def test_the_apply_writes_only_the_approved_plan(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory() as session:
        p = preview_yuyu_probe(session, source, clock=lambda: T1)[0]
    for changed in ({**p, "request_bound": 61}, {**p, "card_print_id": p["card_print_id"] + 1},
                    {**p, "product_identity": "yuyutei:other"}, {**p, "probe_number": 2}):
        with factory.begin() as session, pytest.raises(ValueError, match="differs"):
            plan_yuyu_probe(session, source, changed, clock=lambda: T1)
    with factory.begin() as session, pytest.raises(ValueError, match="plan keys"):
        plan_yuyu_probe(session, source, {**p, "extra": 1}, clock=lambda: T1)
    with factory() as session:
        assert session.scalar(select(FreshnessWork).where(FreshnessWork.kind == "validation")) is None


def test_failed_probes_are_capped_per_pause(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    for number in range(1, YUYU_PROBES_PER_PAUSE + 1):
        assert approve(factory, source).resume_cursor["probe_number"] == number
        with factory.begin() as session:
            probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
        probe_capture(factory, probe.claim_token, verified=False)
        with factory.begin() as session:
            close_yuyu_probe(session, probe.work_id, clock=lambda: T1)
    assert any("probes already used for this pause" in p for p in problems_at(factory, source, T1))


def test_challenged_probes_stay_in_the_same_pause_chain_and_share_the_cap(db):
    factory, source, mapping_id, _ = db
    root = yuyu_denial(factory, source, mapping_id)
    at = T1
    for number in range(1, YUYU_PROBES_PER_PAUSE + 1):
        work = approve(factory, source, at)
        assert work.scope_key == f"source-recovery:yuyutei:{root}:{number}"
        challenge(factory, source, at)
        with factory() as session:
            assert latest_denial(session) != root  # the probe recorded its own denial
        at = at + YUYU_PROBE_COOLDOWN + timedelta(minutes=5)
    problems = problems_at(factory, source, at)
    assert any("probes already used for this pause" in p for p in problems)
    assert budget(factory)[0] == "source_denial"


def test_a_probe_that_meets_a_challenge_waits_for_the_cool_down(db):
    factory, source, mapping_id, _ = db
    root = yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    challenge(factory, source, T1)
    assert budget(factory)[0] == "source_denial"
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "again", clock=lambda: T1 + timedelta(hours=1)) is None
    assert any("wait until" in p for p in problems_at(factory, source, T1 + timedelta(hours=1)))
    later = T1 + YUYU_PROBE_COOLDOWN + timedelta(minutes=2)
    work = approve(factory, source, later)
    assert work.scope_key == f"source-recovery:yuyutei:{root}:2"


def test_a_challenge_whose_attempt_never_settled_still_starts_the_cool_down(db):
    factory, source, mapping_id, _ = db
    root = yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:  # denied, then the turn died before settling
        assert admit_request(session, probe.claim_token, ordinal=1, cost=1, clock=lambda: T1)
        pause_source(session, probe.claim_token, clock=lambda: T1)
    with factory.begin() as session:  # the next turn closes the orphan
        assert not yuyu_probe_ready(session, source, clock=lambda: T1 + timedelta(minutes=10))
    with factory() as session:
        assert latest_denial(session) == root  # no new denial attempt was recorded
        assert session.get(FreshnessWork, probe.work_id).state == "blocked"
    assert any("wait until" in p for p in problems_at(factory, source, T1 + timedelta(hours=1)))


def test_close_marks_a_challenge_the_attempt_could_not_record(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:
        assert admit_request(session, probe.claim_token, ordinal=1, cost=1, clock=lambda: T1)
        complete_claim(session, probe.claim_token, outcome="transient_failure", actual_request_cost=1,
                       failure="x", clock=lambda: T1)
    with factory.begin() as session:
        close_yuyu_probe(session, probe.work_id, challenged=True, clock=lambda: T1)
    assert any("wait until" in p for p in problems_at(factory, source, T1 + timedelta(hours=1)))


def test_a_discovery_denial_can_be_probed(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        work = plan_discovery_scope(session, source, "discovery:x", due_at=T0)
        session.flush()
        session.add(FreshnessAttempt(
            work_id=work.id, claim_token="d", claimed_by="x", claimed_at=T1, started_at=T1, finished_at=T1,
            reserved_request_cost=1, request_costs=[1], actual_request_cost=1, charged_request_cost=1,
            outcome="source_denial"))
    with factory() as session:
        discovery_denial = latest_denial(session)
    work = approve(factory, source, T1 + timedelta(minutes=1))
    assert work.scope_key == f"source-recovery:yuyutei:{discovery_denial}:1"


def test_a_denial_from_other_validation_work_is_refused(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        work = plan_validation(session, source, "something-else", due_at=T0)
        session.flush()
        session.add(FreshnessAttempt(
            work_id=work.id, claim_token="v", claimed_by="x", claimed_at=T1, started_at=T1, finished_at=T1,
            reserved_request_cost=1, request_costs=[1], actual_request_cost=1, charged_request_cost=1,
            outcome="source_denial"))
    assert any("not a Yuyu-Tei probe" in p for p in problems_at(factory, source, T1))


def test_the_preview_skips_mappings_that_are_not_eligible(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        session.get(SourceCardMapping, mapping_id).review_status = "needs_review"
    assert any("no approved, eligible" in p for p in problems_at(factory, source, T1))


def test_one_claim_ordinary_work_stays_paused_and_a_verified_capture_resumes(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    assert claim(factory, source, at=T1) == []  # ordinary dispatch still paused
    with factory.begin() as session:
        assert yuyu_probe_ready(session, source, clock=lambda: T1)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "yuyutei-probe-0", clock=lambda: T1)
    assert probe is not None and probe.resume_cursor["mapping_id"] == mapping_id
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "yuyutei-probe-1", clock=lambda: T1) is None
    probe_capture(factory, probe.claim_token)
    with factory.begin() as session:
        resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=2))
        close_yuyu_probe(session, probe.work_id, reason="probe resumed the source", clock=lambda: T1)
    assert budget(factory) == (None, 0)
    with factory.begin() as session:  # closed: never served again
        assert not yuyu_probe_ready(session, source, clock=lambda: T1 + timedelta(minutes=5))
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1 + timedelta(minutes=5)) is None


def test_a_denial_during_a_completed_capture_blocks_the_resume(db):
    """A 403 on a required request mid-probe (pause_source) survives the result's cursor."""
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:
        assert admit_request(session, probe.claim_token, ordinal=1, cost=5, clock=lambda: T1)
        pause_source(session, probe.claim_token, clock=lambda: T1)
    with factory.begin() as session:
        snap = RawSnapshot(source_id=source, source_url=URL, fetched_at=T1 + timedelta(seconds=20),
                           http_status=200, content_hash="c" * 64, raw_content="page")
        session.add(snap)
        session.flush()
        complete_claim(  # the cursor the collector builds from its claim, without the denial
            session, probe.claim_token, outcome="completed", actual_request_cost=5, raw_snapshot_id=snap.id,
            resume_cursor={**probe.resume_cursor, "identity_verified": True, "product_page_verified": True},
            next_due_at=T1 + timedelta(days=36500), clock=lambda: T1 + timedelta(minutes=1))
    with factory.begin() as session:
        assert session.get(FreshnessWork, probe.work_id).resume_cursor["required_denial"] is True
        with pytest.raises(ValueError, match="no longer current"):
            resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=2))
    assert budget(factory)[0] == "source_denial"


def test_an_unverified_probe_never_resumes(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    probe_capture(factory, probe.claim_token, verified=False)
    with factory.begin() as session, pytest.raises(ValueError):
        resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=2))
    assert budget(factory)[0] == "source_denial"


def test_a_late_resume_is_refused(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    probe_capture(factory, probe.claim_token)
    with factory.begin() as session, pytest.raises(ValueError, match="no longer current"):
        resume_after_yuyu_probe(session, probe.claim_token, clock=lambda: T1 + timedelta(minutes=10))
    assert budget(factory)[0] == "source_denial"


def test_a_newer_denial_makes_a_planned_probe_stale(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        session.add(FreshnessAttempt(
            work_id=session.scalar(select(FreshnessWork.id).where(FreshnessWork.kind == "refresh")),
            claim_token="later", claimed_by="x", claimed_at=T1, started_at=T1, finished_at=T1,
            reserved_request_cost=1, request_costs=[1], actual_request_cost=1, charged_request_cost=1,
            outcome="source_denial"))
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1) is None
    with factory() as session:  # closed, so it can never stall ordinary claims
        assert session.scalar(select(FreshnessWork.state).where(FreshnessWork.kind == "validation")) == "blocked"


def test_a_manual_unpause_closes_a_pending_probe(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        session.scalar(select(SourceDispatchBudget)).pause_reason = None
    with factory.begin() as session:
        assert not yuyu_probe_ready(session, source, clock=lambda: T1)
    with factory() as session:
        assert session.scalar(select(FreshnessWork.state).where(FreshnessWork.kind == "validation")) == "blocked"


def test_a_probe_for_a_mapping_that_became_ineligible_is_closed_not_raised(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        session.get(SourceCardMapping, mapping_id).is_active = False
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1) is None
    with factory() as session:
        assert session.scalar(select(FreshnessWork.state).where(FreshnessWork.kind == "validation")) == "blocked"


def test_an_expired_probe_is_closed_on_the_next_turn(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source)
    with factory.begin() as session:
        probe = claim_yuyu_probe(session, source, "p", clock=lambda: T1)
    with factory.begin() as session:
        assert claim_yuyu_probe(session, source, "p2", clock=lambda: T1 + timedelta(minutes=10)) is None
    with factory() as session:
        row = session.get(FreshnessWork, probe.work_id)
        assert (row.state, row.attempt_count) == ("blocked", 1)


def test_a_source_without_a_budget_has_no_probe_and_does_not_raise(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session:
        session.execute(delete(SourceDispatchBudget))
    with factory.begin() as session:
        assert yuyu_probe_ready(session, source, clock=lambda: T1) is False
        assert yuyu_probe_ready(session, None, clock=lambda: T1) is False
        assert claim_yuyu_probe(session, source, "p", clock=lambda: T1) is None
        assert preview_yuyu_probe(session, source, clock=lambda: T1)[1] == ["no Yuyu-Tei dispatch budget"]


def test_the_lease_is_bounded(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    with factory.begin() as session, pytest.raises(ValueError, match="lease"):
        claim_yuyu_probe(session, source, "p", lease=YUYU_PROBE_MAX_LEASE + timedelta(seconds=1),
                         clock=lambda: T1)
