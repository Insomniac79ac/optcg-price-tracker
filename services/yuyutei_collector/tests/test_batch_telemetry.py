"""The attempt recorder wired into the real run_batch control flow.

Same offline harness as test_batch.py - selection runs for real against an
in-memory SQLite database, the per-mapping fetch is always a fake, so nothing
here touches Playwright, the network or staging.

WHAT THESE TESTS ARE FOR. The recorder was proved in isolation by
test_telemetry.py; what is unproved until here is that run_batch calls it at
the right three moments, translates its own outcomes faithfully, and - the
part that actually matters - that a broken recorder cannot change what the
batch collects, reports or stops on. Telemetry exists to explain failures, and
a telemetry layer capable of causing one would be worse than none.

Lifecycle assertions that depend on the production CHECK constraints (a
skipped row keeping started_at NULL while carrying a finished_at) are repeated
against real PostgreSQL in test_batch_telemetry_postgres.py, because SQLite
enforces no CHECK here and would accept rows staging rejects.
"""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import telemetry
from yuyutei_collector.batch import run_batch
from yuyutei_collector.collect import MappingOutcome
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

from test_batch import FakeMappingRunner, written_outcome


def _attempted(result) -> int:
    return len(result.results)


def _written(result) -> int:
    return sum(1 for r in result.results if r.written)


def _skipped(result) -> int:
    return len(result.mappings_selected) - len(result.results)


def denied_outcome(mapping_id: int) -> MappingOutcome:
    """A source-wide 403 on the homepage gate - the shape the 2026-09-03
    canary actually produced."""
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="no_extraction_attempted",
        failure_stage="homepage",
        classification="static_403",
        source_denied=True,
        reasons=["no_extraction_attempted:classification=static_403"],
    )


def homepage_timeout_outcome(mapping_id: int) -> MappingOutcome:
    """Mapping 413's shape: the homepage never answered, one mapping lost, the
    batch unaffected."""
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="no_extraction_attempted",
        failure_stage="homepage",
        classification=None,
        source_denied=False,
        reasons=["no_extraction_attempted:classification=None"],
    )


def validation_failed_outcome(mapping_id: int) -> MappingOutcome:
    """Mapping 351's shape."""
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="validation_failed",
        failure_stage="validation",
        classification="normal_product",
        reasons=["price_matches_card_code_or_id_digits:50"],
    )


def operational_error_outcome(mapping_id: int) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="operational_error",
        failure_stage="browser_launch",
        reasons=["watchdog_triggered:browser_launch"],
    )


def mapping_load_failed_outcome(mapping_id: int) -> MappingOutcome:
    return MappingOutcome(
        mapping_id=mapping_id,
        stage="mapping_load_failed",
        failure_stage="load",
        reasons=[f"mapping_not_found:{mapping_id}"],
    )


class BatchTelemetryTestCase(unittest.TestCase):
    MAPPING_COUNT = 3

    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=None
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

        with self.Session() as session:
            source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
            canonical = CanonicalCard(card_code="OP13-050")
            session.add_all([source, canonical])
            session.flush()
            card_print = CardPrint(
                canonical_card_id=canonical.id, verification_status="verified", is_active=True
            )
            session.add(card_print)
            session.flush()
            mappings = [
                SourceCardMapping(
                    source_id=source.id,
                    source_card_id=f"OP13-{i:03d}",
                    source_url=f"https://yuyu-tei.jp/sell/opc/card/op13/{10000 + i}",
                    card_print_id=card_print.id,
                    is_active=True,
                    review_status="approved",
                )
                for i in range(1, self.MAPPING_COUNT + 1)
            ]
            session.add_all(mappings)
            session.commit()
            self.source_id = source.id
            self.mapping_ids = [m.id for m in mappings]

        self._patch = patch.object(telemetry, "SessionLocal", self.Session)
        self._patch.start()
        self.addCleanup(self._patch.stop)

        # Inter-mapping pacing is real (1s per mapping) and is test_batch.py's
        # subject, not this file's - 214 mappings would otherwise spend three
        # and a half minutes sleeping. Patched to zero so these tests measure
        # telemetry, not time.
        self._delay_patch = patch("yuyutei_collector.batch._mapping_delay_s", return_value=0.0)
        self._delay_patch.start()
        self.addCleanup(self._delay_patch.stop)

    def _run(self, outcomes, **kwargs):
        runner = FakeMappingRunner(outcomes)
        result = run_batch(session_factory=self.Session, mapping_runner=runner, **kwargs)
        return result, runner

    def _attempts(self):
        with self.Session() as session:
            return session.execute(
                select(SourceCollectionAttempt).order_by(
                    SourceCollectionAttempt.selection_ordinal
                )
            ).scalars().all()

    def _by_mapping(self):
        return {a.source_card_mapping_id: a for a in self._attempts()}


