"""A12 - failure isolation for the Yuyu-Tei collector.

Every test here drives run_one_mapping_detailed / run_batch against a FAKE
Playwright and an in-memory SQLite database. Nothing in this file makes a
network request, launches a real browser, or touches staging.

The failure being pinned is A11's tail (batch a2a222bc394e, 2026-09-06):
mappings 532-539 timed out on product navigation, 540-541 then timed out on
the homepage, and 542-545 could no longer launch a browser at all - each
paying the full 30s launch watchdog to discover it, and each leaving another
"Future exception was never retrieved / TargetClosedError" pair behind.

The invariant these tests exist to hold: a mapping may fail itself, but the
NEXT mapping must start from usable collector state.
"""

import unittest
import unittest.mock
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import collect
from yuyutei_collector.batch import MAX_CONSECUTIVE_BROWSER_FAILURES, run_batch
from yuyutei_collector.collect import MappingOutcome, run_one_mapping_detailed
from yuyutei_collector.db import Base
from yuyutei_collector.models import Card, CardPrint, PriceObservation, Source, SourceCardMapping

FIXTURES = Path(__file__).parent / "fixtures"
HOMEPAGE_URL = "https://yuyu-tei.jp/"
PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"
OTHER_PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10003"

# >500 bytes and carrying the homepage marker, so classify_page returns
# "normal_product" exactly as the real warm-up requires.
HOMEPAGE_HTML = "<html><body>遊々亭 " + ("トップページ " * 120) + "</body></html>"
HOMEPAGE_TITLE = "遊々亭"


def product_html() -> str:
    return (FIXTURES / "product_op01_001_reduced.html").read_text(encoding="utf-8")


PRODUCT_TITLE = "P-L ロロノア・ゾロ(パラレル) 販売 | [OP01]ROMANCE DAWN -遊々亭-"


class FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status
        self.ok = 200 <= status < 300


class Boom(Exception):
    """A non-Playwright teardown failure - the kind _release_browser_objects
    must consume rather than propagate."""


class FakePage:
    def __init__(self, browser: "FakeBrowser"):
        self.browser = browser
        self.url = ""
        self._html = ""
        self._title = ""

    def goto(self, url, wait_until=None, timeout=None):
        self.browser.factory.navigations.append(url)
        behaviour = self.browser.factory.responses.get(url)
        if behaviour is None:
            raise AssertionError(f"test did not script a response for {url}")
        if isinstance(behaviour, BaseException):
            raise behaviour
        self.url = url
        self._html, self._title = behaviour
        return FakeResponse(200)

    def wait_for_timeout(self, ms):
        return None

    def title(self):
        return self._title

    def content(self):
        return self._html

    def close(self):
        self.browser.factory.closed.append("page")
        if self.browser.factory.raise_on_close == "page":
            raise Boom("page close exploded")


class FakeContext:
    def __init__(self, browser: "FakeBrowser"):
        self.browser = browser

    def new_page(self):
        return FakePage(self.browser)

    def close(self):
        self.browser.factory.closed.append("context")
        if self.browser.factory.raise_on_close == "context":
            raise Boom("context close exploded")


class FakeBrowser:
    def __init__(self, factory: "FakePlaywrightFactory"):
        self.factory = factory

    def new_context(self):
        if self.factory.new_context_error is not None:
            raise self.factory.new_context_error
        return FakeContext(self)

    def close(self):
        self.factory.closed.append("browser")
        if self.factory.raise_on_close == "browser":
            raise Boom("browser close exploded")


class FakeChromium:
    def __init__(self, factory):
        self.factory = factory

    def launch(self, **kwargs):
        self.factory.launches += 1
        err = self.factory.launch_error
        if err is not None:
            raise err
        return FakeBrowser(self.factory)


