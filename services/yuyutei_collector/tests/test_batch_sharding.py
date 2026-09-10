"""Partition-invariant tests for deterministic Yuyu-Tei shard selection.

Runs against an in-memory SQLite database - no network, no Playwright, no
staging database. `select_eligible_mappings` runs for real; nothing here
fetches a page or writes an observation.

WHAT THESE TESTS ARE FOR. The collector's shards are what will let one
catalogue sweep be split across several scheduled runs, and the only thing
making that safe is that the shards PARTITION the eligible set: every
eligible mapping in exactly one shard, none in two. Nothing in the database
enforces that - `price_observations` has no per-print-per-day uniqueness
constraint - so if the partition ever broke, two shards would each write an
observation for the same print on the same day and nothing would complain.
These tests are therefore the enforcement mechanism, not a formality.
"""

import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from yuyutei_collector.batch import (
    _membership_digest,
    run_batch,
    select_eligible_mappings,
    validate_shard,
)
from yuyutei_collector.collect import MappingOutcome
from yuyutei_collector.collect import main as collect_main
from yuyutei_collector.db import Base
from yuyutei_collector.models import Card, CardPrint, Source, SourceCardMapping

N = 9


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True)


class ShardPartitionTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session = make_db()
        self.session = self.Session()

        self.yuyutei = Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp")
        self.other_source = Source(id=2, name="snkrdunk", base_url="https://snkrdunk.com")
        self.session.add_all([self.yuyutei, self.other_source])
        self.session.flush()

        self.card = Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro")
        self.session.add(self.card)
        self.session.flush()

        self.verified_active_print = CardPrint(
            id=1, canonical_card_id=1, treatment="normal", verification_status="verified", is_active=True
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

        # Deliberately NOT a contiguous id block: real mapping ids have gaps
        # (rejected candidates, other sources consuming the sequence), and a
        # shard key that only works on a dense range would be a trap.
        self.eligible_ids = list(range(11, 60)) + [77, 78, 91, 145, 200, 201, 202, 303, 545]
        for mid in self.eligible_ids:
            self._mapping(id=mid)

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

    def _shard_ids(self, k, n=N):
        return [m.id for m in select_eligible_mappings(self.session, shard_index=k, shard_count=n)]

    # --- the partition invariant ------------------------------------------

    def test_union_of_shards_is_the_full_eligible_set(self):
        union = []
        for k in range(N):
            union.extend(self._shard_ids(k))
        unsharded = [m.id for m in select_eligible_mappings(self.session)]
        self.assertEqual(sorted(union), sorted(unsharded))
        self.assertEqual(sorted(union), sorted(self.eligible_ids))

    def test_pairwise_intersection_is_empty(self):
        shards = {k: set(self._shard_ids(k)) for k in range(N)}
        for a in range(N):
            for b in range(a + 1, N):
                self.assertEqual(
                    shards[a] & shards[b],
                    set(),
                    f"shards {a} and {b} both claim {sorted(shards[a] & shards[b])}",
                )

    def test_each_mapping_appears_exactly_once(self):
        counts = {mid: 0 for mid in self.eligible_ids}
        for k in range(N):
            for mid in self._shard_ids(k):
                counts[mid] += 1
        self.assertEqual(
            [mid for mid, c in counts.items() if c != 1],
            [],
            "every eligible mapping must belong to exactly one shard",
        )

    def test_membership_is_the_documented_modulo_rule(self):
        for k in range(N):
            self.assertEqual(self._shard_ids(k), sorted(m for m in self.eligible_ids if m % N == k))

    # --- stability --------------------------------------------------------

    def test_adding_newer_mappings_never_moves_existing_ones(self):
        """The property the whole design rests on: approving more mappings
        may only ADD to a shard, never move an id out of the one it was in."""
        before = {k: self._shard_ids(k) for k in range(N)}

        for mid in range(600, 700):
            self._mapping(id=mid)

        after = {k: self._shard_ids(k) for k in range(N)}
        for k in range(N):
            # Every id that was in shard k is still in shard k, in the same
            # relative order, and nothing was taken away.
            self.assertEqual([mid for mid in after[k] if mid in set(before[k])], before[k])
            self.assertTrue(set(before[k]).issubset(set(after[k])))

        # And the enlarged shards still partition the enlarged population.
        union = [mid for k in range(N) for mid in after[k]]
        self.assertEqual(sorted(union), sorted(m.id for m in select_eligible_mappings(self.session)))
        self.assertEqual(len(union), len(set(union)))

    def test_same_shard_twice_is_identical_and_ordered(self):
        first = self._shard_ids(3)
        second = self._shard_ids(3)
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first), "shard membership must stay id-ascending")

    # --- eligibility is never widened -------------------------------------

    def test_ineligible_mappings_stay_excluded_in_every_shard(self):
        """A shard filters the eligible population; it can never reach past
        it. Each of these lands in a different residue class on purpose."""
        ineligible = {
            self._mapping(id=1000, is_active=False).id,
            self._mapping(id=1001, review_status="needs_review").id,
            self._mapping(id=1002, card_print_id=None).id,
            self._mapping(id=1003, card_print_id=self.unverified_print.id).id,
            self._mapping(id=1004, card_print_id=self.inactive_verified_print.id).id,
            self._mapping(id=1005, source_id=self.other_source.id).id,
            self._mapping(id=1006, review_status="rejected").id,
        }
        seen = {mid for k in range(N) for mid in self._shard_ids(k)}
        self.assertEqual(seen & ineligible, set())

    def test_shard_of_an_empty_population_is_empty_not_everything(self):
        """A fresh database with no eligible mappings: every shard is empty.
        Guards the fail-open shape where a shard filter that failed to apply
        would return the whole population instead of nothing."""
        _engine, Session = make_db()
        session = Session()
        try:
            session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
            session.flush()
            for k in range(N):
                self.assertEqual(
                    [m.id for m in select_eligible_mappings(session, shard_index=k, shard_count=N)],
                    [],
                )
        finally:
            session.close()

    # --- argument validation ----------------------------------------------

    def test_invalid_shard_combinations_are_rejected(self):
        for k, n in [(0, 1), (0, 0), (-1, 9), (9, 9), (10, 9), (0, -3)]:
            with self.subTest(shard_index=k, shard_count=n):
                with self.assertRaises(ValueError):
                    select_eligible_mappings(self.session, shard_index=k, shard_count=n)

    def test_shard_arguments_must_be_given_together(self):
        with self.assertRaises(ValueError):
            select_eligible_mappings(self.session, shard_index=0)
        with self.assertRaises(ValueError):
            select_eligible_mappings(self.session, shard_count=N)

    def test_validate_shard_reports_whether_a_shard_was_requested(self):
        self.assertFalse(validate_shard(None, None))
        self.assertTrue(validate_shard(0, 2))

    # --- unsharded behaviour is unchanged ---------------------------------

    def test_unsharded_selection_is_byte_for_byte_the_old_behaviour(self):
        selected = select_eligible_mappings(self.session)
        self.assertEqual([m.id for m in selected], sorted(self.eligible_ids))

    def test_limit_stays_a_prefix_cap_with_and_without_a_shard(self):
        """`limit` is applied last, to the id-ascending result - so with a
        shard it caps that shard's own prefix, not the global population."""
        self.assertEqual(
            [m.id for m in select_eligible_mappings(self.session, limit=5)],
            sorted(self.eligible_ids)[:5],
        )
        shard4 = self._shard_ids(4)
        self.assertEqual(
            [m.id for m in select_eligible_mappings(
                self.session, limit=3, shard_index=4, shard_count=N)],
            shard4[:3],
        )