class OutcomeTranslation(BatchTelemetryTestCase):
    """A-F: every outcome the collector can produce, as the batch records it."""

    def test_a_written_mapping(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, _ = self._run(outcomes)
        self.assertEqual(result.status, "success")
        for mid in self.mapping_ids:
            row = self._by_mapping()[mid]
            self.assertEqual(row.status, "written")
            self.assertIsNone(row.failure_stage)
            self.assertIsNone(row.failure_reason)
            self.assertIsNotNone(row.started_at)
            self.assertIsNotNone(row.finished_at)

    def test_b_validation_failure(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.mapping_ids[1]] = validation_failed_outcome(self.mapping_ids[1])
        self._run(outcomes)
        row = self._by_mapping()[self.mapping_ids[1]]
        self.assertEqual(row.status, "validation_failed")
        self.assertEqual(row.failure_stage, "validation")
        self.assertEqual(row.failure_reason, "price_matches_card_code_or_id_digits:50")
        self.assertFalse(row.source_denied)

    def test_c_homepage_timeout_costs_exactly_one_mapping(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        victim = self.mapping_ids[1]
        outcomes[victim] = homepage_timeout_outcome(victim)
        result, runner = self._run(outcomes)

        # The batch did not stop: every mapping was still attempted.
        self.assertEqual(len(runner.calls), self.MAPPING_COUNT)
        self.assertIsNone(result.stopped_reason)
        rows = self._by_mapping()
        self.assertEqual(rows[victim].status, "no_extraction_attempted")
        self.assertEqual(rows[victim].failure_stage, "homepage")
        self.assertEqual(rows[self.mapping_ids[2]].status, "written")

    def test_e_operational_error(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.mapping_ids[0]] = operational_error_outcome(self.mapping_ids[0])
        self._run(outcomes)
        row = self._by_mapping()[self.mapping_ids[0]]
        self.assertEqual(row.status, "operational_error")
        self.assertEqual(row.failure_stage, "browser_launch")

    def test_f_mapping_load_failure(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.mapping_ids[0]] = mapping_load_failed_outcome(self.mapping_ids[0])
        self._run(outcomes)
        row = self._by_mapping()[self.mapping_ids[0]]
        self.assertEqual(row.status, "mapping_load_failed")
        self.assertEqual(row.failure_stage, "load")

    def test_h_a_written_row_links_the_observation_that_was_actually_written(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        self._run(outcomes)
        for mid in self.mapping_ids:
            self.assertEqual(
                self._by_mapping()[mid].price_observation_id,
                outcomes[mid].observation_id,
            )

    def test_a_failed_attempt_carries_no_observation_id(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.mapping_ids[0]] = validation_failed_outcome(self.mapping_ids[0])
        outcomes[self.mapping_ids[1]] = homepage_timeout_outcome(self.mapping_ids[1])
        self._run(outcomes)
        rows = self._by_mapping()
        self.assertIsNone(rows[self.mapping_ids[0]].price_observation_id)
        self.assertIsNone(rows[self.mapping_ids[1]].price_observation_id)


class SourceDenialLifecycle(BatchTelemetryTestCase):
    """D: the contract that must not move."""

    def setUp(self):
        super().setUp()
        self.denied = self.mapping_ids[1]
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.denied] = denied_outcome(self.denied)
        self.result, self.runner = self._run(outcomes)

    def test_the_batch_still_stops_exactly_where_it_did(self):
        self.assertEqual(self.result.status, "source_wide_failure")
        self.assertEqual(self.result.exit_code, 1)
        self.assertEqual(self.result.stopped_reason, "source_denied:static_403")
        self.assertEqual(_attempted(self.result), 2)
        self.assertEqual(_written(self.result), 1)
        self.assertEqual(_skipped(self.result), 1)

    def test_no_further_navigation_happened(self):
        """The mapping after the denial was never handed to the runner."""
        self.assertEqual([c[0] for c in self.runner.calls], self.mapping_ids[:2])

    def test_the_denied_mapping_keeps_its_own_terminal_outcome(self):
        row = self._by_mapping()[self.denied]
        self.assertEqual(row.status, "no_extraction_attempted")
        self.assertEqual(row.failure_stage, "homepage")
        self.assertTrue(row.source_denied)
        self.assertIsNotNone(row.started_at)  # it really did start

    def test_the_remaining_mapping_is_skipped_and_never_started(self):
        row = self._by_mapping()[self.mapping_ids[2]]
        self.assertEqual(row.status, "skipped")
        self.assertIsNone(row.started_at)
        self.assertIsNotNone(row.finished_at)
        self.assertTrue(row.source_denied)
        self.assertEqual(row.failure_reason, "source_denied:static_403")

    def test_no_start_was_fabricated_for_the_skipped_mapping(self):
        started = [
            a.source_card_mapping_id for a in self._attempts() if a.started_at is not None
        ]
        self.assertEqual(started, self.mapping_ids[:2])

    def test_j_no_selected_row_is_left_unfinished(self):
        for row in self._attempts():
            self.assertNotEqual(row.status, "selected")
            self.assertIsNotNone(row.finished_at)


class OrdinalsAndIntegrity(BatchTelemetryTestCase):
    """I, J, L."""

    def test_i_ordinals_are_one_based_and_match_execution_order(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        _, runner = self._run(outcomes)
        rows = self._attempts()
        self.assertEqual([r.selection_ordinal for r in rows], [1, 2, 3])
        self.assertEqual(
            [r.source_card_mapping_id for r in rows], [c[0] for c in runner.calls]
        )

    def test_exactly_one_row_per_mapping(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        self._run(outcomes)
        rows = self._attempts()
        self.assertEqual(len(rows), self.MAPPING_COUNT)
        self.assertEqual(
            len({r.source_card_mapping_id for r in rows}), self.MAPPING_COUNT
        )

    def test_one_ordinal_per_position(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        self._run(outcomes)
        ordinals = [r.selection_ordinal for r in self._attempts()]
        self.assertEqual(len(ordinals), len(set(ordinals)))

    def test_j_a_complete_batch_leaves_zero_selected_rows(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        self._run(outcomes)
        self.assertEqual([r for r in self._attempts() if r.status == "selected"], [])

    def test_every_row_carries_the_run_and_the_real_ids(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, _ = self._run(outcomes)
        for row in self._attempts():
            self.assertEqual(row.batch_run_id, result.batch_run_id)
            self.assertEqual(row.source_id, self.source_id)
            self.assertIn(row.source_card_mapping_id, self.mapping_ids)

    def test_terminal_rows_cannot_be_rewritten_afterwards(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, _ = self._run(outcomes)
        target = self.mapping_ids[0]
        self.assertIs(
            telemetry.finish_attempt(result.batch_run_id, target, "skipped"), False
        )
        self.assertEqual(self._by_mapping()[target].status, "written")


class StageCoverage(BatchTelemetryTestCase):
    """Every stage the collector can return has a disposition - checked
    against the source, not against the examples that happen to be tested."""

    STAGES_WITH_A_STATUS = {
        "written",
        "validation_failed",
        "no_extraction_attempted",
        "operational_error",
        "mapping_load_failed",
    }

    def _collect_source(self):
        from pathlib import Path

        import yuyutei_collector.collect as collect_module

        return Path(collect_module.__file__).read_text()

    def test_every_stage_the_collector_returns_is_accounted_for(self):
        """Fails if a new MappingOutcome stage appears without a decision about
        what it means for telemetry."""
        import re

        stages = set(re.findall(r'\bstage="([a-z_]+)"', self._collect_source()))
        unaccounted = stages - self.STAGES_WITH_A_STATUS - {"validated_only"}
        self.assertEqual(unaccounted, set(), f"stage with no telemetry disposition: {unaccounted}")

    def test_validated_only_is_produced_only_under_validate_only(self):
        """Q1, structurally: the sole `validated_only` return sits inside the
        `if validate_only:` branch, and run_batch records nothing when
        validate_only is set - so the two can never meet."""
        source = self._collect_source()
        before = source.index("if validate_only:")
        self.assertGreater(source.index('stage="validated_only"'), before)
        self.assertEqual(source.count('stage="validated_only"'), 1)

        from pathlib import Path

        import yuyutei_collector.batch as batch_module

        self.assertIn(
            "record_telemetry = not validate_only", Path(batch_module.__file__).read_text()
        )

    def test_a_validated_only_outcome_leaves_no_selected_row(self):
        """Q1, behaviourally: even if a runner returned `validated_only` in a
        recording batch - which production cannot do - no row is stranded in
        'selected', because in that mode no rows are created at all."""
        outcomes = {
            mid: MappingOutcome(mapping_id=mid, stage="validated_only", written=False)
            for mid in self.mapping_ids
        }
        self._run(outcomes, validate_only=True)
        self.assertEqual(self._attempts(), [])
        self.assertEqual([r for r in self._attempts() if r.status == "selected"], [])


class ValidateOnlyRecordsNothing(BatchTelemetryTestCase):
    def test_a_dry_run_writes_no_attempt_history(self):
        """validate_only writes no observation and no snapshot; it must not
        write attempt rows either, or dry runs would pollute the table
        operators read to find out why real collection produced nothing."""
        outcomes = {
            mid: MappingOutcome(mapping_id=mid, stage="validated_only", written=False)
            for mid in self.mapping_ids
        }
        self._run(outcomes, validate_only=True)
        self.assertEqual(self._attempts(), [])


class TelemetryFailureCannotAffectCollection(BatchTelemetryTestCase):
    """G: the boundary that justifies the whole design."""

    def _baseline(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        outcomes[self.mapping_ids[1]] = validation_failed_outcome(self.mapping_ids[1])
        return outcomes

    def _result_fingerprint(self, result, runner):
        return (
            result.status,
            result.exit_code,
            result.stopped_reason,
            list(result.mappings_selected),
            _attempted(result),
            _written(result),
            _skipped(result),
            [c[0] for c in runner.calls],
        )

    def test_a_totally_broken_recorder_changes_nothing(self):
        outcomes = self._baseline()
        good_result, good_runner = self._run(outcomes)
        good = self._result_fingerprint(good_result, good_runner)

        with self.Session() as session:
            for row in session.execute(select(SourceCollectionAttempt)).scalars().all():
                session.delete(row)
            session.commit()

        def broken():
            raise RuntimeError("telemetry database is gone")

        with patch.object(telemetry, "SessionLocal", broken):
            bad_result, bad_runner = self._run(outcomes)

        self.assertEqual(self._result_fingerprint(bad_result, bad_runner), good)

    def _run_with_one_primitive_broken(self, name):
        def boom(*args, **kwargs):
            raise RuntimeError(f"{name} exploded")

        outcomes = self._baseline()
        with patch.object(telemetry, name, boom):
            return self._run(outcomes)

    def test_a_raising_primitive_does_not_stop_the_batch(self):
        """Defence in depth. telemetry.* already swallows its own failures and
        returns a bool, so a raising primitive means the recorder broke its own
        contract - and even then the batch must complete, because run_batch
        routes every telemetry call through _record."""
        for name in (
            "record_selected_batch",
            "mark_attempt_started",
            "finish_attempt",
        ):
            with self.subTest(primitive=name):
                result, runner = self._run_with_one_primitive_broken(name)
                self.assertEqual(len(runner.calls), self.MAPPING_COUNT)
                self.assertEqual(_written(result), self.MAPPING_COUNT - 1)

    def test_collection_still_writes_when_the_recorder_is_unavailable(self):
        """The property that matters: a valid observation is not suppressed."""
        outcomes = self._baseline()

        def broken():
            raise RuntimeError("telemetry database is gone")

        with patch.object(telemetry, "SessionLocal", broken):
            result, runner = self._run(outcomes)

        self.assertEqual(_written(result), self.MAPPING_COUNT - 1)
        self.assertEqual(len(runner.calls), self.MAPPING_COUNT)
        self.assertEqual(self._attempts(), [])  # nothing recorded, nothing lost

    def test_a_broken_recorder_adds_no_source_request(self):
        outcomes = self._baseline()

        def broken():
            raise RuntimeError("telemetry database is gone")

        with patch.object(telemetry, "SessionLocal", broken):
            _, runner = self._run(outcomes)

        # Exactly one runner call per mapping - no retry, no extra fetch.
        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids)

    def test_a_broken_recorder_preserves_source_denial_semantics(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        denied = self.mapping_ids[1]
        outcomes[denied] = denied_outcome(denied)

        def broken():
            raise RuntimeError("telemetry database is gone")

        with patch.object(telemetry, "SessionLocal", broken):
            result, runner = self._run(outcomes)

        self.assertEqual(result.status, "source_wide_failure")
        self.assertEqual(result.stopped_reason, "source_denied:static_403")
        self.assertEqual(_skipped(result), 1)
        self.assertEqual([c[0] for c in runner.calls], self.mapping_ids[:2])


class SingleMappingCliBoundary(BatchTelemetryTestCase):
    """K: the --mapping-id path is deliberately NOT wired in this tranche.

    run_one_mapping has no batch and therefore no batch_run_id, and the
    required lifecycle here is defined over a selected population. Wiring it
    would mean minting a synthetic run id for a run of one, which is a
    decision worth making explicitly rather than as a side effect of this
    change. Because nothing outside a recorded population can be written,
    selection_ordinal is NOT NULL - there is no "no position" row left to
    describe. These tests record the boundary and will fail loudly if the CLI
    is wired without revisiting it.
    """

    def test_the_cli_path_is_unchanged_and_records_nothing(self):
        from yuyutei_collector import collect

        mapping_id = self.mapping_ids[0]
        with patch.object(
            collect,
            "run_one_mapping_detailed",
            return_value=written_outcome(mapping_id),
        ):
            exit_code = collect.run_one_mapping(mapping_id)

        self.assertEqual(exit_code, 0)
        self.assertEqual(self._attempts(), [])

    def test_a_standalone_attempt_cannot_be_recorded_at_all(self):
        """The table is batch-scoped. With no recorded population there is no
        row to update and none is created, so a would-be CLI attempt leaves no
        trace - which is why selection_ordinal could be tightened to NOT NULL."""
        self.assertIs(
            telemetry.finish_attempt("solo00000001", self.mapping_ids[0], "written"),
            False,
        )
        self.assertEqual(self._attempts(), [])


class LargeBatchOrdering(BatchTelemetryTestCase):
    """L: the 214-mapping ordering semantics, at a size that would expose an
    off-by-one or a re-sort."""

    MAPPING_COUNT = 214

    def test_ordinals_follow_selection_order_across_the_whole_population(self):
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        result, runner = self._run(outcomes)
        self.assertEqual(len(result.mappings_selected), 214)
        self.assertEqual(_written(result), 214)

        rows = self._attempts()
        self.assertEqual([r.selection_ordinal for r in rows], list(range(1, 215)))
        self.assertEqual(
            [r.source_card_mapping_id for r in rows], [c[0] for c in runner.calls]
        )
        self.assertEqual([r.source_card_mapping_id for r in rows], self.mapping_ids)

    def test_a_denial_at_position_177_skips_exactly_the_tail(self):
        """Mapping 413 sat at position 177 of 214 in the real run; a denial
        there must leave 37 skipped rows, none of them started."""
        outcomes = {mid: written_outcome(mid) for mid in self.mapping_ids}
        denied = self.mapping_ids[176]  # 1-based position 177
        outcomes[denied] = denied_outcome(denied)
        result, runner = self._run(outcomes)

        self.assertEqual(_attempted(result), 177)
        self.assertEqual(_skipped(result), 37)
        self.assertEqual(len(runner.calls), 177)

        rows = self._attempts()
        skipped = [r for r in rows if r.status == "skipped"]
        self.assertEqual(len(skipped), 37)
        self.assertTrue(all(r.started_at is None for r in skipped))
        self.assertTrue(all(r.finished_at is not None for r in skipped))
        self.assertEqual([r.selection_ordinal for r in skipped], list(range(178, 215)))
        self.assertEqual([r for r in rows if r.status == "selected"], [])


if __name__ == "__main__":
    unittest.main()
