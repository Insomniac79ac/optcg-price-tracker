"""The scheduled Yuyu-Tei probe end to end on disposable PostgreSQL: the collector's consumer
(yuyutei_collector.recovery) with the real queue, Attempt and settle path. Only the capture
itself is a stand-in (no browser, no source socket)."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import sys

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "services/yuyutei_collector")]

from app.models import FreshnessAttempt, FreshnessWork, PriceObservation, SourceDispatchBudget  # noqa: E402
from app.services.freshness_integration import Attempt, CaptureResult  # noqa: E402
from app.services.freshness_policy import utc_now  # noqa: E402
from app.services.source_recovery import preview_yuyu_probe  # noqa: E402
from yuyutei_collector import recovery  # noqa: E402

from test_freshness_queue_postgres import db  # noqa: F401,E402 - fixture
from test_yuyu_probe_postgres import URL, approve, yuyu_denial  # noqa: E402

LEASE = timedelta(minutes=4)


def capture(*, deny_before_result=False, challenge=False):
    """A stand-in for run_one_mapping_detailed(probe=True): metered, raw page first."""
    def runner(session, mapping_id, *, freshness, probe):
        assert probe is True
        freshness.admit(cost=5)
        if challenge:
            freshness.deny()
            return SimpleNamespace(source_denied=True, reasons=["classification=challenge_or_captcha"],
                                   classification="challenge_or_captcha")
        source_id = session.get(FreshnessWork, freshness.claim.work_id).source_id
        sid = freshness.snapshot(source_id, URL, {"http_status": 200, "html": "<html>product</html>"}, "probe-test")
        freshness.raw_snapshot_id = sid
        if deny_before_result:
            freshness.deny()  # e.g. a 403 on a required request after the page
        freshness.result = CaptureResult(
            "completed", raw_snapshot_id=sid,
            resume_cursor={**freshness.claim.resume_cursor, "identity_verified": True,
                           "product_page_verified": True},
            next_due_at=utc_now() + timedelta(days=36500),
        )
        return SimpleNamespace(source_denied=False, reasons=[], classification="product")
    return runner


def pause(factory):
    with factory() as session:
        return session.scalar(select(SourceDispatchBudget.pause_reason))


def probe_row(factory):
    with factory() as session:
        return session.scalar(select(FreshnessWork).where(FreshnessWork.kind == "validation"))


def consume(factory, source, runner, **kwargs):
    with factory() as session:
        return recovery.consume_planned_probe(session, source, runner=runner, owner="yuyutei-probe-0",
                                              lease=LEASE, **kwargs)


def ready(factory, source, mapping_id):
    yuyu_denial(factory, source, mapping_id)
    approve(factory, source, utc_now())


def test_a_clean_capture_resumes_the_source_and_closes_the_probe(db):
    factory, source, mapping_id, _ = db
    ready(factory, source, mapping_id)
    result = consume(factory, source, capture())
    assert (result["status"], result["resumed"], result["challenged"]) == ("completed", True, False)
    assert pause(factory) is None
    row = probe_row(factory)
    assert (row.state, row.attempt_count, row.last_failure) == ("blocked", 1, "probe resumed the source")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0  # no price written
        b = session.scalar(select(SourceDispatchBudget))
        assert b.reserved_requests == 0
        attempt = session.scalar(select(FreshnessAttempt).where(FreshnessAttempt.work_id == row.id))
        assert (attempt.outcome, attempt.charged_request_cost) == ("completed", 5)
    assert consume(factory, source, capture()) is None  # one-shot


def test_a_challenge_keeps_the_pause_and_starts_the_cool_down(db):
    factory, source, mapping_id, _ = db
    ready(factory, source, mapping_id)
    result = consume(factory, source, capture(challenge=True))
    assert (result["status"], result["resumed"], result["challenged"]) == ("source_denial", False, True)
    assert pause(factory) == "source_denial"
    row = probe_row(factory)
    assert (row.state, row.resume_cursor["required_denial"]) == ("blocked", True)
    with factory() as session:
        problems = preview_yuyu_probe(session, source)[1]
    assert any("wait until" in p for p in problems)


def test_a_denial_after_a_clean_page_never_resumes(db):
    factory, source, mapping_id, _ = db
    ready(factory, source, mapping_id)
    result = consume(factory, source, capture(deny_before_result=True))
    assert (result["resumed"], result["challenged"]) == (False, True)
    assert pause(factory) == "source_denial"
    assert probe_row(factory).resume_cursor["required_denial"] is True


def test_a_settle_failure_after_a_challenge_still_records_the_challenge(db, monkeypatch):
    factory, source, mapping_id, _ = db
    ready(factory, source, mapping_id)

    def broken_finish(self, result):
        raise RuntimeError("database went away")

    monkeypatch.setattr(Attempt, "finish", broken_finish)
    result = consume(factory, source, capture(challenge=True))
    assert result["resumed"] is False and "RuntimeError" in result["resume_refused"]
    assert pause(factory) == "source_denial"
    # The still-claimed probe expires and the next turn closes it; the challenge stays marked.
    with factory.begin() as session:
        assert not recovery.yuyu_probe_ready(session, source, clock=lambda: utc_now() + timedelta(minutes=10))
    row = probe_row(factory)
    assert (row.state, row.resume_cursor["required_denial"]) == ("blocked", True)
    with factory() as session:
        assert any("wait until" in p for p in preview_yuyu_probe(session, source)[1])


@contextmanager
def fake_execution(seen):
    @contextmanager
    def execution(session, source_id, owner, **kwargs):
        telemetry = {"owner": f"{owner}:run", "http_403": 0, "http_429": 0, "challenge": 0,
                     "optional_resource": 0, "stopped_reason": None}
        seen.append((owner, kwargs, telemetry))
        yield telemetry
    yield execution


def test_serve_records_the_probe_turn_as_its_own_execution(db):
    factory, source, mapping_id, _ = db
    ready(factory, source, mapping_id)
    seen = []
    with fake_execution(seen) as execution, factory() as session:
        result = recovery.serve_planned_probe(session, source, runner=capture(challenge=True), shard_index=3,
                                              mapping_seconds=180, execution=execution)
    assert result["challenged"] is True
    owner, kwargs, telemetry = seen[0]
    assert (owner, kwargs["shard"], kwargs["max_work"]) == ("yuyutei-probe-3", 3, 1)
    assert (telemetry["stopped_reason"], telemetry["challenge"]) == ("source_denial", 1)
    with factory() as session:
        attempt = session.scalar(select(FreshnessAttempt).where(FreshnessAttempt.work_id == probe_row(factory).id))
        assert attempt.claimed_by == "yuyutei-probe-3:run"  # the execution's own claims


def test_serve_without_a_probe_opens_no_execution(db):
    factory, source, mapping_id, _ = db
    yuyu_denial(factory, source, mapping_id)
    seen = []
    with fake_execution(seen) as execution, factory() as session:
        assert recovery.serve_planned_probe(session, source, runner=capture(), shard_index=0,
                                            mapping_seconds=180, execution=execution) is None
    assert seen == []
