"""Yuyu-Tei source probe (owner 2026-10-26): probe mode validates without writing a price, and
the scheduled consumer resumes only on a completed probe. Playwright and the queue are fakes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.freshness_integration import CaptureResult
from yuyutei_collector import collect, recovery
from yuyutei_collector.browser import TurnBrowser

import test_raw_before_parse as fixture
from test_turn_browser import FakeAttempt, fake_playwright

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


class ProbeAttempt(FakeAttempt):
    def __init__(self):
        super().__init__()
        self.claim = SimpleNamespace(resume_cursor={"version": 1, "probe": "yuyutei", "mapping_id": 1})
        self.clock = lambda: NOW
        self.deny_calls = 0

    def deny(self):
        self.deny_calls += 1
        self.denied = True
        self.stopped = "source_denial"


class ProbeModeTests(fixture.RawBeforeParseFixture):
    def _probe(self, would_write, reasons=(), product=None):
        factory, _ = fake_playwright()
        turn = TurnBrowser(playwright_factory=factory)
        attempt = ProbeAttempt()
        check = SimpleNamespace(written=would_write, reasons=list(reasons))
        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=product or self._product()),
            patch.object(collect, "extract_with_agreement", return_value=fixture.GOOD_EXTRACTION),
            patch.object(collect, "validate_and_write_observation", return_value=check) as writer,
        ):
            with self.Session() as session:
                outcome = collect.run_one_mapping_detailed(
                    session, self.mapping_id, freshness=attempt, turn=turn, probe=True)
        return attempt, outcome, writer

    def test_a_verified_probe_completes_without_writing_a_price(self):
        attempt, outcome, writer = self._probe(True)
        self.assertEqual(writer.call_args.kwargs["write_observation"], False)
        self.assertEqual(attempt.result.outcome, "completed")
        self.assertEqual(attempt.result.resume_cursor["identity_verified"], True)
        self.assertEqual(attempt.result.resume_cursor["product_page_verified"], True)
        self.assertEqual(attempt.result.resume_cursor["probe"], "yuyutei")
        self.assertGreater(attempt.result.next_due_at, NOW)
        self.assertFalse(outcome.written)

    def test_an_unverified_probe_is_an_identity_refusal(self):
        attempt, _, _ = self._probe(False, ["card_code_mismatch"])
        self.assertEqual(attempt.result.outcome, "identity_refusal")
        self.assertIsNone(attempt.result.resume_cursor)
        self.assertEqual(attempt.result.failure, "card_code_mismatch")

    def test_a_price_only_failure_is_transient_as_in_ordinary_captures(self):
        attempt, _, _ = self._probe(False, ["price_missing"])
        self.assertEqual(attempt.result.outcome, "transient_failure")

    def test_a_challenge_page_served_with_200_is_recorded_as_a_denial_at_once(self):
        # Recorded before the attempt settles (pause + durable probe mark), as discovery does,
        # so a crash before settling cannot lose the challenge.
        challenge = {**self._product(html="<html><body>Checking your browser</body></html>" + "x" * 500),
                     "page_title": "Just a moment..."}
        attempt, outcome, writer = self._probe(True, product=challenge)
        self.assertEqual(attempt.deny_calls, 1)
        self.assertTrue(outcome.source_denied)
        writer.assert_not_called()

    def test_probe_requires_a_metered_attempt(self):
        with self.Session() as session, self.assertRaises(ValueError):
            collect.run_one_mapping_detailed(session, self.mapping_id, probe=True)


class FakeQueueAttempt:
    def __init__(self, session, claim):
        self.claim, self.result, self.denied, self.stopped = claim, None, False, None
        self.raw_snapshot_id, self.charged_cost, self.finished = None, 5, []
        self.health = {"http_403": 0, "http_429": 0, "optional_resource": 0}
        self.source_optional_denials = 0

    def finish(self, result):
        self.finished.append(result)
        return True


CLAIM = SimpleNamespace(work_id=7, claim_token="t", resume_cursor={"mapping_id": 3})
LEASE = timedelta(minutes=4)


def consume(runner, claim=CLAIM, resume_effect=None, telemetry=None):
    session = MagicMock()
    with (
        patch.object(recovery, "claim_yuyu_probe", return_value=claim),
        patch.object(recovery, "Attempt", FakeQueueAttempt),
        patch.object(recovery, "resume_after_yuyu_probe", side_effect=resume_effect) as resume,
        patch.object(recovery, "close_yuyu_probe") as close,
    ):
        result = recovery.consume_planned_probe(session, 1, runner=runner, owner="yuyutei-probe-0",
                                                lease=LEASE, telemetry=telemetry)
    close.assert_called_once()  # one-shot: closed whatever happened
    return result, resume, close


def test_no_authorized_probe_means_ordinary_work():
    telemetry = {"stopped_reason": None}
    with patch.object(recovery, "claim_yuyu_probe", return_value=None):
        assert recovery.consume_planned_probe(MagicMock(), 1, runner=MagicMock(), owner="o", lease=LEASE,
                                              telemetry=telemetry) is None
    assert telemetry["stopped_reason"] == "source_probe_not_claimed"


def test_a_completed_probe_resumes_the_source():
    def runner(session, mapping_id, *, freshness, probe):
        assert (mapping_id, probe) == (3, True)
        freshness.result = CaptureResult("completed", raw_snapshot_id=11)
        return SimpleNamespace(source_denied=False, reasons=[])

    telemetry = {"http_403": 0, "http_429": 0, "optional_resource": 0, "challenge": 0, "stopped_reason": None}
    result, resume, close = consume(runner, telemetry=telemetry)
    assert result["resumed"] is True and result["status"] == "completed" and result["challenged"] is False
    resume.assert_called_once()
    assert close.call_args.kwargs["challenged"] is False
    assert telemetry["stopped_reason"] == "source_probe_resumed"


def test_a_challenged_probe_stays_paused_and_is_marked():
    def runner(session, mapping_id, *, freshness, probe):
        freshness.denied = True
        return SimpleNamespace(source_denied=True, classification="challenge_or_captcha",
                               reasons=["no_extraction_attempted:classification=challenge_or_captcha"])

    telemetry = {"http_403": 0, "http_429": 0, "optional_resource": 0, "challenge": 0, "stopped_reason": None}
    result, resume, close = consume(runner, telemetry=telemetry)
    assert result["status"] == "source_denial" and result["resumed"] is False
    resume.assert_not_called()
    assert close.call_args.kwargs["challenged"] is True
    assert (telemetry["stopped_reason"], telemetry["challenge"]) == ("source_denial", 1)


def test_a_denial_beside_a_completed_result_never_resumes():
    def runner(session, mapping_id, *, freshness, probe):
        freshness.denied = True
        freshness.result = CaptureResult("completed", raw_snapshot_id=11)
        return SimpleNamespace(source_denied=False, reasons=[])

    result, resume, close = consume(runner)
    assert result["resumed"] is False and result["challenged"] is True
    resume.assert_not_called()
    assert close.call_args.kwargs["challenged"] is True


def test_a_403_or_429_on_an_optional_source_request_counts_as_a_challenge():
    def runner(session, mapping_id, *, freshness, probe):
        freshness.source_optional_denials = 1  # e.g. 429 on a yuyu-tei.jp stylesheet
        freshness.result = CaptureResult("completed", raw_snapshot_id=11)
        return SimpleNamespace(source_denied=False, reasons=[])

    result, resume, close = consume(runner)
    assert result["resumed"] is False and result["challenged"] is True
    resume.assert_not_called()
    assert close.call_args.kwargs["challenged"] is True


def test_a_crashing_probe_is_settled_not_left_claimed():
    def runner(session, mapping_id, *, freshness, probe):
        raise RuntimeError("browser died")

    result, resume, _ = consume(runner)
    assert result["status"] == "transient_failure" and result["failure"] == "RuntimeError"
    resume.assert_not_called()


def test_a_refused_resume_fails_closed_and_still_closes_the_probe():
    def runner(session, mapping_id, *, freshness, probe):
        freshness.result = CaptureResult("completed", raw_snapshot_id=11)
        return SimpleNamespace(source_denied=False, reasons=[])

    result, _, _ = consume(runner, resume_effect=ValueError("probe evidence is no longer current"))
    assert result["resumed"] is False
    assert "no longer current" in result["resume_refused"]


def test_serve_skips_the_execution_when_no_probe_is_due():
    execution = MagicMock()
    with patch.object(recovery, "yuyu_probe_ready", return_value=False):
        assert recovery.serve_planned_probe(MagicMock(), 1, runner=MagicMock(), shard_index=0,
                                            mapping_seconds=180, execution=execution) is None
    execution.assert_not_called()


def test_serve_caps_the_lease_for_a_long_mapping_timeout():
    from contextlib import nullcontext

    seen = {}

    def fake_consume(session, source_id, **kwargs):
        seen.update(kwargs)
        return {"status": "completed"}

    with patch.object(recovery, "yuyu_probe_ready", return_value=True), \
         patch.object(recovery, "consume_planned_probe", side_effect=fake_consume):
        recovery.serve_planned_probe(MagicMock(), 1, runner=MagicMock(), shard_index=2, mapping_seconds=3600,
                                     execution=lambda *a, **k: nullcontext(None))
    assert seen["lease"] == recovery.YUYU_PROBE_MAX_LEASE
    assert seen["owner"] == "yuyutei-probe-2"
