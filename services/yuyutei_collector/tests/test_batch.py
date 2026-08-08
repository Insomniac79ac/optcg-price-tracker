"""Tests for yuyutei_collector.batch against an in-memory SQLite database -
no network, no real Playwright/browser, no staging database. Selection
(select_eligible_mappings) runs for real against the test database; the
per-mapping Yuyu-Tei fetch (mapping_runner) is always a fake so these tests
never make a network request.
"""

import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from yuyutei_collector.batch import BatchResult, run_batch, select_eligible_mappings
from yuyutei_collector.collect import MappingOutcome
from yuyutei_collector.db import Base
from yuyutei_collector.models import Card, CardPrint, PriceObservation, Source, SourceCardMapping


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return engine, Session


class FakeMappingRunner:
    """Records every call it receives and returns a canned MappingOutcome
    per mapping_id - stands in for run_one_mapping_detailed so these tests
    never touch Playwright or the network."""

    def __init__(self, outcomes: dict[int, MappingOutcome], sleep_s: float = 0.0):
        self.outcomes = outcomes
        self.sleep_s = sleep_s
        self.calls: list[tuple[int, str | None]] = []
        self.validate_only_calls: list[bool] = []

    def __call__(self, session, mapping_id, validate_only=False, batch_run_id=None):
        self.calls.append((mapping_id, batch_run_id))
        self.validate_only_calls.append(validate_only)
        if self.sleep_s:
            time.sleep(self.sleep_s)
        return self.outcomes[mapping_id]


def written_outcome(mapping_id: int, price_jpy: int = 1000, stock_status: str = "in_stock") -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="written",
        written=True,
        classification="normal_product",
        observation_id=1000 + mapping_id,
        raw_snapshot_id=2000 + mapping_id,
        card_id=1,
        card_print_id=mapping_id,
        source_card_mapping_id=mapping_id,
        price_jpy=price_jpy,
        stock_status=stock_status,
        observed_at="2026-01-01T00:00:00+00:00",
    )


def validation_failed_outcome(mapping_id: int, reasons: list[str]) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="validation_failed",
        written=False,
        classification="normal_product",
        reasons=reasons,
    )


def source_denied_outcome(mapping_id: int, classification: str) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="no_extraction_attempted",
        written=False,
        classification=classification,
        source_denied=True,
        reasons=[f"no_extraction_attempted:classification={classification}"],
    )


def operational_error_outcome(mapping_id: int) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="operational_error",
        written=False,
        reasons=["RuntimeError: boom"],
    )


class SelectionTestCase(unittest.TestCase):
    """Exercises select_eligible_mappings for real against a SQLite DB -
    proves the discovery query itself (not a mock) enforces every
    eligibility rule."""

    def setUp(self):
        self.engine, Session = make_db()
        self.session = Session()

        self.yuyutei = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        self.other_source = Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com")
        self.session.add_all([self.yuyutei, self.other_source])
        self.session.flush()

        self.card = Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro")
        self.session.add(self.card)
        self.session.flush()

        self.verified_active_print = CardPrint(
            id=1, canonical_card_id=1, treatment="parallel", verification_status="verified", is_active=True
        )
        self.unverified_print = CardPrint(
            id=2, canonical_card_id=1, treatment="normal", verification_status="unverified", is_active=True
        )
        self.inactive_verified_print = CardPrint(
            id=3, canonical_card_id=1, treatment="normal", verification_status="verified", is_active=False
        )
        self.session.add_all(
            [self.verified_active_print, self.unverified_print, self.inactive_verified_print]
        )
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def _mapping(self, **overrides):
        fields = dict(
            card_id=self.card.id,
            source_id=self.yuyutei.id,
            card_print_id=self.verified_active_print.id,
            source_card_id="OP01-001",
            source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
            is_active=True,
            review_status="approved",
        )
        fields.update(overrides)
        mapping = SourceCardMapping(**fields)
        self.session.add(mapping)
        self.session.flush()
        return mapping

    def test_eligible_mapping_is_selected(self):
        mapping = self._mapping(id=10)
        selected = select_eligible_mappings(self.session)
        self.assertEqual([m.id for m in selected], [mapping.id])

    def test_unverified_print_excluded(self):
        self._mapping(id=11, card_print_id=self.unverified_print.id)
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_inactive_print_excluded(self):
        self._mapping(id=12, card_print_id=self.inactive_verified_print.id)
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_unapproved_mapping_excluded(self):
        self._mapping(id=13, review_status="needs_review")
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_inactive_mapping_excluded(self):
        self._mapping(id=14, is_active=False)
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_lineageless_mapping_excluded(self):
        """A mapping with no card_print_id at all (legacy-card-only) must
        never be selected, even if otherwise approved+active."""
        self._mapping(id=15, card_print_id=None)
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_non_yuyutei_source_excluded(self):
        self._mapping(id=16, source_id=self.other_source.id)
        selected = select_eligible_mappings(self.session)
        self.assertEqual(selected, [])

    def test_no_hardcoded_card_identity(self):
        """Selection must be driven purely by DB state, not any particular
        card_code/mapping id - proven by using values nothing in the source
        tree ever hardcodes."""
        other_print = CardPrint(
            id=99, canonical_card_id=1, treatment="normal", verification_status="verified", is_active=True
        )
        self.session.add(other_print)
        self.session.flush()
        mapping = self._mapping(id=777, card_print_id=99, source_card_id="OP99-999")
        selected = select_eligible_mappings(self.session)
        self.assertEqual([m.id for m in selected], [mapping.id])

    def test_mapping_ids_narrows_without_widening_eligibility(self):
        eligible = self._mapping(id=20)
        ineligible_print = CardPrint(
            id=4, canonical_card_id=1, treatment="normal", verification_status="unverified", is_active=True
        )
        self.session.add(ineligible_print)
        self.session.flush()
        ineligible = self._mapping(id=21, card_print_id=4, source_card_id="OP01-002")

        # Asking for both an eligible and an ineligible id must only ever
        # return the eligible one - mapping_ids narrows, never bypasses
        # eligibility.
        selected = select_eligible_mappings(self.session, mapping_ids=[eligible.id, ineligible.id])
        self.assertEqual([m.id for m in selected], [eligible.id])

    def test_limit_bounds_selection(self):
        first = self._mapping(id=20)
        second_print = CardPrint(
            id=4, canonical_card_id=1, treatment="normal", verification_status="verified", is_active=True
        )
        self.session.add(second_print)
        self.session.flush()
        self._mapping(id=21, card_print_id=4, source_card_id="OP01-002")

        selected = select_eligible_mappings(self.session, limit=1)
        self.assertEqual([m.id for m in selected], [first.id])


