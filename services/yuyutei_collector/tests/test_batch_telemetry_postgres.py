"""The wired batch, against the production lifecycle CHECK.

test_batch_telemetry.py runs the same control flow on SQLite, which enforces
no CHECK constraints - so it can prove run_batch WROTE what was intended, but
not that staging would accept it. The row this matters most for is the skipped
one: started_at NULL together with a finished_at is exactly the combination an
earlier draft's constraint forbade, and a batch that produced it would have
had its telemetry silently swallowed in production while every SQLite test
stayed green.

So this file runs the real run_batch against real PostgreSQL with the
production lifecycle constraint in place. Skips when no server answers, and
never touches staging.
"""

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import telemetry
from yuyutei_collector.batch import run_batch
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    PriceObservation,
    CardPrint,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

from test_batch import FakeMappingRunner, written_outcome
from test_batch_telemetry import denied_outcome, validation_failed_outcome

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DB_NAME = "atlas_batch_telemetry_test"

MAPPING_COUNT = 5

# The CHECK constraints the migration installs. Declared here because the
# collector's mirror model carries no CHECKs (the migration is their single
# authority), and without them this file would prove nothing SQLite had not
# already proved. NOT NULL columns and the UNIQUE constraints come from the
# mirror model itself via create_all - and are asserted below rather than
# assumed, because this tuple drifting out of step with the migration is
# exactly the defect that reached a commit once already.
LIFECYCLE_CONSTRAINTS = (
    "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
    " ck_source_collection_attempts_finished_iff_terminal"
    " CHECK ((status = 'selected') = (finished_at IS NULL))",
    "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
    " ck_source_collection_attempts_finished_after_started"
    " CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)",
    "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
    " ck_source_collection_attempts_selection_ordinal_positive"
    " CHECK (selection_ordinal > 0)",
    "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
    " ck_source_collection_attempts_status"
    " CHECK (status IN ('selected','written','validation_failed',"
    "'no_extraction_attempted','operational_error','mapping_load_failed','skipped'))",
    "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
    " ck_source_collection_attempts_failure_stage"
    " CHECK (failure_stage IS NULL OR failure_stage IN ('load','browser_launch',"
    "'homepage','product','extraction','validation','write'))",
)


@pytest.fixture()
def pg():
    url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")

    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in LIFECYCLE_CONSTRAINTS:
            conn.execute(text(statement))
    Session = sessionmaker(bind=engine, future=True)

    with Session() as session:
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
            for i in range(1, MAPPING_COUNT + 1)
        ]
        session.add_all(mappings)
        session.flush()
        # Real observations, so a 'written' attempt can reference one through
        # the live price_observation_id foreign key. A fabricated id would be
        # rejected by that FK - which is the constraint doing its job, but it
        # would test the fixture rather than the batch.
        observations = [
            PriceObservation(
                source_id=source.id,
                observed_at=datetime.now(timezone.utc),
                price_type="sell",
                price_jpy=80,
                card_print_id=card_print.id,
                source_card_mapping_id=mapping.id,
            )
            for mapping in mappings
        ]
        session.add_all(observations)
        session.commit()
        subject = {
            "source_id": source.id,
            "mapping_ids": [m.id for m in mappings],
            "observation_ids": {
                o.source_card_mapping_id: o.id for o in observations
            },
        }

    with patch.object(telemetry, "SessionLocal", Session), patch(
        "yuyutei_collector.batch._mapping_delay_s", return_value=0.0
    ):
        yield Session, subject

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin.dispose()


def _written(subject, mapping_id):
    """written_outcome with its observation_id replaced by the id that really
    exists, so the production FK is exercised rather than tripped."""
    outcome = written_outcome(mapping_id)
    outcome.observation_id = subject["observation_ids"][mapping_id]
    return outcome


def _attempts(Session):
    with Session() as session:
        return session.execute(
            select(SourceCollectionAttempt).order_by(
                SourceCollectionAttempt.selection_ordinal
            )
        ).scalars().all()


def _run(Session, outcomes):
    runner = FakeMappingRunner(outcomes)
    result = run_batch(session_factory=Session, mapping_runner=runner)
    return result, runner


def test_a_clean_batch_is_accepted_by_the_production_constraints(pg):
    Session, subject = pg
    outcomes = {mid: _written(subject, mid) for mid in subject["mapping_ids"]}
    _run(Session, outcomes)

    rows = _attempts(Session)
    assert len(rows) == MAPPING_COUNT
    assert [r.selection_ordinal for r in rows] == list(range(1, MAPPING_COUNT + 1))
    assert all(r.status == "written" for r in rows)
    assert all(r.started_at is not None and r.finished_at is not None for r in rows)


