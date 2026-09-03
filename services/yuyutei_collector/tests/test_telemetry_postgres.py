"""The half of the telemetry contract that needs a real engine.

"A rolled-back pricing transaction must still leave the row explaining why it
rolled back" requires two genuinely concurrent write transactions. In-memory
SQLite gives every session the same DBAPI connection, so a telemetry commit
there would also commit the caller's pending work - the test would pass while
proving the opposite of what it claims. A file-backed SQLite is no better:
it serialises writers, so the telemetry write would simply be locked out.

Postgres can hold both transactions at once, which is the situation the
collector is actually in, so the claim is tested here or not at all.

Skips when no server answers. Never touches staging.
"""

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import telemetry
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DB_NAME = "atlas_collector_telemetry_test"

RUN = "batch0001"


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
    # The collector's own minimal metadata, plus the one lifecycle CHECK the
    # production schema carries. The mirror model deliberately declares no
    # CHECKs (the migration is their single authority), which means these
    # tables would otherwise accept rows Postgres rejects in staging - so the
    # recorder's output would go untested against the rule that matters most.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE source_collection_attempts ADD CONSTRAINT"
                " ck_source_collection_attempts_finished_iff_terminal"
                " CHECK ((status = 'selected') = (finished_at IS NULL))"
            )
        )
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
        mapping = SourceCardMapping(
            source_id=source.id,
            source_card_id="OP13-050",
            source_url="https://yuyu-tei.jp/sell/opc/card/op13/10060",
            card_print_id=card_print.id,
            is_active=True,
            review_status="approved",
        )
        session.add(mapping)
        session.commit()
        subject = {
            "source_id": source.id,
            "print_id": card_print.id,
            "mapping_id": mapping.id,
        }

    with patch.object(telemetry, "SessionLocal", Session):
        yield engine, Session, subject

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin.dispose()


def test_telemetry_survives_a_rollback_of_the_caller(pg):
    """The reason the recorder opens its own session. A pricing transaction
    that rolls back must not take the record explaining it down as well - that
    record cannot live inside the transaction it describes."""
    _, Session, subject = pg

    caller = Session()
    caller.add(
        PriceObservation(
            source_id=subject["source_id"],
            observed_at=datetime.now(timezone.utc),
            price_type="sell",
            price_jpy=50,
            card_print_id=subject["print_id"],
            source_card_mapping_id=subject["mapping_id"],
        )
    )
    caller.flush()  # a real, open, uncommitted write transaction

    assert telemetry.record_selected_batch(RUN, subject["source_id"], [subject["mapping_id"]])
    assert telemetry.finish_attempt(
        RUN,
        subject["mapping_id"],
        "operational_error",
        failure_stage="write",
        failure_reason="caller rolled back",
    )

    caller.rollback()
    caller.close()

    with Session() as session:
        observations = session.execute(select(PriceObservation)).scalars().all()
        attempts = session.execute(select(SourceCollectionAttempt)).scalars().all()

    assert observations == []          # the caller's work is gone
    assert len(attempts) == 1          # its explanation is not
    assert attempts[0].status == "operational_error"
    assert attempts[0].failure_reason == "caller rolled back"


def test_a_telemetry_failure_cannot_roll_back_caller_data(pg):
    """The opposite direction, on the same engine: a telemetry write that
    fails leaves the caller's uncommitted work intact and committable."""
    _, Session, subject = pg

    caller = Session()
    caller.add(
        PriceObservation(
            source_id=subject["source_id"],
            observed_at=datetime.now(timezone.utc),
            price_type="sell",
            price_jpy=50,
            card_print_id=subject["print_id"],
            source_card_mapping_id=subject["mapping_id"],
        )
    )
    caller.flush()

    def broken():
        raise RuntimeError("database is gone")

    with patch.object(telemetry, "SessionLocal", broken):
        assert telemetry.record_selected_batch(
            RUN, subject["source_id"], [subject["mapping_id"]]
        ) is False

    caller.commit()
    caller.close()

    with Session() as session:
        observations = session.execute(select(PriceObservation)).scalars().all()
    assert len(observations) == 1
    assert observations[0].price_jpy == 50


def test_the_recorder_commits_independently_of_an_open_caller_transaction(pg):
    """A telemetry row is durable the moment it is written, without waiting
    for - or depending on - the caller's commit."""
    _, Session, subject = pg

    caller = Session()
    caller.add(
        PriceObservation(
            source_id=subject["source_id"],
            observed_at=datetime.now(timezone.utc),
            price_type="sell",
            price_jpy=50,
            card_print_id=subject["print_id"],
            source_card_mapping_id=subject["mapping_id"],
        )
    )
    caller.flush()

    telemetry.record_selected_batch(RUN, subject["source_id"], [subject["mapping_id"]])

    # A third, unrelated session sees the telemetry row while the caller's
    # observation is still invisible to it.
    with Session() as observer:
        assert observer.execute(select(SourceCollectionAttempt)).scalars().all() != []
        assert observer.execute(select(PriceObservation)).scalars().all() == []

    caller.rollback()
    caller.close()


def test_the_recorder_never_writes_a_row_the_real_constraint_rejects(pg):
    """The recorder's own output, against the production lifecycle rule.

    Each step below would raise (and be swallowed into a False) if it produced
    a 'selected' row carrying a finish time, or a terminal row without one.
    """
    _, Session, subject = pg
    mapping = subject["mapping_id"]

    # selected: no finish time
    assert telemetry.record_selected_batch(RUN, subject["source_id"], [mapping]) is True
    with Session() as s:
        row = s.execute(select(SourceCollectionAttempt)).scalars().one()
    assert row.status == "selected" and row.finished_at is None

    # in-flight: still no finish time
    assert telemetry.mark_attempt_started(RUN, mapping) is True
    with Session() as s:
        row = s.execute(select(SourceCollectionAttempt)).scalars().one()
    assert row.status == "selected" and row.started_at is not None
    assert row.finished_at is None

    # terminal: finish time present
    assert telemetry.finish_attempt(RUN, mapping, "written") is True
    with Session() as s:
        row = s.execute(select(SourceCollectionAttempt)).scalars().one()
    assert row.status == "written" and row.finished_at is not None


def test_the_recorder_can_skip_without_starting_under_the_real_constraint(pg):
    """selected -> skipped, started_at NULL, finished_at set - the transition
    the original CHECK made impossible, now proved against the corrected one."""
    _, Session, subject = pg
    mapping = subject["mapping_id"]
    telemetry.record_selected_batch(RUN, subject["source_id"], [mapping])
    assert telemetry.finish_attempt(RUN, mapping, "skipped", source_denied=True) is True
    with Session() as s:
        row = s.execute(select(SourceCollectionAttempt)).scalars().one()
    assert row.status == "skipped"
    assert row.started_at is None
    assert row.finished_at is not None
