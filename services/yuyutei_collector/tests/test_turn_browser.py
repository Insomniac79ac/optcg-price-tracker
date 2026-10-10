"""A due-work turn reuses one warmed browser; all Playwright objects are fakes."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.freshness_integration import AdmissionStopped
from yuyutei_collector import collect, due
from yuyutei_collector.browser import DeadlineExceeded, TurnBrowser

import test_raw_before_parse as fixture

GOOD_EXTRACTION = fixture.GOOD_EXTRACTION


class FakeAttempt:
    def __init__(self):
        self.stopped = None
        self.denied = False
        self.result = None
        self.settled = []

    def settle_browser(self, page):
        self.settled.append(page)

    def begin_result(self):
        pass


def fake_playwright():
    pw = MagicMock()
    pw.contexts = []

    def new_context(**options):
        context = MagicMock(name=f"context{len(pw.contexts)}")
        context.options = options
        context.new_page.side_effect = lambda: MagicMock(name="page")
        pw.contexts.append(context)
        return context

    pw.chromium.launch.return_value.new_context.side_effect = new_context
    factory = MagicMock()
    factory.return_value.start.return_value = pw
    return factory, pw


class TurnBrowserTests(fixture.RawBeforeParseFixture):
    def setUp(self):
        super().setUp()
        self.factory, self.pw = fake_playwright()
        self.turn = TurnBrowser(playwright_factory=self.factory)
        self.warmups = 0

    def _attempt(self, *, product=None, extraction=GOOD_EXTRACTION, homepage=None,
                 product_effect=None, settle_effect=None):
        attempt = FakeAttempt()
        if settle_effect:
            attempt.settle_browser = MagicMock(side_effect=settle_effect)

        def warm(page):
            self.warmups += 1
            return homepage or self._normal_homepage()

        def goto(page, url):
            if product_effect:
                return product_effect(attempt)
            return product or self._product()

        written = SimpleNamespace(outcome="captured", observation_ids=[1])
        with (
            patch.object(collect, "warm_up_homepage", side_effect=warm),
            patch.object(collect, "goto_and_capture_raw", side_effect=goto),
            patch.object(collect, "extract_with_agreement", return_value=extraction),
            patch.object(due, "write_capture", return_value=written),
        ):
            with self.Session() as session:
                outcome = collect.run_one_mapping_detailed(
                    session, self.mapping_id, freshness=attempt, turn=self.turn
                )
        return attempt, outcome

    def test_clean_attempts_share_one_warm_up_and_one_browser(self):
        attempts = [self._attempt()[0] for _ in range(3)]
        self.assertEqual(self.warmups, 1)
        self.assertEqual(self.pw.chromium.launch.call_count, 1)
        context = self.pw.contexts[0]
        self.assertEqual(context.options, {"service_workers": "block"})
        # Each attempt settled its own page before the next was bound.
        pages = [a.settled[0] for a in attempts]
        self.assertEqual(len(set(map(id, pages))), 3)
        for page in pages:
            page.close.assert_called_once()
        self.assertIsNone(self.turn.meter.attempt)
        context.close.assert_not_called()
        self.assertTrue(self.turn.warm)
        context.route.assert_called_once()  # one turn-level meter, installed once

    def test_every_failure_class_discards_the_browser_and_rewarms(self):
        def stop(attempt):
            attempt.stopped = "budget"
            return self._product()

        def deny(attempt):
            attempt.denied = True
            return self._product()

        def deadline_hit(attempt):
            raise DeadlineExceeded("product_navigation")

        def crash(attempt):
            raise RuntimeError("target closed")

        challenge_html = "<html><body>Just a moment...</body></html>"
        cases = {
            "http_404": dict(product=self._product(status=404)),
            "not_normal_product": dict(product=self._product(html=challenge_html)),
            "homepage_failed": dict(homepage={"http_status": 403, "classification": "access_denied",
                                              "html": "<html>denied</html>"}),
            "stopped": dict(product_effect=stop),
            "denied": dict(product_effect=deny),
            "settle_stopped": dict(settle_effect=AdmissionStopped("browser_route_settle_timeout")),
            "deadline": dict(product_effect=deadline_hit),
            "exception": dict(product_effect=crash),
        }
        for name, failure in cases.items():
            with self.subTest(name):
                self.factory, self.pw = fake_playwright()
                self.turn = TurnBrowser(playwright_factory=self.factory)
                self.warmups = 0
                self._attempt()
                if name == "homepage_failed":
                    self.turn.warm = False  # force this attempt to warm, and fail
                self._attempt(**failure)
                self.assertFalse(self.turn.warm)
                self.assertIsNone(self.turn.context)
                self.pw.contexts[0].close.assert_called_once()
                self._attempt()
                self.assertEqual(self.pw.chromium.launch.call_count, 2)
                self.assertEqual(self.warmups, 3 if name == "homepage_failed" else 2)

    def test_turn_requires_a_metered_attempt(self):
        with self.Session() as session, self.assertRaises(ValueError):
            collect.run_one_mapping_detailed(session, self.mapping_id, turn=self.turn)

    def test_launch_deadline_marks_browser_unusable_and_discards(self):
        self.pw.chromium.launch.side_effect = DeadlineExceeded("browser_launch")
        _, outcome = self._attempt()
        self.assertTrue(outcome.browser_unusable)
        self.assertIsNone(self.turn.context)

    def test_run_due_closes_the_turn_however_it_ends(self):
        seen = {}

        def failing_drain(session, source_id, owner, runner, **kwargs):
            seen["turn"] = runner.keywords["turn"]
            raise RuntimeError("lease lost")

        with patch.object(due, "drain", side_effect=failing_drain), \
             patch.object(TurnBrowser, "close") as close:
            with self.assertRaises(RuntimeError):
                due.run_due(shard_index=0, session_factory=self.Session)
        self.assertIsInstance(seen["turn"], TurnBrowser)
        close.assert_called_once()

    def test_explicit_runner_keeps_per_capture_behaviour(self):
        runner = MagicMock()
        with patch.object(due, "drain", return_value=[]) as drain:
            due.run_due(shard_index=0, session_factory=self.Session, runner=runner)
        self.assertIs(drain.call_args.args[3], runner)