def test_a_source_denial_writes_skipped_rows_the_real_schema_accepts(pg):
    """The row the earlier constraint would have rejected: terminal, finished,
    and never started. If run_batch fabricated a start to satisfy a CHECK, or
    if the CHECK still forbade this shape, this test is where it shows."""
    Session, subject = pg
    mapping_ids = subject["mapping_ids"]
    denied = mapping_ids[1]
    outcomes = {mid: _written(subject, mid) for mid in mapping_ids}
    outcomes[denied] = denied_outcome(denied)

    result, runner = _run(Session, outcomes)

    assert result.status == "source_wide_failure"
    assert result.stopped_reason == "source_denied:static_403"
    assert [c[0] for c in runner.calls] == mapping_ids[:2]

    rows = {r.source_card_mapping_id: r for r in _attempts(Session)}
    assert len(rows) == MAPPING_COUNT

    # The denied mapping keeps its own terminal outcome, and it really started.
    assert rows[denied].status == "no_extraction_attempted"
    assert rows[denied].failure_stage == "homepage"
    assert rows[denied].source_denied is True
    assert rows[denied].started_at is not None

    # Everything behind it: terminal, finished, never started.
    for mid in mapping_ids[2:]:
        assert rows[mid].status == "skipped"
        assert rows[mid].started_at is None
        assert rows[mid].finished_at is not None
        assert rows[mid].source_denied is True


def test_no_selected_row_survives_a_completed_batch(pg):
    Session, subject = pg
    mapping_ids = subject["mapping_ids"]
    outcomes = {mid: _written(subject, mid) for mid in mapping_ids}
    outcomes[mapping_ids[3]] = validation_failed_outcome(mapping_ids[3])
    _run(Session, outcomes)

    rows = _attempts(Session)
    assert [r for r in rows if r.status == "selected"] == []
    assert all(r.finished_at is not None for r in rows)


def test_the_unique_constraints_hold_across_a_real_run(pg):
    Session, subject = pg
    outcomes = {mid: _written(subject, mid) for mid in subject["mapping_ids"]}
    result, _ = _run(Session, outcomes)

    with Session() as session:
        pairs = session.execute(
            text(
                "SELECT count(*), count(DISTINCT source_card_mapping_id),"
                " count(DISTINCT selection_ordinal)"
                " FROM source_collection_attempts WHERE batch_run_id = :b"
            ),
            {"b": result.batch_run_id},
        ).one()
    assert pairs[0] == MAPPING_COUNT
    assert pairs[1] == MAPPING_COUNT
    assert pairs[2] == MAPPING_COUNT


def test_a_broken_recorder_still_lets_the_batch_finish_under_real_constraints(pg):
    Session, subject = pg
    outcomes = {mid: _written(subject, mid) for mid in subject["mapping_ids"]}

    def broken():
        raise RuntimeError("telemetry database is gone")

    with patch.object(telemetry, "SessionLocal", broken):
        result, runner = _run(Session, outcomes)

    assert result.status == "success"
    assert len(runner.calls) == MAPPING_COUNT
    assert _attempts(Session) == []


def test_the_fixture_agrees_with_the_final_migration_contract(pg):
    """Guards the guard.

    This file's whole value is that its table matches production. When the
    ordinal was tightened to NOT NULL the tuple above kept the old
    "IS NULL OR > 0" form for a while: harmless in effect, because the mirror
    model already made the column NOT NULL, but it meant a file claiming to
    mirror the migration quietly did not. Asserting the shape from the live
    catalogue makes that drift impossible to miss again.
    """
    Session, _ = pg
    with Session() as session:
        nullable = session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns"
                " WHERE table_name = 'source_collection_attempts'"
                "   AND column_name = 'selection_ordinal'"
            )
        ).scalar_one()

        ordinal_check = session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_source_collection_attempts_selection_ordinal_positive'"
            )
        ).scalar_one()

        uniques = session.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conrelid = 'source_collection_attempts'::regclass AND contype = 'u'"
            )
        ).all()

    assert nullable == "NO"                       # selection_ordinal NOT NULL
    assert "selection_ordinal > 0" in ordinal_check
    assert "IS NULL" not in ordinal_check         # the stale form is gone

    unique_defs = {name: definition for name, definition in uniques}
    assert any(
        "batch_run_id" in d and "selection_ordinal" in d for d in unique_defs.values()
    ), f"batch+ordinal uniqueness missing: {unique_defs}"
    assert any(
        "batch_run_id" in d and "source_card_mapping_id" in d for d in unique_defs.values()
    ), f"batch+mapping uniqueness missing: {unique_defs}"