class ShardCountSensitivityTests(unittest.TestCase):
    """N is a fixed deployment constant. This is the test that says why."""

    def setUp(self):
        self.engine, self.Session = make_db()
        self.session = self.Session()
        self.session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
        self.session.flush()
        self.session.add(Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro"))
        self.session.flush()
        self.session.add(
            CardPrint(id=1, canonical_card_id=1, treatment="normal",
                      verification_status="verified", is_active=True)
        )
        self.session.flush()
        for mid in range(11, 60):
            self.session.add(
                SourceCardMapping(
                    id=mid, card_id=1, source_id=1, card_print_id=1,
                    source_card_id="OP01-001",
                    source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
                    is_active=True, review_status="approved",
                )
            )
        self.session.flush()

    def tearDown(self):
        self.session.close()

    def test_changing_n_reassigns_membership(self):
        """Shard 0 of 9 and shard 0 of 8 are different sets. A sweep that
        spanned a change of N would double-collect some mappings and miss
        others - which is why N must never be retuned in place."""
        of_nine = {m.id for m in select_eligible_mappings(self.session, shard_index=0, shard_count=9)}
        of_eight = {m.id for m in select_eligible_mappings(self.session, shard_index=0, shard_count=8)}
        self.assertNotEqual(of_nine, of_eight)

    def test_every_n_still_partitions_for_that_n(self):
        for n in (2, 3, 5, 8, 9, 12):
            with self.subTest(shard_count=n):
                union = []
                for k in range(n):
                    union.extend(
                        m.id for m in select_eligible_mappings(
                            self.session, shard_index=k, shard_count=n)
                    )
                self.assertEqual(len(union), len(set(union)))
                self.assertEqual(
                    sorted(union), [m.id for m in select_eligible_mappings(self.session)]
                )


class ShardedRunBatchTests(unittest.TestCase):
    """run_batch end-to-end with a fake mapping runner - no network."""

    def setUp(self):
        # Same reason as tests/test_batch.py: these exercise selection and
        # orchestration, never the real inter-mapping delay's duration.
        self._sleep_patch = patch("yuyutei_collector.batch.time.sleep")
        self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

        self.engine, self.Session = make_db()
        session = self.Session()
        session.add(Source(id=1, name="yuyutei", base_url="https://yuyu-tei.jp"))
        session.flush()
        session.add(Card(id=1, card_code="OP01-001", name_en="Roronoa Zoro"))
        session.flush()
        session.add(
            CardPrint(id=1, canonical_card_id=1, treatment="normal",
                      verification_status="verified", is_active=True)
        )
        session.flush()
        self.ids = list(range(11, 47))
        for mid in self.ids:
            session.add(
                SourceCardMapping(
                    id=mid, card_id=1, source_id=1, card_print_id=1,
                    source_card_id="OP01-001",
                    source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
                    is_active=True, review_status="approved",
                )
            )
        session.commit()
        session.close()

    def _runner(self):
        calls = []

        def runner(session, mapping_id, validate_only=False, batch_run_id=None):
            calls.append(mapping_id)
            return MappingOutcome(mapping_id=mapping_id, stage="written", written=True)

        return runner, calls

    def test_sharded_run_attempts_only_that_shard(self):
        runner, calls = self._runner()
        with patch("yuyutei_collector.batch.telemetry"):
            result = run_batch(
                shard_index=2, shard_count=N,
                session_factory=self.Session, mapping_runner=runner,
            )
        expected = [mid for mid in self.ids if mid % N == 2]
        self.assertEqual(calls, expected)
        self.assertEqual(result.mappings_selected, expected)

    def test_nine_shards_cover_every_mapping_exactly_once(self):
        attempted = []
        for k in range(N):
            runner, calls = self._runner()
            with patch("yuyutei_collector.batch.telemetry"):
                run_batch(
                    shard_index=k, shard_count=N,
                    session_factory=self.Session, mapping_runner=runner,
                )
            attempted.extend(calls)
        self.assertEqual(sorted(attempted), self.ids)
        self.assertEqual(len(attempted), len(set(attempted)))

    def test_unsharded_run_calls_the_selector_exactly_as_before(self):
        """The regression guard for 'existing behaviour unchanged': with no
        shard arguments the selector is invoked with the same two keyword
        arguments it has always received, so a selector that knows nothing
        about sharding still works."""
        seen_kwargs = {}

        def recording_selector(session, **kwargs):
            seen_kwargs.update(kwargs)
            return select_eligible_mappings(session, **kwargs)

        runner, calls = self._runner()
        with patch("yuyutei_collector.batch.telemetry"):
            run_batch(
                session_factory=self.Session, mapping_runner=runner,
                mapping_selector=recording_selector,
            )
        self.assertEqual(set(seen_kwargs), {"limit", "mapping_ids"})
        self.assertEqual(calls, self.ids)

    def test_legacy_selector_signature_still_works_unsharded(self):
        """A selector with the pre-change signature (no shard kwargs at all)
        must still be callable by an unsharded run."""
        def legacy_selector(session, limit=None, mapping_ids=None):
            return select_eligible_mappings(session, limit=limit, mapping_ids=mapping_ids)

        runner, calls = self._runner()
        with patch("yuyutei_collector.batch.telemetry"):
            run_batch(
                session_factory=self.Session, mapping_runner=runner,
                mapping_selector=legacy_selector,
            )
        self.assertEqual(calls, self.ids)

    def test_invalid_shard_fails_before_any_mapping_is_attempted(self):
        runner, calls = self._runner()
        with self.assertRaises(ValueError):
            run_batch(
                shard_index=9, shard_count=N,
                session_factory=self.Session, mapping_runner=runner,
            )
        self.assertEqual(calls, [])

    def test_shard_scope_telemetry_is_emitted(self):
        runner, _ = self._runner()
        with patch("yuyutei_collector.batch.telemetry"), \
                patch("yuyutei_collector.batch.log_event") as log:
            run_batch(
                shard_index=2, shard_count=N,
                session_factory=self.Session, mapping_runner=runner,
            )
        scope = [c.kwargs for c in log.call_args_list if c.args and c.args[0] == "batch_shard_scope"]
        self.assertEqual(len(scope), 1)
        line = scope[0]
        expected = [mid for mid in self.ids if mid % N == 2]
        self.assertTrue(line["sharded"])
        self.assertEqual(line["shard_index"], 2)
        self.assertEqual(line["shard_count"], N)
        self.assertEqual(line["eligible_total"], len(self.ids))
        self.assertEqual(line["selected_count"], len(expected))
        self.assertEqual(line["first_mapping_id"], expected[0])
        self.assertEqual(line["last_mapping_id"], expected[-1])
        self.assertEqual(line["membership_digest"], _membership_digest(expected))

    def test_membership_digest_is_stable_and_discriminating(self):
        a = [mid for mid in self.ids if mid % N == 2]
        self.assertEqual(_membership_digest(a), _membership_digest(list(a)))
        self.assertNotEqual(_membership_digest(a), _membership_digest(a[:-1]))
        self.assertNotEqual(_membership_digest(a), _membership_digest(list(reversed(a))))


class ShardCliTests(unittest.TestCase):
    """argparse-level rules. These never touch a database or the network."""

    def _main(self, argv):
        with patch.object(sys, "argv", ["collect"] + argv):
            collect_main()

    def test_mapping_ids_and_shard_are_refused_together(self):
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--approved-mappings", "--mapping-ids", "1,2",
                        "--shard-index", "0", "--shard-count", "9"])
        self.assertEqual(ctx.exception.code, 2)

    def test_shard_index_without_count_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--approved-mappings", "--shard-index", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_shard_count_below_two_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--approved-mappings", "--shard-index", "0", "--shard-count", "1"])
        self.assertEqual(ctx.exception.code, 2)

    def test_shard_index_out_of_range_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--approved-mappings", "--shard-index", "9", "--shard-count", "9"])
        self.assertEqual(ctx.exception.code, 2)

    def test_shard_on_single_mapping_path_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            self._main(["--mapping-id", "5", "--shard-index", "0", "--shard-count", "9"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
