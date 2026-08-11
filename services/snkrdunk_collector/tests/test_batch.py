"""Tests for snkrdunk_collector.batch against an in-memory SQLite database -
no network, no real Playwright/browser, no staging database. Selection
(select_eligible_mappings) runs for real against the test database; the
per-mapping SNKRDUNK fetch (mapping_runner) is always a fake so these tests
never make a network request. Mirrors
services/yuyutei_collector/tests/test_batch.py."""

import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.batch import BatchResult, run_batch, select_eligible_mappings
from snkrdunk_collector.collect import MappingOutcome
from snkrdunk_collector.db import Base
from snkrdunk_collector.models import Card, CardPrint, PriceObservation, Source, SourceCardMapping


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return engine, Session


class FakeMappingRunner:
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


def written_outcome(mapping_id: int, price_jpy: int = 1000) -> MappingOutcome:
    return MappingOutcome(mapping_id=mapping_id, stage="written", written=True, price_jpy=price_jpy)


def failed_outcome(mapping_id: int, reasons=None) -> MappingOutcome:
    return MappingOutcome(mapping_id=mapping_id, stage="validation_failed", written=False, reasons=reasons or [])


def denied_outcome(mapping_id: int, classification="static_403") -> MappingOutcome:
    return MappingOutcome(mapping_id=mapping_id, stage="no_extraction_attempted", source_denied=True, classification=classification)


class BaseBatchTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session = make_db()
        session = self.Session()
        source = Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com")
        rejected_source = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        session.add_all([source, rejected_source])

        cards = [Card(id=i, card_code=f"OP01-{i:03d}", name_en=f"Card {i}") for i in range(1, 6)]
        session.add_all(cards)

        prints = [
            CardPrint(id=i, canonical_card_id=i, language="jp", treatment="parallel", verification_status="verified")
            for i in range(1, 4)
        ]
        # An unverified print - must never be selected.
        prints.append(
            CardPrint(id=4, canonical_card_id=4, language="jp", treatment="parallel", verification_status="unverified")
        )
        session.add_all(prints)
        session.flush()

        mappings = [
            SourceCardMapping(
                id=100 + i, card_id=i, source_id=2, card_print_id=i,
                source_card_id=f"OP01-{i:03d}", source_url=f"https://snkrdunk.com/apparels/{i}",
                is_active=True, review_status="approved", manual_verified=True,
            )
            for i in range(1, 4)
        ]
        # Rejected legacy mapping - card_print_id is null, must never be selected.
        mappings.append(
            SourceCardMapping(
                id=200, card_id=4, source_id=2, card_print_id=None,
                source_card_id="OP01-004", source_url="https://snkrdunk.com/cards/OP01-004",
                is_active=True, review_status="rejected", manual_verified=False,
            )
        )
        # Mapping pointing at an unverified print - must never be selected.
        mappings.append(
            SourceCardMapping(
                id=201, card_id=4, source_id=2, card_print_id=4,
                source_card_id="OP01-004", source_url="https://snkrdunk.com/apparels/999",
                is_active=True, review_status="approved", manual_verified=True,
            )
        )
        # Inactive mapping - must never be selected.
        mappings.append(
            SourceCardMapping(
                id=202, card_id=1, source_id=2, card_print_id=1,
                source_card_id="OP01-001", source_url="https://snkrdunk.com/apparels/998",
                is_active=False, review_status="approved", manual_verified=True,
            )
        )
        # Approved but never actually manually verified - must never be
        # selected (see the 2026-08-10 incident this check was added for).
        mappings.append(
            SourceCardMapping(
                id=203, card_id=1, source_id=2, card_print_id=1,
                source_card_id="OP01-001", source_url="https://snkrdunk.com/apparels/997",
                is_active=True, review_status="approved", manual_verified=False,
            )
        )
        session.add_all(mappings)
        session.commit()
        session.close()