class FakePlaywrightFactory:
    """One instance stands in for the sync_playwright() module entry. Records
    launches, navigations and every close() so a test can assert on the exact
    lifecycle rather than on log text."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.launches = 0
        self.navigations: list[str] = []
        self.closed: list[str] = []
        self.stopped = 0
        self.launch_error: BaseException | None = None
        self.new_context_error: BaseException | None = None
        self.raise_on_close: str | None = None
        self.chromium = FakeChromium(self)

    # sync_playwright() returns a context manager whose __enter__ is the API
    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stopped += 1
        return False


class CollectorFailureIsolationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        self.session = self.Session()

        self.session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
        self.session.add(Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro"))
        self.session.flush()
        self.session.add(
            CardPrint(
                id=1,
                canonical_card_id=1,
                treatment="parallel",
                verification_status="verified",
                is_active=True,
            )
        )
        self.session.flush()
        for mapping_id, url in ((10, PRODUCT_URL), (11, OTHER_PRODUCT_URL)):
            self.session.add(
                SourceCardMapping(
                    id=mapping_id,
                    card_id=1,
                    source_id=1,
                    card_print_id=1,
                    source_card_id="OP01-001",
                    source_url=url,
                    is_active=True,
                    review_status="approved",
                )
            )
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def install(self, responses) -> FakePlaywrightFactory:
        factory = FakePlaywrightFactory(responses)
        patcher = unittest.mock.patch.object(collect, "sync_playwright", factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        return factory

    def healthy_responses(self) -> dict:
        return {
            HOMEPAGE_URL: (HOMEPAGE_HTML, HOMEPAGE_TITLE),
            PRODUCT_URL: (product_html(), PRODUCT_TITLE),
            OTHER_PRODUCT_URL: (product_html(), PRODUCT_TITLE),
        }

    # ---------------------------------------------------------------- A ----
    def test_product_timeout_is_isolated_and_the_next_mapping_succeeds(self):
        """A11's 532-539 shape: the product URL times out. The mapping fails,
        the browser is fully released, and the next mapping writes."""
        responses = self.healthy_responses()
        responses[PRODUCT_URL] = PlaywrightError("Timeout 30000ms exceeded")
        factory = self.install(responses)

        first = run_one_mapping_detailed(self.session, 10)
        self.assertEqual(first.stage, "no_extraction_attempted")
        self.assertEqual(first.failure_stage, "product")
        # A page that timed out says nothing about the browser subsystem.
        self.assertFalse(first.browser_unusable)
        # Teardown ran to completion, innermost first - the thing A11 skipped.
        self.assertEqual(factory.closed, ["page", "context", "browser"])

        factory.closed.clear()
        second = run_one_mapping_detailed(self.session, 11)
        self.assertEqual(second.stage, "written")
        self.assertTrue(second.written)
        self.assertEqual(factory.closed, ["page", "context", "browser"])

    # ---------------------------------------------------------------- B ----
    def test_homepage_timeout_is_isolated_and_the_next_mapping_succeeds(self):
        """A11's 540-541 shape: the homepage itself stops answering."""
        responses = self.healthy_responses()
        responses[HOMEPAGE_URL] = PlaywrightError("Timeout 30000ms exceeded")
        factory = self.install(responses)

        first = run_one_mapping_detailed(self.session, 10)
        self.assertEqual(first.stage, "no_extraction_attempted")
        self.assertEqual(first.failure_stage, "homepage")
        self.assertFalse(first.browser_unusable)
        self.assertEqual(factory.closed, ["page", "context", "browser"])
        # The product URL was never requested - the gate held.
        self.assertNotIn(PRODUCT_URL, factory.navigations)

        responses[HOMEPAGE_URL] = (HOMEPAGE_HTML, HOMEPAGE_TITLE)
        factory.closed.clear()
        second = run_one_mapping_detailed(self.session, 11)
        self.assertEqual(second.stage, "written")

    # ---------------------------------------------------------------- C ----
    def test_browser_state_closing_unexpectedly_is_detected_and_discarded(self):
        """A11's 542-545 shape: the browser plumbing itself fails. The bad
        state must be flagged, discarded, and replaced with a fresh browser."""
        responses = self.healthy_responses()
        factory = self.install(responses)
        factory.new_context_error = PlaywrightError(
            "Target page, context or browser has been closed"
        )

        first = run_one_mapping_detailed(self.session, 10)
        self.assertEqual(first.stage, "operational_error")
        # The distinction the batch needs, and the one A11 could not make.
        self.assertTrue(first.browser_unusable)
        # The browser that DID come into existence was still released, even
        # though the context never did.
        self.assertEqual(factory.closed, ["browser"])
        self.assertEqual(factory.stopped, 1)

        # Fresh state for the next mapping: a new launch, and it succeeds.
        factory.new_context_error = None
        launches_before = factory.launches
        second = run_one_mapping_detailed(self.session, 11)
        self.assertEqual(second.stage, "written")
        self.assertEqual(factory.launches, launches_before + 1)

    def test_a_launch_that_never_returns_is_marked_browser_unusable(self):
        factory = self.install(self.healthy_responses())
        factory.launch_error = PlaywrightError("Timeout 30000ms exceeded launching browser")

        outcome = run_one_mapping_detailed(self.session, 10)
        self.assertEqual(outcome.stage, "operational_error")
        self.assertTrue(outcome.browser_unusable)
        # Nothing existed to close, and teardown coped with that silently.
        self.assertEqual(factory.closed, [])

    # ---------------------------------------------------------------- D ----
    def test_teardown_that_raises_is_consumed_and_the_next_mapping_proceeds(self):
        """Every handle gets its own close attempt, a raise is swallowed, and
        the mapping keeps the outcome it had already earned."""
        for handle in ("page", "context", "browser"):
            with self.subTest(handle=handle):
                factory = self.install(self.healthy_responses())
                factory.raise_on_close = handle

                first = run_one_mapping_detailed(self.session, 10)
                # The teardown failure did not become the mapping's outcome.
                self.assertEqual(first.stage, "written")
                # Independence: a raise on one handle never skips the others.
                self.assertEqual(factory.closed, ["page", "context", "browser"])

                factory.raise_on_close = None
                second = run_one_mapping_detailed(self.session, 11)
                self.assertEqual(second.stage, "written")

    # ---------------------------------------------------------------- F ----
    def test_healthy_path_launches_exactly_one_browser_per_mapping(self):
        """Guards against 'fix' by restart: failure isolation must not make
        the ordinary path rebuild a browser it did not need to."""
        factory = self.install(self.healthy_responses())

        for mapping_id in (10, 11):
            outcome = run_one_mapping_detailed(self.session, mapping_id)
            self.assertEqual(outcome.stage, "written")

        self.assertEqual(factory.launches, 2)
        self.assertEqual(factory.stopped, 2)
        self.assertEqual(
            factory.closed, ["page", "context", "browser", "page", "context", "browser"]
        )
        # One homepage warm-up and one product request per mapping - the
        # healthy-path source request count is unchanged by A12.
        self.assertEqual(
            factory.navigations,
            [HOMEPAGE_URL, PRODUCT_URL, HOMEPAGE_URL, OTHER_PRODUCT_URL],
        )

    def test_only_one_observation_is_written_per_successful_mapping(self):
        factory = self.install(self.healthy_responses())
        run_one_mapping_detailed(self.session, 10)
        self.assertEqual(factory.launches, 1)
        rows = self.session.query(PriceObservation).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_card_mapping_id, 10)


