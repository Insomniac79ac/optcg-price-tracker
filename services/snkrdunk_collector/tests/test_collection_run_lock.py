"""Single-run locking for write-capable SNKRDUNK collection.

These tests need a REAL PostgreSQL backend, because the whole mechanism is a
Postgres advisory lock: on sqlite there is no lock to take and the collector
deliberately proceeds unlocked (see run_lock). They skip cleanly when no test
database is configured, exactly like the other Postgres-only suites here.

Point them at a throwaway database:
    SNKRDUNK_TEST_PG_URL=postgresql+psycopg://opcg:opcg@localhost:5545/lock_test
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from snkrdunk_collector.batch import run_batch
from snkrdunk_collector.collect import MappingOutcome
from snkrdunk_collector.models import CardPrint, Source, SourceCardMapping
from snkrdunk_collector.run_lock import (
    COLLECTION_LOCK_KEY,
    LOCK_PID_INFO_KEY,
    LockLost,
    assert_lock_owned,
    collection_lock,
    pinned_session,
)

PG_URL = os.environ.get("SNKRDUNK_TEST_PG_URL")


@unittest.skipUnless(PG_URL, "SNKRDUNK_TEST_PG_URL not set; advisory locks need real Postgres")
class CollectionLockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(PG_URL, future=True)
        # Minimal explicit schema rather than metadata.create_all: the
        # collector's models are a deliberately partial READ-ONLY mirror of
        # the API's tables and were never meant to emit DDL (they omit the
        # constraints the real foreign keys point at). These tests only need
        # the five tables the lock's guarantees are observed through.
        self._create_schema()
        self.Session = sessionmaker(bind=self.engine, autoflush=False, future=True)
        db = self.Session()
        db.add(Source(id=1, name="snkrdunk", base_url="https://snkrdunk.com"))
        db.commit()
        for mid in (1, 2, 3):
            db.add(CardPrint(id=1000 + mid, canonical_card_id=1, language="jp",
                             is_active=True, verification_status="verified"))
            db.add(SourceCardMapping(
                id=mid, card_id=None, source_id=1, card_print_id=1000 + mid,
                source_card_id=str(mid),
                source_url=f"https://snkrdunk.com/apparels/{mid}",
                is_active=True, review_status="approved", manual_verified=True,
                last_collection_attempted_at=None,
            ))
        db.commit()
        db.close()
        self.calls: list[int] = []

    def _create_schema(self) -> None:
        """Build the schema from the mirror's own metadata, so it cannot drift
        from the models these tests exercise.

        price_observations is the one exception: it carries a COMPOSITE
        foreign key onto source_card_mappings(source_id, card_id,
        card_print_id) - the paired-lineage constraint - and the read-only
        mirror does not declare the unique index that key points at, so
        Postgres refuses to create it. These tests only ever count rows in
        that table, so it is created without the constraint rather than
        teaching the mirror to emit DDL it was never meant to emit.
        """
        from snkrdunk_collector.models import Base

        tables = [t for t in Base.metadata.sorted_tables if t.name != "price_observations"]
        c = self.engine.connect()
        try:
            c.exec_driver_sql(
                "DROP TABLE IF EXISTS price_observations, raw_snapshots, "
                "source_card_mappings, card_prints, canonical_cards, cards, "
                "release_product_aliases, release_products, sources CASCADE"
            )
            c.commit()
        finally:
            c.close()
        Base.metadata.create_all(self.engine, tables=tables)
        c = self.engine.connect()
        try:
            c.exec_driver_sql(
                """
                CREATE TABLE price_observations (
                    id SERIAL PRIMARY KEY, card_id INTEGER,
                    source_id INTEGER NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    price_type VARCHAR(32) NOT NULL, price_jpy INTEGER,
                    condition_label VARCHAR(64), stock_status VARCHAR(32),
                    listing_count INTEGER, raw_snapshot_id INTEGER,
                    candidate_id INTEGER, source_card_mapping_id INTEGER,
                    card_print_id INTEGER)
                """
            )
            c.commit()
        finally:
            c.close()

    def tearDown(self) -> None:
        self.engine.dispose()

    def runner(self, session, mapping_id, validate_only, batch_run_id):
        self.calls.append(mapping_id)
        return MappingOutcome(
            mapping_id=mapping_id,
            stage="validated_only" if validate_only else "written",
            written=not validate_only,
            would_write=True,
            identity_verified=True,
        )

    def _state(self):
        db = self.Session()
        try:
            stamped = db.execute(text(
                "SELECT count(*) FROM source_card_mappings "
                "WHERE last_collection_attempted_at IS NOT NULL")).scalar_one()
            snapshots = db.execute(text("SELECT count(*) FROM raw_snapshots")).scalar_one()
            observations = db.execute(text("SELECT count(*) FROM price_observations")).scalar_one()
            return stamped, snapshots, observations
        finally:
            db.close()

    def _advisory_held(self) -> int:
        c = self.engine.connect()
        try:
            return c.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=:k"),
                {"k": COLLECTION_LOCK_KEY & 0xFFFFFFFF}).scalar_one()
        finally:
            c.close()

    # --- acquisition -------------------------------------------------------

    def test_a_real_run_acquires_the_lock(self):
        holder = create_engine(PG_URL, future=True)
        with collection_lock(holder, enabled=True) as lock:
            self.assertTrue(lock.acquired)
            self.assertFalse(lock.unsupported)
        holder.dispose()

    def test_a_concurrent_real_run_is_refused_and_does_nothing(self):
        """The core guarantee: while one run holds the lock, a second
        write-capable run selects nothing, stamps nothing and writes nothing."""
        holder = create_engine(PG_URL, future=True)
        with collection_lock(holder, enabled=True) as held:
            self.assertTrue(held.acquired)
            result = run_batch(
                session_factory=lambda: self.Session(),
                mapping_runner=self.runner,
                lock_engine=self.engine,
            )
            self.assertEqual(result.status, "skipped_locked")
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.mappings_selected, [])
            self.assertEqual(result.results, [])
            self.assertIsNotNone(result.stopped_reason)
        holder.dispose()
        # Nothing was fetched...
        self.assertEqual(self.calls, [])
        # ...and nothing was persisted.
        stamped, snapshots, observations = self._state()
        self.assertEqual((stamped, snapshots, observations), (0, 0, 0))

    def test_the_first_run_proceeds_normally_when_uncontended(self):
        result = run_batch(
            session_factory=lambda: self.Session(),
            mapping_runner=self.runner,
            lock_engine=self.engine,
        )
        self.assertNotEqual(result.status, "skipped_locked")
        self.assertEqual(self.calls, [1, 2, 3])
        stamped, _, _ = self._state()
        self.assertEqual(stamped, 3)

    # --- release -----------------------------------------------------------

    def test_lock_is_released_after_a_successful_run(self):
        run_batch(session_factory=lambda: self.Session(),
                  mapping_runner=self.runner, lock_engine=self.engine)
        self.assertEqual(self._advisory_held(), 0)

    def test_lock_is_released_after_an_exception(self):
        def boom(session, mapping_id, validate_only, batch_run_id):
            raise RuntimeError("collector died")

        with self.assertRaises(RuntimeError):
            run_batch(session_factory=lambda: self.Session(),
                      mapping_runner=boom, lock_engine=self.engine)
        self.assertEqual(self._advisory_held(), 0)

    def test_lock_is_released_when_the_owning_connection_dies(self):
        """No TTL, no reaper: Postgres releases a session-scoped advisory lock
        when the connection ends, however it ends."""
        holder = create_engine(PG_URL, future=True)
        conn = holder.connect()
        acquired = conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": COLLECTION_LOCK_KEY}).scalar_one()
        self.assertTrue(acquired)
        # Kill the connection without ever unlocking.
        conn.close()
        holder.dispose()
        self.assertEqual(self._advisory_held(), 0)

    def test_a_later_run_can_acquire_after_release(self):
        run_batch(session_factory=lambda: self.Session(),
                  mapping_runner=self.runner, lock_engine=self.engine)
        self.calls.clear()
        result = run_batch(session_factory=lambda: self.Session(),
                           mapping_runner=self.runner, lock_engine=self.engine)
        self.assertNotEqual(result.status, "skipped_locked")
        self.assertEqual(self.calls, [1, 2, 3])

    # --- scope -------------------------------------------------------------

    def test_validate_only_is_not_blocked_by_a_held_lock(self):
        """A validate-only run persists nothing, so it must stay inspectable
        while a real run is in progress."""
        holder = create_engine(PG_URL, future=True)
        with collection_lock(holder, enabled=True) as held:
            self.assertTrue(held.acquired)
            result = run_batch(
                session_factory=lambda: self.Session(),
                mapping_runner=self.runner,
                validate_only=True,
                lock_engine=self.engine,
            )
        holder.dispose()
        self.assertNotEqual(result.status, "skipped_locked")
        self.assertEqual(self.calls, [1, 2, 3])
        # ...and it still stamped nothing.
        stamped, snapshots, observations = self._state()
        self.assertEqual((stamped, snapshots, observations), (0, 0, 0))

    def test_an_explicit_mapping_id_real_run_obeys_the_same_lock(self):
        holder = create_engine(PG_URL, future=True)
        with collection_lock(holder, enabled=True):
            result = run_batch(
                session_factory=lambda: self.Session(),
                mapping_runner=self.runner,
                mapping_ids=[1, 2, 3],
                lock_engine=self.engine,
            )
        holder.dispose()
        self.assertEqual(result.status, "skipped_locked")
        self.assertEqual(self.calls, [])
        self.assertEqual(self._state(), (0, 0, 0))

    def test_fair_ordering_and_stamping_survive_the_lock(self):
        """The lock must not have disturbed what the run actually does."""
        db = self.Session()
        db.execute(text("UPDATE source_card_mappings SET last_collection_attempted_at=:t WHERE id=1"),
                   {"t": datetime(2026, 1, 1, tzinfo=timezone.utc)})
        db.commit()
        db.close()
        run_batch(session_factory=lambda: self.Session(),
                  mapping_runner=self.runner, lock_engine=self.engine)
        # 2 and 3 are never-attempted so they come first; 1 is stalest-but-attempted.
        self.assertEqual(self.calls, [2, 3, 1])


@unittest.skipUnless(PG_URL, "SNKRDUNK_TEST_PG_URL not set; advisory locks need real Postgres")
class LockOwnershipHardeningTestCase(CollectionLockTestCase):
    """Fail-closed ownership: losing the lock connection must stop the run,
    not let it reconnect to a lockless backend and keep writing."""

    # --- pinning ----------------------------------------------------------

    def test_the_work_session_is_pinned_to_the_lock_owning_backend(self):
        with collection_lock(self.engine, enabled=True) as lock:
            self.assertTrue(lock.acquired)
            session = pinned_session(lock, lambda: self.Session())
            try:
                # The Session writes through the very backend holding the lock.
                self.assertEqual(
                    session.execute(text("SELECT pg_backend_pid()")).scalar_one(),
                    lock.backend_pid,
                )
                self.assertEqual(session.info[LOCK_PID_INFO_KEY], lock.backend_pid)
            finally:
                session.close()

    def test_lock_survives_every_per_mapping_commit(self):
        """Commit-per-mapping is preserved AND does not release the lock."""
        pids = []
        holder = create_engine(PG_URL, future=True)

        def runner(session, mapping_id, validate_only, batch_run_id):
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            # A competing run must still be refused mid-batch, after commits.
            with holder.connect() as rival:
                self.assertFalse(
                    rival.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                  {"k": COLLECTION_LOCK_KEY}).scalar_one(),
                    "the lock was released by a per-mapping commit")
            return self.runner(session, mapping_id, validate_only, batch_run_id)

        result = run_batch(session_factory=lambda: self.Session(),
                           mapping_runner=runner, lock_engine=self.engine)
        holder.dispose()
        self.assertEqual(result.status, "success")
        self.assertEqual(len(set(pids)), 1, "run drifted across backends")
        stamped, _, _ = self._state()
        self.assertEqual(stamped, 3)

    # --- detection --------------------------------------------------------

    def test_a_reconnected_backend_without_the_lock_is_detected(self):
        """The precise fail-open hazard: a rollback lets SQLAlchemy procure a
        NEW backend that holds nothing. Verification must catch it."""
        with collection_lock(self.engine, enabled=True) as lock:
            session = pinned_session(lock, lambda: self.Session())
            try:
                assert_lock_owned(session)  # healthy
                lock.connection.invalidate()
                with self.assertRaises(Exception):
                    session.execute(text("SELECT 1"))
                session.rollback()  # the gesture that silently reconnects
                new_pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
                self.assertNotEqual(new_pid, lock.backend_pid)
                with self.assertRaises(LockLost) as ctx:
                    assert_lock_owned(session)
                self.assertIn("backend changed", str(ctx.exception))
            finally:
                session.close()

    def test_a_dead_connection_is_lock_lost_not_a_shrug(self):
        with collection_lock(self.engine, enabled=True) as lock:
            session = pinned_session(lock, lambda: self.Session())
            try:
                lock.connection.invalidate()
                with self.assertRaises(LockLost):
                    assert_lock_owned(session)
            finally:
                session.close()

    def test_same_backend_that_unlocked_is_still_lock_lost(self):
        """Same pid, but the lock is gone - the second half of the check."""
        with collection_lock(self.engine, enabled=True) as lock:
            session = pinned_session(lock, lambda: self.Session())
            try:
                session.execute(text("SELECT pg_advisory_unlock(:k)"),
                                {"k": COLLECTION_LOCK_KEY})
                session.commit()
                self.assertEqual(
                    session.execute(text("SELECT pg_backend_pid()")).scalar_one(),
                    lock.backend_pid, "pid must be unchanged for this to be meaningful")
                with self.assertRaises(LockLost) as ctx:
                    assert_lock_owned(session)
                self.assertIn("no longer holds", str(ctx.exception))
            finally:
                session.close()

    # --- run-level failure behaviour --------------------------------------

    def test_loss_during_a_mapping_prevents_even_that_mapping_being_stamped(self):
        """Ownership went away while mapping 1 was in hand, so mapping 1 is
        NOT stamped either - the stamp boundary verifies before it writes."""
        def runner(session, mapping_id, validate_only, batch_run_id):
            outcome = self.runner(session, mapping_id, validate_only, batch_run_id)
            if len(self.calls) == 1:
                # Drop the lock the way a dead connection would.
                session.execute(text("SELECT pg_advisory_unlock(:k)"),
                                {"k": COLLECTION_LOCK_KEY})
                session.commit()
            return outcome

        result = run_batch(session_factory=lambda: self.Session(),
                           mapping_runner=runner, lock_engine=self.engine)
        self.assertEqual(result.status, "lock_lost")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.stopped_reason, "collection_lock_lost")
        # Only the first mapping ran; the run did not continue.
        self.assertEqual(self.calls, [1])
        stamped, _, _ = self._state()
        self.assertEqual(stamped, 0,
                         "the mapping in hand when the lock was lost must not be stamped")

    def test_backend_killed_between_mappings_stops_before_the_next_one(self):
        """The loop-top boundary. Mapping 1 completes and IS stamped; the
        owning backend is then terminated from another connection - real
        connection loss, not a simulated unlock - and mapping 2 is never
        fetched or stamped."""
        import snkrdunk_collector.batch as batch_mod

        killer = create_engine(PG_URL, future=True)
        pids: list[int] = []

        def runner(session, mapping_id, validate_only, batch_run_id):
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return self.runner(session, mapping_id, validate_only, batch_run_id)

        def kill_between_mappings():
            # Called between mappings, after mapping 1's stamp committed.
            with killer.connect() as c:
                c.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pids[0]})
                c.commit()
            return 0.0

        original = batch_mod._mapping_delay_s
        batch_mod._mapping_delay_s = kill_between_mappings
        try:
            result = run_batch(session_factory=lambda: self.Session(),
                               mapping_runner=runner, lock_engine=self.engine)
        finally:
            batch_mod._mapping_delay_s = original
            killer.dispose()

        self.assertEqual(result.status, "lock_lost")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(self.calls, [1], "mapping 2 was fetched after the backend died")
        stamped, _, _ = self._state()
        self.assertEqual(stamped, 1, "only mapping 1, stamped before the connection died")
        # The dead backend took the lock with it; nothing is wedged.
        self.assertEqual(self._advisory_held(), 0)

    def test_lock_loss_before_the_first_stamp_stamps_nothing_at_all(self):
        """Loss after fetch but before mutation: zero stamps, zero rows."""
        def runner(session, mapping_id, validate_only, batch_run_id):
            self.calls.append(mapping_id)
            session.execute(text("SELECT pg_advisory_unlock(:k)"),
                            {"k": COLLECTION_LOCK_KEY})
            session.commit()
            return MappingOutcome(mapping_id=mapping_id, stage="written",
                                  written=True, would_write=True, identity_verified=True)

        result = run_batch(session_factory=lambda: self.Session(),
                           mapping_runner=runner, lock_engine=self.engine)
        self.assertEqual(result.status, "lock_lost")
        self.assertEqual(self.calls, [1])
        self.assertEqual(self._state(), (0, 0, 0),
                         "lock was lost before any mutation; nothing may persist")

    def test_writer_refuses_to_create_rows_without_the_lock(self):
        """The snapshot/observation boundary guards itself, independently of
        the batch loop - a fetch that already happened cannot write."""
        from snkrdunk_collector.writer import write_evidence_snapshot

        with collection_lock(self.engine, enabled=True) as lock:
            session = pinned_session(lock, lambda: self.Session())
            try:
                session.execute(text("SELECT pg_advisory_unlock(:k)"),
                                {"k": COLLECTION_LOCK_KEY})
                session.commit()
                with self.assertRaises(LockLost):
                    write_evidence_snapshot(
                        session=session, source_id=1,
                        source_url="https://snkrdunk.com/x", http_status=200,
                        raw_html="<html></html>", parser_version="t")
                session.rollback()
            finally:
                session.close()
        self.assertEqual(self._state(), (0, 0, 0))

    def test_the_lock_is_released_after_a_lock_lost_run(self):
        """A lost run must not leave the key wedged for the next invocation."""
        def runner(session, mapping_id, validate_only, batch_run_id):
            self.calls.append(mapping_id)
            session.execute(text("SELECT pg_advisory_unlock(:k)"),
                            {"k": COLLECTION_LOCK_KEY})
            session.commit()
            return MappingOutcome(mapping_id=mapping_id, stage="written", written=True)

        run_batch(session_factory=lambda: self.Session(),
                  mapping_runner=runner, lock_engine=self.engine)
        self.assertEqual(self._advisory_held(), 0)
        # ...and a later independent run acquires normally.
        self.calls.clear()
        result = run_batch(session_factory=lambda: self.Session(),
                           mapping_runner=self.runner, lock_engine=self.engine)
        self.assertEqual(result.status, "success")
        self.assertEqual(self.calls, [1, 2, 3])

    def test_no_silent_reacquisition_within_the_same_run(self):
        """After loss the run stops; it must not retake the key and continue."""
        def runner(session, mapping_id, validate_only, batch_run_id):
            self.calls.append(mapping_id)
            session.execute(text("SELECT pg_advisory_unlock(:k)"),
                            {"k": COLLECTION_LOCK_KEY})
            session.commit()
            return MappingOutcome(mapping_id=mapping_id, stage="written", written=True)

        rival = create_engine(PG_URL, future=True)
        run_batch(session_factory=lambda: self.Session(),
                  mapping_runner=runner, lock_engine=self.engine)
        # The run gave the key up and never took it back, so a rival gets it.
        with rival.connect() as c:
            self.assertTrue(c.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                      {"k": COLLECTION_LOCK_KEY}).scalar_one())
        rival.dispose()
        self.assertEqual(self.calls, [1])

    # --- unchanged behaviour ----------------------------------------------

    def test_validate_only_sessions_are_unpinned_and_unguarded(self):
        """Validate-only keeps its old lifecycle exactly: no pin, no marker,
        so assert_lock_owned cannot fail it even while a real run holds."""
        holder = create_engine(PG_URL, future=True)
        with collection_lock(holder, enabled=True):
            session = self.Session()
            try:
                self.assertNotIn(LOCK_PID_INFO_KEY, session.info)
                assert_lock_owned(session)  # no-op, must not raise
            finally:
                session.close()
            result = run_batch(session_factory=lambda: self.Session(),
                               mapping_runner=self.runner, validate_only=True,
                               lock_engine=self.engine)
        holder.dispose()
        self.assertNotEqual(result.status, "lock_lost")
        self.assertEqual(self.calls, [1, 2, 3])
        self.assertEqual(self._state(), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
