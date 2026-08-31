"""Fair, bounded selection for `--approved-mappings`.

WHAT THIS PROTECTS. Collection is serial, so a run's cost grows with the
approved population while BATCH_TOTAL_TIMEOUT_S stays fixed. Under the old
id-ascending order the run was cut off at the same point every night and the
tail was never collected at all. These tests pin the two properties that fix
that - a bounded run, and an order that makes truncation harmless - and the
eligibility rules that must NOT have changed along the way.

The starvation test is the important one: it simulates consecutive runs and
asserts every mapping is actually reached, which is the behaviour the whole
change exists to produce.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from snkrdunk_collector.batch import run_batch, select_eligible_mappings
from snkrdunk_collector.config import settings
from snkrdunk_collector.models import Base, CardPrint, Source, SourceCardMapping

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


class FairSchedulingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db: Session = self.Session()
        self.source = Source(id=1, name="snkrdunk", base_url="https://snkrdunk.com")
        self.db.add(self.source)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def add_mapping(
        self,
        mapping_id: int,
        *,
        attempted_at: datetime | None = None,
        review_status: str = "approved",
        manual_verified: bool = True,
        is_active: bool = True,
        print_active: bool = True,
        print_status: str = "verified",
        card_print_id: int | None = None,
    ) -> SourceCardMapping:
        pid = card_print_id if card_print_id is not None else 1000 + mapping_id
        self.db.add(
            CardPrint(
                id=pid,
                canonical_card_id=1,
                language="jp",
                is_active=print_active,
                verification_status=print_status,
            )
        )
        m = SourceCardMapping(
            id=mapping_id,
            card_id=None,
            source_id=self.source.id,
            card_print_id=pid,
            source_card_id=str(mapping_id),
            source_url=f"https://snkrdunk.com/apparels/{mapping_id}",
            is_active=is_active,
            review_status=review_status,
            manual_verified=manual_verified,
            last_collection_attempted_at=attempted_at,
        )
        self.db.add(m)
        self.db.commit()
        return m

    def selected_ids(self, **kwargs) -> list[int]:
        return [m.id for m in select_eligible_mappings(self.db, **kwargs)]


class OrderingTests(FairSchedulingTestCase):
    def test_never_collected_mappings_rank_first(self):
        self.add_mapping(1, attempted_at=NOW - timedelta(days=5))
        self.add_mapping(2, attempted_at=None)
        self.add_mapping(3, attempted_at=NOW - timedelta(days=90))
        self.add_mapping(4, attempted_at=None)
        # Both never-attempted rows precede every attempted one, however old.
        self.assertEqual(self.selected_ids()[:2], [2, 4])

    def test_oldest_collected_ranks_before_newer(self):
        self.add_mapping(1, attempted_at=NOW - timedelta(hours=1))
        self.add_mapping(2, attempted_at=NOW - timedelta(days=7))
        self.add_mapping(3, attempted_at=NOW - timedelta(days=2))
        self.assertEqual(self.selected_ids(), [2, 3, 1])

    def test_tie_break_is_deterministic_by_id(self):
        same = NOW - timedelta(days=1)
        for mid in (7, 3, 9, 1):
            self.add_mapping(mid, attempted_at=same)
        self.assertEqual(self.selected_ids(), [1, 3, 7, 9])

    def test_never_collected_tie_break_is_also_by_id(self):
        for mid in (5, 2, 8):
            self.add_mapping(mid, attempted_at=None)
        self.assertEqual(self.selected_ids(), [2, 5, 8])

    def test_ordering_is_stable_across_repeated_calls(self):
        self.add_mapping(1, attempted_at=NOW - timedelta(days=1))
        self.add_mapping(2, attempted_at=None)
        self.add_mapping(3, attempted_at=NOW - timedelta(days=3))
        self.assertEqual(self.selected_ids(), self.selected_ids())

    def test_a_previous_result_never_affects_order(self):
        """Priority comes only from WHEN a mapping was attempted, never from
        whether that attempt produced a price. A card nobody is selling must
        keep being checked, or the collector stops noticing new listings."""
        self.add_mapping(1, attempted_at=NOW - timedelta(days=10))
        self.add_mapping(2, attempted_at=NOW - timedelta(days=1))
        # No observation/price state exists in this schema at all - the only
        # input to the order is the attempt timestamp.
        self.assertEqual(self.selected_ids(), [1, 2])


class LimitTests(FairSchedulingTestCase):
    def test_limit_is_enforced(self):
        for mid in range(1, 11):
            self.add_mapping(mid, attempted_at=None)
        self.assertEqual(self.selected_ids(limit=4), [1, 2, 3, 4])

    def test_limit_takes_the_stalest_slice(self):
        self.add_mapping(1, attempted_at=NOW - timedelta(days=1))
        self.add_mapping(2, attempted_at=NOW - timedelta(days=9))
        self.add_mapping(3, attempted_at=None)
        self.assertEqual(self.selected_ids(limit=2), [3, 2])


class EligibilityUnchangedTests(FairSchedulingTestCase):
    """The fair order must not have quietly widened WHAT is eligible."""

    def test_unapproved_inactive_and_unverified_are_still_excluded(self):
        self.add_mapping(1, attempted_at=None)
        self.add_mapping(2, attempted_at=None, review_status="rejected")
        self.add_mapping(3, attempted_at=None, manual_verified=False)
        self.add_mapping(4, attempted_at=None, is_active=False)
        self.add_mapping(5, attempted_at=None, print_active=False)
        self.add_mapping(6, attempted_at=None, print_status="unverified")
        self.assertEqual(self.selected_ids(), [1])

    def test_mapping_ids_still_narrows_and_never_force_includes(self):
        self.add_mapping(1, attempted_at=None)
        self.add_mapping(2, attempted_at=None, review_status="rejected")
        self.assertEqual(self.selected_ids(mapping_ids=[1, 2]), [1])

    def test_require_approved_false_still_relaxes_only_review_state(self):
        self.add_mapping(1, attempted_at=None, review_status="pending", manual_verified=False)
        self.add_mapping(2, attempted_at=None, is_active=False)
        got = self.selected_ids(mapping_ids=[1, 2], require_approved=False)
        self.assertEqual(got, [1])


class RunBatchLimitDefaultTests(FairSchedulingTestCase):
    """The default bound must apply to the nightly run and ONLY to it."""

    def _run(self, **kwargs):
        seen: list[int] = []

        def runner(session, mapping_id, validate_only, batch_run_id):
            seen.append(mapping_id)
            from snkrdunk_collector.collect import MappingOutcome

            return MappingOutcome(
                mapping_id=mapping_id,
                stage="validated_only" if validate_only else "written",
                written=not validate_only,
                would_write=True,
                identity_verified=True,
            )

        run_batch(
            session_factory=lambda: self.Session(),
            mapping_runner=runner,
            **kwargs,
        )
        return seen

    def test_unscoped_run_is_bounded_by_the_setting(self):
        for mid in range(1, 13):
            self.add_mapping(mid, attempted_at=None)
        original = settings.BATCH_MAX_MAPPINGS_PER_RUN
        settings.BATCH_MAX_MAPPINGS_PER_RUN = 5
        try:
            self.assertEqual(self._run(), [1, 2, 3, 4, 5])
        finally:
            settings.BATCH_MAX_MAPPINGS_PER_RUN = original

    def test_explicit_mapping_ids_are_never_silently_truncated(self):
        for mid in range(1, 13):
            self.add_mapping(mid, attempted_at=None)
        original = settings.BATCH_MAX_MAPPINGS_PER_RUN
        settings.BATCH_MAX_MAPPINGS_PER_RUN = 2
        try:
            got = self._run(mapping_ids=list(range(1, 13)))
            self.assertEqual(len(got), 12)
        finally:
            settings.BATCH_MAX_MAPPINGS_PER_RUN = original

    def test_explicit_limit_wins_over_the_default(self):
        for mid in range(1, 13):
            self.add_mapping(mid, attempted_at=None)
        original = settings.BATCH_MAX_MAPPINGS_PER_RUN
        settings.BATCH_MAX_MAPPINGS_PER_RUN = 2
        try:
            self.assertEqual(len(self._run(limit=9)), 9)
        finally:
            settings.BATCH_MAX_MAPPINGS_PER_RUN = original

    def test_a_real_run_stamps_every_attempt_and_validate_only_stamps_none(self):
        for mid in (1, 2, 3):
            self.add_mapping(mid, attempted_at=None)
        self._run(limit=3)
        self.db.expire_all()
        stamped = [self.db.get(SourceCardMapping, m).last_collection_attempted_at for m in (1, 2, 3)]
        self.assertTrue(all(s is not None for s in stamped), stamped)

        for mid in (4, 5):
            self.add_mapping(mid, attempted_at=None)
        self._run(mapping_ids=[4, 5], validate_only=True)
        self.db.expire_all()
        untouched = [self.db.get(SourceCardMapping, m).last_collection_attempted_at for m in (4, 5)]
        self.assertEqual(untouched, [None, None])


class NoStarvationTests(FairSchedulingTestCase):
    """The property the whole change exists to produce."""

    def _one_run(self, batch_size: int) -> list[int]:
        picked = select_eligible_mappings(self.db, limit=batch_size)
        ids = [m.id for m in picked]
        # Stamp exactly as a real run does, monotonically increasing so runs
        # are distinguishable.
        for offset, m in enumerate(picked):
            m.last_collection_attempted_at = datetime.now(timezone.utc) + timedelta(
                microseconds=offset
            )
        self.db.commit()
        return ids

    def test_every_mapping_is_reached_within_ceil_n_over_batch_runs(self):
        population = 202
        batch = 70
        for mid in range(1, population + 1):
            self.add_mapping(mid, attempted_at=None)

        reached: set[int] = set()
        runs = 0
        while len(reached) < population:
            runs += 1
            self.assertLessEqual(runs, 10, "coverage should not take this many runs")
            reached.update(self._one_run(batch))

        self.assertEqual(len(reached), population)
        self.assertEqual(runs, -(-population // batch))  # ceil division: 3

    def test_the_tail_is_not_starved_by_repeated_runs(self):
        """Under the OLD id-ordering the same first N ran every time. Here the
        mappings a run does not reach are exactly the ones the next run takes
        first."""
        for mid in range(1, 11):
            self.add_mapping(mid, attempted_at=None)
        first = self._one_run(4)
        second = self._one_run(4)
        third = self._one_run(4)
        self.assertEqual(first, [1, 2, 3, 4])
        self.assertEqual(second, [5, 6, 7, 8])
        # Run three wraps to the two never-reached rows, then the stalest.
        self.assertEqual(second[:0] + third[:2], [9, 10])
        self.assertEqual(set(first) | set(second) | set(third[:2]), set(range(1, 11)))

    def test_a_permanently_refusing_mapping_does_not_monopolise(self):
        """A mapping that never writes still gets stamped, so it takes its
        turn and then yields - it can never be retried ahead of everything
        else forever."""
        for mid in (1, 2, 3, 4):
            self.add_mapping(mid, attempted_at=None)
        self.assertEqual(self._one_run(2), [1, 2])
        self.assertEqual(self._one_run(2), [3, 4])
        self.assertEqual(self._one_run(2), [1, 2])


if __name__ == "__main__":
    unittest.main()


class InterruptedRunTests(FairSchedulingTestCase):
    """A run that stops early must leave the mappings it never reached at the
    FRONT of the next run's queue. This is what makes a bounded run safe: an
    interruption costs nothing, because unstamped means highest priority."""

    def _run(self, *, outcomes, **kwargs):
        from snkrdunk_collector.collect import MappingOutcome

        def runner(session, mapping_id, validate_only, batch_run_id):
            spec = outcomes.get(mapping_id, "written")
            if spec == "boom":
                raise RuntimeError("collector died mid-batch")
            if spec == "denied":
                return MappingOutcome(
                    mapping_id=mapping_id,
                    stage="no_extraction_attempted",
                    source_denied=True,
                    classification="static_403",
                )
            if spec == "floor":
                return MappingOutcome(
                    mapping_id=mapping_id,
                    stage="floor_unavailable",
                    written=False,
                    floor_unavailable=True,
                    identity_verified=True,
                    reasons=["no_raw_condition_price_available"],
                )
            if spec == "failed":
                return MappingOutcome(
                    mapping_id=mapping_id,
                    stage="validation_failed",
                    written=False,
                    identity_verified=False,
                    reasons=["artwork_not_confirmed_match:no_match"],
                )
            return MappingOutcome(mapping_id=mapping_id, stage="written", written=True)

        return run_batch(session_factory=lambda: self.Session(), mapping_runner=runner, **kwargs)

    def _stamps(self, ids):
        self.db.expire_all()
        return {i: self.db.get(SourceCardMapping, i).last_collection_attempted_at for i in ids}

    def test_a_crash_leaves_later_mappings_unstamped_and_highest_priority(self):
        for mid in range(1, 6):
            self.add_mapping(mid, attempted_at=None)
        with self.assertRaises(RuntimeError):
            self._run(outcomes={3: "boom"}, limit=5)
        stamps = self._stamps(range(1, 6))
        # 1 and 2 completed and were stamped; 3 died; 4 and 5 were never reached.
        self.assertIsNotNone(stamps[1])
        self.assertIsNotNone(stamps[2])
        self.assertIsNone(stamps[3])
        self.assertIsNone(stamps[4])
        self.assertIsNone(stamps[5])
        # The next run therefore starts exactly where this one stopped.
        self.assertEqual(self.selected_ids()[:3], [3, 4, 5])

    def test_source_denial_leaves_the_remainder_unstamped(self):
        for mid in range(1, 6):
            self.add_mapping(mid, attempted_at=None)
        self._run(outcomes={2: "denied"}, limit=5)
        stamps = self._stamps(range(1, 6))
        self.assertIsNotNone(stamps[1])
        # The denied mapping WAS attempted, so it is stamped and rotates.
        self.assertIsNotNone(stamps[2])
        # Everything after the stop was never attempted.
        self.assertEqual([stamps[3], stamps[4], stamps[5]], [None, None, None])
        self.assertEqual(self.selected_ids()[:3], [3, 4, 5])

    def test_failed_and_floor_unavailable_mappings_are_stamped_and_rotate(self):
        """A mapping that refuses, or verifies with nothing listed, must still
        take its turn - otherwise it would stay 'never attempted' and preempt
        every other mapping forever."""
        self.add_mapping(1, attempted_at=None)
        self.add_mapping(2, attempted_at=None)
        self.add_mapping(3, attempted_at=None)
        self._run(outcomes={1: "failed", 2: "floor", 3: "written"}, limit=3)
        stamps = self._stamps((1, 2, 3))
        self.assertTrue(all(v is not None for v in stamps.values()), stamps)
        # All three rotate to the back together; none is privileged by result.
        self.add_mapping(4, attempted_at=None)
        self.assertEqual(self.selected_ids()[0], 4)
