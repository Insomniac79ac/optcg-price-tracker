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
from snkrdunk_collector.run_lock import COLLECTION_LOCK_KEY, collection_lock

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


if __name__ == "__main__":
    unittest.main()
