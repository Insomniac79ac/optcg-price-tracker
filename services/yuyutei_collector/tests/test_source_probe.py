"""Yuyu-Tei source probe (owner 2026-10-26): probe mode validates without writing a price, and
the scheduled consumer resumes only on a completed probe. Playwright and the queue are fakes."""

from datetime import datetime, timezone
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


class ProbeModeTests(fixture.RawBeforeParseFixture):
    def _probe(self, would_write, reasons=()):
        factory, _ = fake_playwright()
        turn = TurnBrowser(playwright_factory=factory)
        attempt = ProbeAttempt()
        check = SimpleNamespace(written=would_write, reasons=list(reasons))
        with (
            patch.object(collect, "warm_up_homepage", return_value=self._normal_homepage()),
            patch.object(collect, "goto_and_capture_raw", return_value=self._product()),
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

    def test_probe_requires_a_metered_attempt(self):
        with self.Session() as session, self.assertRaises(ValueError):
            collect.run_one_mapping_detailed(session, self.mapping_id, probe=True)


class FakeQueueAttempt:
    def __init__(self, session, claim):
        self.claim, self.result, self.denied, self.stopped = claim, None, False, None
        self.raw_snapshot_id, self.charged_cost, self.finished = None, 5, []

    def finish(self, result):
        self.finished.append(result)
        return True


def consume(runner, claim=SimpleNamespace(work_id=7, claim_token="t", resume_cursor={"mapping_id": 3})):
    session = MagicMock()
    with (
        patch.object(recovery, "claim_yuyu_probe", return_value=claim),
        patch.object(recovery, "Attempt", FakeQueueAttempt),
        patch.object(recovery, "resume_after_yuyu_probe") as resume,
    ):
        result = recovery.consume_planned_probe(session, 1, runner=runner, owner="yuyutei-probe-0")
    return result, resume


def test_no_authorized_probe_means_ordinary_work():
    with patch.object(recovery, "claim_yuyu_probe", return_value=None):
        assert recovery.consume_planned_probe(MagicMock(), 1, runner=MagicMock(), owner="o") is None


def test_a_completed_probe_resumes_the_source():
    def runner(session, mapping_id, *, freshness, probe):
        assert (mapping_id, probe) == (3, True)
        freshness.result = CaptureResult("completed", raw_snapshot_id=11)
        return SimpleNamespace(source_denied=False, reasons=[])

    result, resume = consume(runner)
    assert result["resumed"] is True and result["status"] == "completed"
    resume.assert_called_once()


def test_a_challenged_probe_stays_paused():
    def runner(session, mapping_id, *, freshness, probe):
        freshness.denied = True
        return SimpleNamespace(source_denied=True, reasons=["no_extraction_attempted:classification=challenge_or_captcha"])

    result, resume = consume(runner)
    assert result["status"] == "source_denial" and result["resumed"] is False
    resume.assert_not_called()


def test_a_crashing_probe_is_settled_not_left_claimed():
    def runner(session, mapping_id, *, freshness, probe):
        raise RuntimeError("browser died")

    result, resume = consume(runner)
    assert result["status"] == "transient_failure" and result["failure"] == "RuntimeError"
    resume.assert_not_called()
