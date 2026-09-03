"""yuyutei_collector.telemetry - the best-effort recorder primitive.

WHAT THIS PROTECTS. Telemetry exists because failure left no evidence; it must
never become a reason for failure. Two properties carry that, and both are
asserted here rather than assumed:

  * A telemetry failure never reaches collection code. Every function returns
    a bool and raises nothing, whatever the database does.
  * The telemetry session is independent of the caller's. A rolled-back
    pricing transaction must still leave the row explaining why it rolled
    back, and a failed telemetry write must not roll back a good observation.
    Those are opposite directions and only a separate short-lived session
    satisfies both, so both directions get a test.

In-memory SQLite via the collector's own models - no network, no staging
database. SQLite does not enforce the CHECK vocabulary that Postgres does;
that half is covered by
services/api/tests/test_source_collection_attempts_postgres.py.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import telemetry
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    STATUS_SELECTED,
    STATUS_SKIPPED,
    STATUS_WRITTEN,
    CardPrint,
    CanonicalCard,
    PriceObservation,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

RUN = "batch0001"


class TelemetryTestCase(unittest.TestCase):
    def setUp(self):
        # One shared in-memory database across connections, so the recorder's
        # own independent session sees the same data as the test's.
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
            print_row = CardPrint(
                canonical_card_id=canonical.id, verification_status="verified", is_active=True
            )
            session.add(print_row)
            session.flush()
            mappings = [
                SourceCardMapping(
                    source_id=source.id,
                    source_card_id=f"OP13-{i:03d}",
                    source_url=f"https://yuyu-tei.jp/sell/opc/card/op13/{10000 + i}",
                    card_print_id=print_row.id,
                    is_active=True,
                    review_status="approved",
                )
                for i in (50, 51, 52)
            ]
            session.add_all(mappings)
            session.commit()
            self.source_id = source.id
            self.print_id = print_row.id
            self.mapping_ids = [m.id for m in mappings]

        self._patch = patch.object(telemetry, "SessionLocal", self.Session)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _rows(self):
        with self.Session() as session:
            return session.execute(
                select(SourceCollectionAttempt).order_by(SourceCollectionAttempt.id)
            ).scalars().all()


class RecordSelectedBatch(TelemetryTestCase):
    def test_the_whole_population_is_persisted_in_one_call(self):
        assert telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids) is True
        rows = self._rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r.status for r in rows}, {STATUS_SELECTED})
        self.assertEqual({r.batch_run_id for r in rows}, {RUN})

    def test_selection_order_is_recorded(self):
        ordered = list(reversed(self.mapping_ids))
        telemetry.record_selected_batch(RUN, self.source_id, ordered)
        with self.Session() as session:
            rows = session.execute(
                select(SourceCollectionAttempt).order_by(
                    SourceCollectionAttempt.selection_ordinal
                )
            ).scalars().all()
        self.assertEqual([r.selection_ordinal for r in rows], [1, 2, 3])
        self.assertEqual([r.source_card_mapping_id for r in rows], ordered)

    def test_a_selected_row_has_no_started_at(self):
        """The distinction the table exists for: selected is not started."""
        telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids)
        self.assertTrue(all(r.started_at is None for r in self._rows()))
        self.assertTrue(all(r.selected_at is not None for r in self._rows()))

    def test_an_empty_population_writes_nothing_and_succeeds(self):
        self.assertIs(telemetry.record_selected_batch(RUN, self.source_id, []), True)
        self.assertEqual(self._rows(), [])

    def test_the_population_is_all_or_nothing(self):
        """A partial population would be worse than none: a later reader could
        not tell a short list from an aborted write."""
        bad = [*self.mapping_ids, 999999]  # violates the mapping FK
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        result = telemetry.record_selected_batch(RUN, self.source_id, bad)
        # Either the driver enforced the FK (no rows) or it did not (all rows),
        # but never a partial write of only the valid ids.
        self.assertIn(len(self._rows()), (0, len(bad)))
        self.assertIsInstance(result, bool)


class MarkAndFinish(TelemetryTestCase):
    def setUp(self):
        super().setUp()
        telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids)

    def test_mark_attempt_started_stamps_the_existing_row(self):
        target = self.mapping_ids[1]
        assert telemetry.mark_attempt_started(RUN, target) is True
        rows = {r.source_card_mapping_id: r for r in self._rows()}
        self.assertIsNotNone(rows[target].started_at)
        self.assertIsNone(rows[self.mapping_ids[0]].started_at)
        # Still one row per (run, mapping) - it updated, it did not insert.
        self.assertEqual(len(self._rows()), 3)

    def test_finish_attempt_records_the_outcome(self):
        target = self.mapping_ids[0]
        telemetry.mark_attempt_started(RUN, target)
        assert (
            telemetry.finish_attempt(
                RUN, target, STATUS_WRITTEN, price_observation_id=None
            )
            is True
        )
        row = {r.source_card_mapping_id: r for r in self._rows()}[target]
        self.assertEqual(row.status, STATUS_WRITTEN)
        self.assertIsNotNone(row.finished_at)
        self.assertIsNotNone(row.started_at)

    def test_finish_attempt_records_a_failure_stage_and_reason(self):
        target = self.mapping_ids[0]
        telemetry.finish_attempt(
            RUN,
            target,
            "validation_failed",
            failure_stage="validation",
            failure_reason="price_matches_card_code_or_id_digits:50",
        )
        row = {r.source_card_mapping_id: r for r in self._rows()}[target]
        self.assertEqual(row.failure_stage, "validation")
        self.assertEqual(row.failure_reason, "price_matches_card_code_or_id_digits:50")

    def test_selected_to_skipped_finishes_without_ever_starting(self):
        """THE lifecycle case: the batch aborted before reaching this mapping.
        The row must become skipped with a finished_at and NO started_at - an
        earlier draft invented a start here to satisfy a CHECK, which recorded
        an event that never happened."""
        target = self.mapping_ids[2]
        assert telemetry.finish_attempt(
            RUN, target, STATUS_SKIPPED, source_denied=True,
            failure_reason="source_denied:static_403",
        ) is True
        row = {r.source_card_mapping_id: r for r in self._rows()}[target]
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertIsNone(row.started_at)
        self.assertIsNotNone(row.finished_at)
        self.assertTrue(row.source_denied)
        self.assertEqual(row.failure_reason, "source_denied:static_403")

    def test_an_over_long_reason_is_truncated_not_rejected(self):
        """Losing the tail of a reason beats losing the whole row."""
        target = self.mapping_ids[0]
        telemetry.finish_attempt(
            RUN, target, "operational_error", failure_reason="x" * 5000
        )
        row = {r.source_card_mapping_id: r for r in self._rows()}[target]
        self.assertEqual(len(row.failure_reason), 500)

    def test_finish_without_a_prior_row_is_declined(self):
        """The table is batch-scoped: record_selected_batch is its only INSERT,
        so an attempt exists exactly when its mapping was part of a recorded
        population. With no such row there is nothing to finish, and the call
        declines rather than conjuring an attempt belonging to no run."""
        before = len(self._rows())
        self.assertIs(
            telemetry.finish_attempt("solo0001", self.mapping_ids[0], STATUS_WRITTEN),
            False,
        )
        self.assertEqual(len(self._rows()), before)

    def test_mark_started_without_a_prior_row_is_declined(self):
        before = len(self._rows())
        self.assertIs(telemetry.mark_attempt_started("solo0002", self.mapping_ids[0]), False)
        self.assertEqual(len(self._rows()), before)

    def test_a_caller_that_knows_a_start_time_may_supply_it(self):
        """finish_attempt still accepts an explicit start for a selected row
        whose start was never separately recorded - it just never invents one."""
        started = datetime.now(timezone.utc) - timedelta(seconds=4)
        target = self.mapping_ids[0]
        telemetry.finish_attempt(RUN, target, STATUS_WRITTEN, started_at=started)
        row = {r.source_card_mapping_id: r for r in self._rows()}[target]
        self.assertIsNotNone(row.started_at)


    def test_price_observation_id_is_linked_when_supplied(self):
        with self.Session() as session:
            observation = PriceObservation(
                source_id=self.source_id,
                observed_at=datetime.now(timezone.utc),
                price_type="sell",
                price_jpy=50,
                card_print_id=self.print_id,
                source_card_mapping_id=self.mapping_ids[0],
            )
            session.add(observation)
            session.commit()
            observation_id = observation.id
        telemetry.finish_attempt(
            RUN, self.mapping_ids[0], STATUS_WRITTEN, price_observation_id=observation_id
        )
        row = {r.source_card_mapping_id: r for r in self._rows()}[self.mapping_ids[0]]
        self.assertEqual(row.price_observation_id, observation_id)


class LifecycleTransitions(TelemetryTestCase):
    """Every transition the wiring will need, end to end through the recorder."""

    def setUp(self):
        super().setUp()
        telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids)

    def _row(self, mapping_id):
        return {r.source_card_mapping_id: r for r in self._rows()}[mapping_id]

    def test_selected_to_written(self):
        target = self.mapping_ids[0]
        self.assertEqual(self._row(target).status, STATUS_SELECTED)
        telemetry.mark_attempt_started(RUN, target)
        assert telemetry.finish_attempt(RUN, target, STATUS_WRITTEN) is True
        row = self._row(target)
        self.assertEqual(row.status, STATUS_WRITTEN)
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.finished_at)

    def test_selected_to_started_to_validation_failed(self):
        target = self.mapping_ids[0]
        telemetry.mark_attempt_started(RUN, target)
        assert telemetry.finish_attempt(
            RUN, target, "validation_failed", failure_stage="validation",
            failure_reason="price_matches_card_code_or_id_digits:50",
        ) is True
        row = self._row(target)
        self.assertEqual(row.status, "validation_failed")
        self.assertEqual(row.failure_stage, "validation")
        self.assertIsNotNone(row.started_at)

    def test_selected_to_started_to_operational_error(self):
        target = self.mapping_ids[1]
        telemetry.mark_attempt_started(RUN, target)
        assert telemetry.finish_attempt(
            RUN, target, "operational_error", failure_stage="browser_launch",
            failure_reason="watchdog_triggered:browser_launch",
        ) is True
        row = self._row(target)
        self.assertEqual(row.status, "operational_error")
        self.assertEqual(row.failure_stage, "browser_launch")

    def test_selected_to_skipped_without_a_start(self):
        target = self.mapping_ids[2]
        assert telemetry.finish_attempt(RUN, target, STATUS_SKIPPED) is True
        row = self._row(target)
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertIsNone(row.started_at)
        self.assertIsNotNone(row.finished_at)

    def test_selected_to_started_to_skipped(self):
        """Not produced by today's batch flow - it breaks BEFORE starting the
        next mapping - but nothing forbids it, and a row that started and was
        then abandoned should record both facts rather than be unrepresentable."""
        target = self.mapping_ids[1]
        telemetry.mark_attempt_started(RUN, target)
        assert telemetry.finish_attempt(RUN, target, STATUS_SKIPPED) is True
        row = self._row(target)
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertIsNotNone(row.started_at)
        self.assertIsNotNone(row.finished_at)

    def test_a_terminal_row_is_not_silently_overwritten(self):
        """An outcome is recorded once. A second finish is either a wiring bug
        or a retry, and either way it would replace the real reason a mapping
        failed with a later, blander one."""
        target = self.mapping_ids[0]
        telemetry.mark_attempt_started(RUN, target)
        telemetry.finish_attempt(
            RUN, target, "validation_failed", failure_stage="validation",
            failure_reason="the real reason",
        )
        self.assertIs(
            telemetry.finish_attempt(RUN, target, STATUS_WRITTEN), False
        )
        row = self._row(target)
        self.assertEqual(row.status, "validation_failed")
        self.assertEqual(row.failure_reason, "the real reason")

    def test_a_repeated_identical_finish_is_still_refused(self):
        """Not absorbed as a harmless no-op. Deciding it were identical means
        reading the values to compare them, which is the beginning of a merge
        policy - and a duplicate finish is a wiring bug worth surfacing."""
        target = self.mapping_ids[0]
        first = dict(
            failure_stage="validation", failure_reason="price_missing_or_ambiguous"
        )
        telemetry.finish_attempt(RUN, target, "validation_failed", **first)
        finished_at = self._row(target).finished_at
        self.assertIs(
            telemetry.finish_attempt(RUN, target, "validation_failed", **first), False
        )
        # Not even the timestamp moved.
        self.assertEqual(self._row(target).finished_at, finished_at)

    def test_starting_a_terminal_row_is_refused(self):
        target = self.mapping_ids[0]
        telemetry.finish_attempt(RUN, target, STATUS_SKIPPED)
        self.assertIs(telemetry.mark_attempt_started(RUN, target), False)
        self.assertIsNone(self._row(target).started_at)

    def test_no_public_primitive_can_mutate_a_terminal_row(self):
        """The whole public surface, against a row that is already done."""
        target = self.mapping_ids[0]
        telemetry.mark_attempt_started(RUN, target)
        telemetry.finish_attempt(
            RUN, target, "validation_failed", failure_stage="validation",
            failure_reason="the real reason",
        )
        before = self._row(target)
        snapshot = (
            before.status, before.failure_stage, before.failure_reason,
            before.started_at, before.finished_at, before.selection_ordinal,
            before.source_denied, before.price_observation_id,
        )

        self.assertIs(telemetry.mark_attempt_started(RUN, target), False)
        self.assertIs(telemetry.finish_attempt(RUN, target, STATUS_WRITTEN), False)
        self.assertIs(
            telemetry.finish_attempt(
                RUN, target, STATUS_SKIPPED, source_denied=True,
                failure_reason="a later, blander reason", price_observation_id=1,
            ),
            False,
        )
        # record_selected_batch cannot reach it either: the unique constraint
        # on (batch_run_id, source_card_mapping_id) makes a re-selection of the
        # same run fail as a whole rather than reset a row.
        self.assertIs(
            telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids), False
        )

        after = self._row(target)
        self.assertEqual(
            (
                after.status, after.failure_stage, after.failure_reason,
                after.started_at, after.finished_at, after.selection_ordinal,
                after.source_denied, after.price_observation_id,
            ),
            snapshot,
        )

    def test_there_is_no_overwrite_flag_on_the_public_api(self):
        """A forensic record with a documented bypass is one bad call site away
        from not being a forensic record, so the parameter must not exist."""
        import inspect

        for fn in (
            telemetry.finish_attempt,
            telemetry.mark_attempt_started,
            telemetry.record_selected_batch,
        ):
            params = set(inspect.signature(fn).parameters)
            self.assertNotIn("allow_terminal_overwrite", params)
            self.assertNotIn("force", params)


class NeverRaisesIntoCollection(TelemetryTestCase):
    """Every entry point, with the database sabotaged."""

    def _broken_session(self):
        def factory():
            raise RuntimeError("database is gone")

        return patch.object(telemetry, "SessionLocal", factory)

    def test_record_selected_batch_swallows_a_database_failure(self):
        with self._broken_session():
            self.assertIs(
                telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids), False
            )

    def test_mark_attempt_started_swallows_a_database_failure(self):
        with self._broken_session():
            self.assertIs(telemetry.mark_attempt_started(RUN, self.mapping_ids[0]), False)

    def test_finish_attempt_swallows_a_database_failure(self):
        with self._broken_session():
            self.assertIs(
                telemetry.finish_attempt(RUN, self.mapping_ids[0], STATUS_WRITTEN), False
            )

    def test_a_failure_falls_back_to_one_json_line_on_stdout(self):
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with self._broken_session(), redirect_stdout(buffer):
            telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids)
        printed = buffer.getvalue().strip()
        self.assertIn("telemetry_write_failed", printed)
        self.assertEqual(len(printed.splitlines()), 1)

    def test_a_commit_failure_is_swallowed_too(self):
        """Not just a session that will not open - one that opens and then
        refuses to commit."""

        class RefusingSession:
            def __init__(self, *a, **kw):
                pass

            def add_all(self, *a, **kw):
                pass

            def add(self, *a, **kw):
                pass

            def execute(self, *a, **kw):
                raise RuntimeError("connection reset")

            def commit(self):
                raise RuntimeError("connection reset")

            def close(self):
                pass

        with patch.object(telemetry, "SessionLocal", RefusingSession):
            self.assertIs(
                telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids), False
            )
            self.assertIs(
                telemetry.finish_attempt(RUN, self.mapping_ids[0], STATUS_WRITTEN), False
            )


class SessionIndependence(TelemetryTestCase):
    """The direction SQLite can prove honestly."""

    # The other direction - "telemetry survives a rollback of the caller" -
    # needs two genuinely concurrent write transactions, which in-memory
    # SQLite cannot provide: every session here shares one DBAPI connection,
    # so a telemetry commit would also commit the caller's pending work and
    # the test would pass for the wrong reason. It lives in
    # test_telemetry_postgres.py against a real engine instead.

    def test_a_telemetry_failure_cannot_roll_back_caller_data(self):
        """The opposite direction: the caller's uncommitted work is untouched
        by a telemetry write that fails."""
        caller = self.Session()
        caller.add(
            PriceObservation(
                source_id=self.source_id,
                observed_at=datetime.now(timezone.utc),
                price_type="sell",
                price_jpy=50,
                card_print_id=self.print_id,
                source_card_mapping_id=self.mapping_ids[1],
            )
        )
        caller.flush()

        def factory():
            raise RuntimeError("database is gone")

        with patch.object(telemetry, "SessionLocal", factory):
            self.assertIs(
                telemetry.record_selected_batch(RUN, self.source_id, self.mapping_ids), False
            )

        caller.commit()   # must still succeed
        caller.close()
        with self.Session() as session:
            observations = session.execute(select(PriceObservation)).scalars().all()
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].price_jpy, 50)


class IntegrationPoints(unittest.TestCase):
    """Where the recorder is called from, pinned.

    Replaces 1A's "not yet wired in" guard. The orchestration layer owns the
    batch id and the loop, so all three calls live in batch.py; collect.py
    stays free of telemetry entirely, which is what keeps a single mapping's
    collection logic unaware of whether anything is recording it."""

    def _source(self, module):
        from pathlib import Path

        return (Path(telemetry.__file__).parent / module).read_text()

    def test_batch_calls_all_three_primitives(self):
        source = self._source("batch.py")
        for primitive in (
            "telemetry.record_selected_batch",
            "telemetry.mark_attempt_started",
            "telemetry.finish_attempt",
        ):
            self.assertIn(primitive, source)

    def test_every_telemetry_call_goes_through_the_guard(self):
        """_record is what makes "a telemetry problem cannot reach the pricing
        job" true at the CALL SITE, independent of the recorder keeping its own
        contract. A primitive invoked directly would be a hole in that
        guarantee, so this asserts the shape with the parser rather than with a
        substring that reformatting could defeat."""
        import ast

        tree = ast.parse(self._source("batch.py"))
        called_directly = []
        passed_to_record = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # telemetry.X(...) - a direct invocation
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "telemetry"
            ):
                called_directly.append(func.attr)
            # _record(telemetry.X, ...) - the guarded form
            if isinstance(func, ast.Name) and func.id == "_record" and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Attribute)
                    and isinstance(first.value, ast.Name)
                    and first.value.id == "telemetry"
                ):
                    passed_to_record += 1

        self.assertEqual(called_directly, [], "telemetry invoked without _record")
        # selection, start, finish, and the skipped remainder
        self.assertEqual(passed_to_record, 4)

    def test_collect_does_not_reference_telemetry(self):
        self.assertNotIn("telemetry", self._source("collect.py"))


if __name__ == "__main__":
    unittest.main()