class RunBatchTestCase(unittest.TestCase):
    def setUp(self):
        # Every test here exercises orchestration logic, never the actual
        # conservative inter-mapping delay's real duration - patched out so
        # this suite runs in milliseconds, not seconds.
        self._sleep_patch = patch("yuyutei_collector.batch.time.sleep")
        self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

        self.engine, self.Session = make_db()
        session = self.Session()

        source = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        card = Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro")
        session.add_all([source, card])
        session.flush()

        self.mapping_ids = [10, 20, 30]
        for i, mapping_id in enumerate(self.mapping_ids):
            print_row = CardPrint(
                id=100 + i, canonical_card_id=1, treatment="normal",
                verification_status="verified", is_active=True,
            )
            session.add(print_row)
            session.flush()
            session.add(
                SourceCardMapping(
                    id=mapping_id, card_id=card.id, source_id=source.id,
                    card_print_id=print_row.id, source_card_id=f"OP01-{i:03d}",
                    source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{i}",
                    is_active=True, review_status="approved",
                )
            )
        session.commit()
        session.close()

    def _run(self, outcomes: dict[int, MappingOutcome], sleep_s: float = 0.0, **kwargs) -> tuple[BatchResult, FakeMappingRunner]:
        runner = FakeMappingRunner(outcomes, sleep_s=sleep_s)
        result = run_batch(session_factory=self.Session, mapping_runner=runner, **kwargs)
        return result, runner

    def test_five_mappings_processed_sequentially(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, runner = self._run(outcomes)
        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids)
        self.assertEqual(result.mappings_selected, self.mapping_ids)

    def test_one_success_produces_one_observation_outcome(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, _runner = self._run(outcomes)
        written = [r for r in result.results if r.written]
        self.assertEqual(len(written), 3)
        for r in result.results:
            self.assertTrue(r.written)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)

    def test_mapping_validation_failure_writes_zero_observations_for_that_mapping(self):
        outcomes = {
            self.mapping_ids[0]: written_outcome(self.mapping_ids[0]),
            self.mapping_ids[1]: validation_failed_outcome(
                self.mapping_ids[1], ["price_disagreement:jsonld=100,dom=200"]
            ),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2]),
        }
        result, runner = self._run(outcomes)

        # All three still attempted - a mapping-level failure does not stop
        # the batch.
        self.assertEqual(len(runner.calls), 3)
        failed = next(r for r in result.results if r.mapping_id == self.mapping_ids[1])
        self.assertFalse(failed.written)
        self.assertIsNone(failed.observation_id)
        self.assertEqual(result.status, "partial_failure")
        self.assertEqual(result.exit_code, 2)

    def test_mapping_failure_does_not_contaminate_another_mapping(self):
        outcomes = {
            self.mapping_ids[0]: validation_failed_outcome(self.mapping_ids[0], ["price_missing_or_ambiguous"]),
            self.mapping_ids[1]: written_outcome(self.mapping_ids[1], price_jpy=555, stock_status="out_of_stock"),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2], price_jpy=999, stock_status="in_stock"),
        }
        result, _runner = self._run(outcomes)

        by_id = {r.mapping_id: r for r in result.results}
        self.assertFalse(by_id[self.mapping_ids[0]].written)
        self.assertIsNone(by_id[self.mapping_ids[0]].price_jpy)
        self.assertEqual(by_id[self.mapping_ids[1]].price_jpy, 555)
        self.assertEqual(by_id[self.mapping_ids[1]].stock_status, "out_of_stock")
        self.assertEqual(by_id[self.mapping_ids[2]].price_jpy, 999)
        self.assertEqual(by_id[self.mapping_ids[2]].stock_status, "in_stock")

    def test_403_stops_the_whole_batch(self):
        outcomes = {
            self.mapping_ids[0]: written_outcome(self.mapping_ids[0]),
            self.mapping_ids[1]: source_denied_outcome(self.mapping_ids[1], "static_403"),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2]),
        }
        result, runner = self._run(outcomes)

        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids[:2])  # third never attempted
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.status, "source_wide_failure")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("static_403", result.stopped_reason)

    def test_captcha_stops_the_whole_batch(self):
        outcomes = {
            self.mapping_ids[0]: source_denied_outcome(self.mapping_ids[0], "challenge_or_captcha"),
            self.mapping_ids[1]: written_outcome(self.mapping_ids[1]),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2]),
        }
        result, runner = self._run(outcomes)

        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids[:1])
        self.assertEqual(result.status, "source_wide_failure")
        self.assertEqual(result.exit_code, 1)

    def test_identity_mismatch_fails_one_mapping_without_inventing_data(self):
        outcomes = {
            self.mapping_ids[0]: validation_failed_outcome(
                self.mapping_ids[0], ["card_code_mismatch_vs_mapping:displayed=OP01-002,mapping=OP01-001"]
            ),
            self.mapping_ids[1]: written_outcome(self.mapping_ids[1]),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2]),
        }
        result, runner = self._run(outcomes)

        self.assertEqual(len(runner.calls), 3)  # continues past the mismatch
        mismatched = next(r for r in result.results if r.mapping_id == self.mapping_ids[0])
        self.assertFalse(mismatched.written)
        self.assertIsNone(mismatched.price_jpy)
        self.assertIsNone(mismatched.stock_status)
        self.assertIsNone(mismatched.observation_id)

    def test_operational_error_continues_to_next_mapping(self):
        outcomes = {
            self.mapping_ids[0]: operational_error_outcome(self.mapping_ids[0]),
            self.mapping_ids[1]: written_outcome(self.mapping_ids[1]),
            self.mapping_ids[2]: written_outcome(self.mapping_ids[2]),
        }
        result, runner = self._run(outcomes)
        self.assertEqual(len(runner.calls), 3)
        self.assertEqual(result.status, "partial_failure")

    def test_duplicate_selector_result_cannot_produce_two_observations(self):
        """Defends against a hypothetical selector bug (or a future change)
        returning the same mapping twice - run_batch must still only ever
        call mapping_runner once per mapping id per batch."""
        session = self.Session()
        real_mappings = select_eligible_mappings(session)
        doubled = real_mappings + [real_mappings[0]]

        def doubling_selector(_session, limit=None, mapping_ids=None):
            return doubled

        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        runner = FakeMappingRunner(outcomes)
        result = run_batch(
            session_factory=self.Session, mapping_runner=runner, mapping_selector=doubling_selector
        )
        session.close()

        ids_called = [c[0] for c in runner.calls]
        self.assertEqual(len(ids_called), len(set(ids_called)))  # no id called twice
        self.assertEqual(ids_called.count(self.mapping_ids[0]), 1)
        self.assertEqual(len(result.results), 3)

    def test_batch_run_id_is_consistent_across_mappings(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, runner = self._run(outcomes)
        batch_run_ids = {c[1] for c in runner.calls}
        self.assertEqual(len(batch_run_ids), 1)
        self.assertEqual(batch_run_ids.pop(), result.batch_run_id)

    def test_limit_bounds_batch_size(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, runner = self._run(outcomes, limit=1)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result.mappings_selected, [self.mapping_ids[0]])

    def test_mapping_ids_narrows_batch_to_just_those_ids(self):
        """A one-off operational batch (e.g. right after approving a new
        group of mappings) can target exactly that group without touching
        any other already-eligible mapping."""
        target = [self.mapping_ids[1]]
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, runner = self._run(outcomes, mapping_ids=target)
        self.assertEqual([c[0] for c in runner.calls], target)
        self.assertEqual(result.mappings_selected, target)
        self.assertEqual(result.status, "success")

    def test_validate_only_is_threaded_through_to_mapping_runner(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        _result, runner = self._run(outcomes, validate_only=True)
        self.assertTrue(runner.validate_only_calls)
        self.assertTrue(all(runner.validate_only_calls))

    def test_batch_total_timeout_stops_remaining_mappings(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        session.close()
        self.assertEqual(len(selected), 3)

        # Clock reads, in call order: (1) budget computed before the loop,
        # (2) the index-0 deadline check, (3) the index-1 deadline check,
        # (4) the index-2 deadline check - jumping far into the future so
        # only the third check trips the watchdog, after two mappings have
        # already been attempted.
        clock = iter([0.0, 0.0, 0.0, 1_000_000.0])

        def fake_monotonic():
            return next(clock, 1_000_000.0)

        import yuyutei_collector.batch as batch_module

        original_monotonic = batch_module.time.monotonic
        batch_module.time.monotonic = fake_monotonic
        try:
            outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
            runner = FakeMappingRunner(outcomes)
            result = run_batch(session_factory=self.Session, mapping_runner=runner)
        finally:
            batch_module.time.monotonic = original_monotonic

        self.assertEqual(len(runner.calls), 2)  # only the first two mappings got attempted
        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids[:2])
        self.assertEqual(result.stopped_reason, "batch_total_timeout_exceeded")
        self.assertEqual(result.status, "partial_failure")
        self.assertEqual(result.exit_code, 2)

    def test_no_eligible_mappings_is_a_clean_success(self):
        engine, Session = make_db()
        session = Session()
        session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
        session.commit()
        session.close()

        result = run_batch(session_factory=Session, mapping_runner=FakeMappingRunner({}))
        self.assertEqual(result.results, [])
        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)


class ObservationLineageTestCase(unittest.TestCase):
    """Confirms a written MappingOutcome's fields, when actually persisted
    via the real writer path (not the fake runner), still land as one
    PriceObservation row scoped to the correct card_print_id - guards
    against a batch-layer bug that could scramble which print an
    observation belongs to."""

    def test_batch_writes_route_to_correct_print(self):
        from yuyutei_collector.writer import validate_and_write_observation

        engine, Session = make_db()
        session = Session()
        source = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        card = Card(id=1, card_code="OP01-001", name_en="Zoro")
        session.add_all([source, card])
        session.flush()
        print_a = CardPrint(id=1, canonical_card_id=1, treatment="parallel", verification_status="verified", is_active=True)
        print_b = CardPrint(id=2, canonical_card_id=1, treatment="normal", verification_status="verified", is_active=True)
        session.add_all([print_a, print_b])
        session.flush()
        mapping_a = SourceCardMapping(
            id=1, card_id=card.id, source_id=source.id, card_print_id=print_a.id,
            source_card_id="OP01-001", source_url="https://yuyu-tei.jp/a", is_active=True, review_status="approved",
        )
        mapping_b = SourceCardMapping(
            id=2, card_id=card.id, source_id=source.id, card_print_id=print_b.id,
            source_card_id="OP01-001", source_url="https://yuyu-tei.jp/b", is_active=True, review_status="approved",
        )
        session.add_all([mapping_a, mapping_b])
        session.flush()

        extraction_a = {
            "extraction_status": "extracted", "fail_reasons": [],
            "extracted": {"card_code": "OP01-001", "treatment": "parallel", "sell_price_jpy": 3000, "stock_status": "in_stock"},
        }
        extraction_b = {
            "extraction_status": "extracted", "fail_reasons": [],
            "extracted": {"card_code": "OP01-001", "treatment": "normal", "sell_price_jpy": 100, "stock_status": "in_stock"},
        }
        validate_and_write_observation(
            session=session, mapping=mapping_a, classification="normal_product",
            extraction=extraction_a, http_status=200, raw_html="<html>a</html>",
            source_url=mapping_a.source_url, parser_version="test",
        )
        validate_and_write_observation(
            session=session, mapping=mapping_b, classification="normal_product",
            extraction=extraction_b, http_status=200, raw_html="<html>b</html>",
            source_url=mapping_b.source_url, parser_version="test",
        )
        session.commit()

        obs_a = session.query(PriceObservation).filter_by(card_print_id=print_a.id).one()
        obs_b = session.query(PriceObservation).filter_by(card_print_id=print_b.id).one()
        self.assertEqual(obs_a.price_jpy, 3000)
        self.assertEqual(obs_b.price_jpy, 100)
        self.assertNotEqual(obs_a.id, obs_b.id)
        session.close()


if __name__ == "__main__":
    unittest.main()