def browser_unusable_outcome(mapping_id: int) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="operational_error",
        failure_stage="browser_launch",
        browser_unusable=True,
        reasons=["watchdog_triggered:browser_launch"],
    )


def written_outcome(mapping_id: int) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="written",
        written=True,
        classification="normal_product",
        observation_id=mapping_id,
        card_print_id=mapping_id,
        source_card_mapping_id=mapping_id,
        price_jpy=100,
        stock_status="in_stock",
        observed_at="2026-01-01T00:00:00+00:00",
    )


def page_failure_outcome(mapping_id: int) -> MappingOutcome:
    """A per-mapping page failure: the browser is fine."""
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="no_extraction_attempted",
        failure_stage="product",
        reasons=["no_extraction_attempted:classification=None"],
    )


class BatchCascadeBreakerTest(unittest.TestCase):
    """run_batch's half of the invariant: one failed mapping must not end the
    batch, but a browser subsystem that has stopped working must not be asked
    the same question for every mapping still queued."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        session = self.Session()
        session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
        session.add(Card(id=1, card_code="OP01-001", name_en="Zoro"))
        session.flush()
        session.add(
            CardPrint(
                id=1,
                canonical_card_id=1,
                treatment="parallel",
                verification_status="verified",
                is_active=True,
            )
        )
        session.flush()
        for mapping_id in range(1, 9):
            session.add(
                SourceCardMapping(
                    id=mapping_id,
                    card_id=1,
                    source_id=1,
                    card_print_id=1,
                    source_card_id="OP01-001",
                    source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{mapping_id}",
                    is_active=True,
                    review_status="approved",
                )
            )
        session.commit()
        session.close()

    def _run(self, outcomes):
        calls: list[int] = []

        def runner(session, mapping_id, validate_only=False, batch_run_id=None):
            calls.append(mapping_id)
            return outcomes[mapping_id]

        with unittest.mock.patch("yuyutei_collector.batch._mapping_delay_s", return_value=0):
            result = run_batch(session_factory=self.Session, mapping_runner=runner)
        return result, calls

    def test_page_failures_never_stop_the_batch(self):
        """Eight consecutive per-mapping page failures - the browser is fine,
        so every mapping is still attempted."""
        outcomes = {i: page_failure_outcome(i) for i in range(1, 9)}
        result, calls = self._run(outcomes)
        self.assertEqual(calls, list(range(1, 9)))
        self.assertIsNone(result.stopped_reason)

    def test_batch_stops_after_consecutive_browser_failures(self):
        outcomes = {i: browser_unusable_outcome(i) for i in range(1, 9)}
        result, calls = self._run(outcomes)
        self.assertEqual(len(calls), MAX_CONSECUTIVE_BROWSER_FAILURES)
        self.assertEqual(result.stopped_reason, "browser_unavailable")
        # The mappings never reached are skipped, not invented as failures.
        self.assertEqual(result.status, "partial_failure")

    def test_a_recovered_mapping_resets_the_breaker(self):
        """Two browser failures, then a success, then two more: the browser
        demonstrably worked in between, so the batch must run to the end."""
        outcomes = {
            1: browser_unusable_outcome(1),
            2: browser_unusable_outcome(2),
            3: written_outcome(3),
            4: browser_unusable_outcome(4),
            5: browser_unusable_outcome(5),
            6: written_outcome(6),
            7: written_outcome(7),
            8: written_outcome(8),
        }
        result, calls = self._run(outcomes)
        self.assertEqual(calls, list(range(1, 9)))
        self.assertIsNone(result.stopped_reason)

    # ---------------------------------------------------------------- E ----
    def test_batch_deadline_behaviour_is_unchanged(self):
        """The batch watchdog still owns the wall-clock stop, still checks
        before each mapping starts, and still reports its own reason. A12
        added a breaker beside it, not in front of it."""
        import yuyutei_collector.batch as batch_module

        # (1) budget computed before the loop, (2)(3) two passing checks,
        # (4) far future - so the third mapping is never started.
        clock = iter([0.0, 0.0, 0.0, 1_000_000.0])
        original = batch_module.time.monotonic
        batch_module.time.monotonic = lambda: next(clock, 1_000_000.0)
        try:
            outcomes = {i: written_outcome(i) for i in range(1, 9)}
            result, calls = self._run(outcomes)
        finally:
            batch_module.time.monotonic = original

        self.assertEqual(calls, [1, 2])
        self.assertEqual(result.stopped_reason, "batch_total_timeout_exceeded")
        self.assertEqual(result.status, "partial_failure")
        self.assertEqual(result.exit_code, 2)

    def test_source_denial_still_takes_priority(self):
        """A denial must keep its own stopped_reason, not be relabelled."""
        outcomes = {i: written_outcome(i) for i in range(1, 9)}
        outcomes[2] = MappingOutcome(
            mapping_id=2,
            stage="no_extraction_attempted",
            classification="static_403",
            source_denied=True,
            reasons=["no_extraction_attempted:classification=static_403"],
        )
        result, calls = self._run(outcomes)
        self.assertEqual(calls, [1, 2])
        self.assertEqual(result.stopped_reason, "source_denied:static_403")


if __name__ == "__main__":
    unittest.main()
