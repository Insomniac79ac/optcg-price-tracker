"""PostgreSQL proof that the coordinator guards the producer through CPI."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app import market_index_daily_pipeline as pipeline
from app.snapshot_market_index import SnapshotRunResult
from tests import test_market_index_completion_postgres as completion_postgres
from tests._market_value_publication_helpers import D29, seed

# Fully migrated, disposable local database; skips if no local PostgreSQL answers.
pg_engine = completion_postgres.pg_engine
db_session = completion_postgres.db_session


@pytest.fixture
def prepared(db_session, pg_engine, monkeypatch):
    seed(db_session)
    monkeypatch.setattr(
        pipeline,
        "SessionLocal",
        sessionmaker(bind=pg_engine, autoflush=False),
    )
    monkeypatch.setattr(
        pipeline.snapshot_market_index,
        "snapshot_market_index",
        lambda db: SnapshotRunResult(
            snapshot_date=D29,
            calculated_at=datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
            prints_selected=4,
            rows_created=0,
            rows_skipped_existing=4,
            dry_run=False,
            completion_status="verified_existing",
            completion_verified=True,
        ),
    )


def test_producer_cannot_start_while_cpi_runs(prepared, pg_engine, monkeypatch):
    real_cpi = pipeline.card_pirate_index_writer.run_writer
    attempted = []

    def cpi(db):
        with pg_engine.connect() as producer:
            producer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                producer.execute(
                    text(
                        "UPDATE job_locks SET status='active' "
                        "WHERE lock_name='market_index_snapshot'"
                    )
                )
            producer.rollback()
        attempted.append(True)
        return real_cpi(db)

    monkeypatch.setattr(pipeline.card_pirate_index_writer, "run_writer", cpi)
    result = pipeline.run_pipeline()
    assert result.exit_code == 0
    assert result.market_value.inserted == 2
    assert result.card_pirate_index.inserted > 0
    assert attempted == [True]
    # The coordinator's shared row lock is gone after the run.
    with pg_engine.connect() as producer:
        producer.execute(
            text(
                "SELECT status FROM job_locks "
                "WHERE lock_name='market_index_snapshot' FOR UPDATE NOWAIT"
            )
        )
        producer.rollback()


def test_uncommitted_producer_transition_blocks_gate(prepared, pg_engine):
    with pg_engine.connect() as producer:
        producer.execute(
            text(
                "UPDATE job_locks SET status='active' "
                "WHERE lock_name='market_index_snapshot'"
            )
        )
        result = pipeline.run_pipeline()
        producer.rollback()
    assert result.exit_code == 1
    assert result.receipt.status == "failed"
    assert result.market_value.status == result.card_pirate_index.status == "skipped"