class SelectionTests(BaseBatchTestCase):
    def test_only_approved_active_verified_print_mappings_selected(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        self.assertEqual([m.id for m in selected], [101, 102, 103])
        session.close()

    def test_rejected_mapping_excluded(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        self.assertNotIn(200, [m.id for m in selected])
        session.close()

    def test_unverified_print_mapping_excluded(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        self.assertNotIn(201, [m.id for m in selected])
        session.close()

    def test_inactive_mapping_excluded(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        self.assertNotIn(202, [m.id for m in selected])
        session.close()

    def test_approved_but_not_manually_verified_mapping_excluded(self):
        session = self.Session()
        selected = select_eligible_mappings(session)
        self.assertNotIn(203, [m.id for m in selected])
        session.close()

    def test_mapping_ids_narrows_but_never_widens(self):
        session = self.Session()
        selected = select_eligible_mappings(session, mapping_ids=[101, 200])
        self.assertEqual([m.id for m in selected], [101])  # 200 is rejected, stays excluded
        session.close()

    def test_limit_caps_result(self):
        session = self.Session()
        selected = select_eligible_mappings(session, limit=2)
        self.assertEqual(len(selected), 2)
        session.close()

    def test_require_approved_false_includes_not_yet_approved_mapping(self):
        session = self.Session()
        # 203 is approved but never manually verified - excluded by default.
        selected = select_eligible_mappings(session, mapping_ids=[203], require_approved=False)
        self.assertEqual([m.id for m in selected], [203])
        session.close()

    def test_require_approved_false_still_excludes_legacy_and_inactive(self):
        session = self.Session()
        # 200 (no card_print_id) and 202 (inactive) stay excluded even with
        # the approval gate off - those are structural gates, not approval.
        selected = select_eligible_mappings(session, mapping_ids=[200, 202, 203], require_approved=False)
        self.assertEqual([m.id for m in selected], [203])
        session.close()


class BatchExecutionTests(BaseBatchTestCase):
    def test_all_success_batch(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: written_outcome(102), 103: written_outcome(103)})
        result = run_batch(session_factory=self.Session, mapping_runner=runner)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(result.results), 3)
        self.assertEqual([mid for mid, _ in runner.calls], [101, 102, 103])

    def test_mapping_level_failure_does_not_stop_batch_or_contaminate_others(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: failed_outcome(102, ["artwork_not_confirmed_match"]), 103: written_outcome(103)})
        result = run_batch(session_factory=self.Session, mapping_runner=runner)
        self.assertEqual(result.status, "partial_failure")
        self.assertEqual(len(result.results), 3)
        self.assertTrue(result.results[0].written)
        self.assertFalse(result.results[1].written)
        self.assertTrue(result.results[2].written)

    def test_source_wide_denial_stops_remaining_batch(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: denied_outcome(102), 103: written_outcome(103)})
        result = run_batch(session_factory=self.Session, mapping_runner=runner)
        self.assertEqual(result.status, "source_wide_failure")
        self.assertEqual(len(result.results), 2)  # 103 never attempted
        self.assertEqual([mid for mid, _ in runner.calls], [101, 102])

    def test_earlier_valid_writes_preserved_after_source_wide_denial(self):
        runner = FakeMappingRunner({101: written_outcome(101, price_jpy=5000), 102: denied_outcome(102)})
        result = run_batch(session_factory=self.Session, mapping_runner=runner, mapping_ids=[101, 102])
        self.assertTrue(result.results[0].written)
        self.assertEqual(result.results[0].price_jpy, 5000)

    def test_each_mapping_called_exactly_once_with_same_batch_run_id(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: written_outcome(102), 103: written_outcome(103)})
        result = run_batch(session_factory=self.Session, mapping_runner=runner)
        batch_run_ids = {brid for _, brid in runner.calls}
        self.assertEqual(len(batch_run_ids), 1)
        self.assertEqual(next(iter(batch_run_ids)), result.batch_run_id)

    def test_validate_only_propagated_to_every_mapping(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: written_outcome(102), 103: written_outcome(103)})
        run_batch(session_factory=self.Session, mapping_runner=runner, validate_only=True)
        self.assertTrue(all(runner.validate_only_calls))

    def test_delay_between_mappings_applied(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: written_outcome(102), 103: written_outcome(103)})
        with patch("snkrdunk_collector.batch.settings") as mock_settings:
            mock_settings.SNKRDUNK_REQUEST_DELAY_MS = 5
            mock_settings.BATCH_TOTAL_TIMEOUT_S = 60
            start = time.monotonic()
            run_batch(session_factory=self.Session, mapping_runner=runner)
            elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.01)  # 2 delays of 5ms

    def test_no_duplicate_mapping_ids_processed(self):
        runner = FakeMappingRunner({101: written_outcome(101), 102: written_outcome(102), 103: written_outcome(103)})
        run_batch(session_factory=self.Session, mapping_runner=runner, mapping_ids=[101, 101, 102])
        mapping_ids_called = [mid for mid, _ in runner.calls]
        self.assertEqual(len(mapping_ids_called), len(set(mapping_ids_called)))

    def test_require_approved_false_without_validate_only_raises(self):
        runner = FakeMappingRunner({})
        with self.assertRaises(ValueError):
            run_batch(
                session_factory=self.Session,
                mapping_runner=runner,
                mapping_ids=[203],
                require_approved=False,
                validate_only=False,
            )

    def test_require_approved_false_with_validate_only_reaches_unapproved_mapping(self):
        runner = FakeMappingRunner({203: failed_outcome(203, ["no_raw_condition_price_available"])})
        result = run_batch(
            session_factory=self.Session,
            mapping_runner=runner,
            mapping_ids=[203],
            require_approved=False,
            validate_only=True,
        )
        self.assertEqual([mid for mid, _ in runner.calls], [203])
        self.assertTrue(all(runner.validate_only_calls))
        self.assertEqual(result.mappings_selected, [203])


if __name__ == "__main__":
    unittest.main()
