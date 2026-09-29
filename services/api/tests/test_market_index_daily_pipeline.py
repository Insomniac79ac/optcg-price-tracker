"""Daily coordination with disposable mock data and real downstream writers."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from app import market_index_daily_pipeline as pipeline
from app.models.job_lock import JobLock
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_point import MarketValuePoint
from app.services.job_locks import with_job_lock
from app.snapshot_market_index import SnapshotRunResult
from tests._market_value_publication_helpers import (
    D25,
    D26,
    D27,
    D28,
    D29,
    receipt,
    seed,
)


def snapshot_result(*, empty=False, day=D29):
    return SnapshotRunResult(
        snapshot_date=None if empty else day,
        calculated_at=(
            None
            if empty
            else datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        ),
        prints_selected=0 if empty else 4,
        rows_created=0,
        rows_skipped_existing=0 if empty else 4,
        dry_run=False,
        completion_status="empty_selection" if empty else "verified_existing",
        completion_verified=not empty,
    )


@pytest.fixture
def prepared(db_session, monkeypatch):
    seed(db_session)
    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False
    )
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(
        pipeline.snapshot_market_index,
        "snapshot_market_index",
        lambda db: snapshot_result(),
    )
    return db_session


def test_verified_gate_precedes_independent_writers_and_closes_sessions(
    prepared, monkeypatch
):
    events = []
    real_verify = pipeline.verify_market_index_snapshot_completion
    real_publish = pipeline.market_value_publisher.run_publisher
    real_cpi = pipeline.card_pirate_index_writer.run_writer
    sessions = []
    factory = pipeline.SessionLocal

    class TrackedSession:
        def __enter__(self):
            self.session = factory()
            sessions.append(self)
            return self.session

        def __exit__(self, *args):
            self.session.close()
            self.closed = True

    def snap(db):
        events.append("snapshot")
        return snapshot_result()

    def verify(db, day):
        events.append("receipt")
        assert sessions[0].closed
        assert db is sessions[1].session
        return real_verify(db, day)

    def publish(db, **kwargs):
        events.append("market_value")
        assert not hasattr(sessions[1], "closed")
        assert kwargs == {"mode": "write"}
        return real_publish(db, **kwargs)

    def cpi(db):
        events.append("cpi")
        assert sessions[2].closed
        assert not hasattr(sessions[1], "closed")
        return real_cpi(db)

    monkeypatch.setattr(pipeline, "SessionLocal", TrackedSession)
    monkeypatch.setattr(pipeline.snapshot_market_index, "snapshot_market_index", snap)
    monkeypatch.setattr(pipeline, "verify_market_index_snapshot_completion", verify)
    monkeypatch.setattr(pipeline.market_value_publisher, "run_publisher", publish)
    monkeypatch.setattr(pipeline.card_pirate_index_writer, "run_writer", cpi)
    result = pipeline.run_pipeline()
    assert events == ["snapshot", "receipt", "market_value", "cpi"]
    assert all(session.closed for session in sessions)
    assert result.exit_code == 0
    assert result.receipt.status == "verified"
    assert result.market_value.dates == (D29,)
    assert result.market_value.inserted == 2
    assert result.card_pirate_index.inserted > 0
    # Legacy CPI retains its existing archive semantics. Market Value alone
    # must exclude the receipt-less September 27 and 28 gap.
    assert len(set(prepared.scalars(select(MarketValuePoint.point_date)))) == 3
    assert D27 not in set(prepared.scalars(select(MarketValuePoint.point_date)))
    assert D28 not in set(prepared.scalars(select(MarketValuePoint.point_date)))
    prepared.rollback()
    locks = {row.lock_name: row.status for row in prepared.scalars(select(JobLock))}
    assert locks[pipeline.LOCK_NAME] == "released"
    assert locks["market_value_writer"] == "released"
    assert locks["card_pirate_index"] == "released"


def test_retry_is_no_op_after_publication(prepared):
    first = pipeline.run_pipeline()
    second = pipeline.run_pipeline()
    assert first.exit_code == second.exit_code == 0
    assert second.snapshot.status == "no_op"
    assert second.snapshot.inserted == 0
    assert second.market_value.status == "no_op"
    assert second.card_pirate_index.status == "no_op"
    assert second.market_value.inserted == second.card_pirate_index.inserted == 0
    assert second.market_value.dates == ()


def test_snapshot_failure_or_empty_batch_stops_all_downstream(prepared, monkeypatch):
    def broken(db):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(pipeline.snapshot_market_index, "snapshot_market_index", broken)
    result = pipeline.run_pipeline()
    assert result.exit_code == 1 and result.snapshot.reason == "snapshot failed"
    assert result.receipt.status == result.market_value.status == "skipped"
    monkeypatch.setattr(
        pipeline.snapshot_market_index,
        "snapshot_market_index",
        lambda db: snapshot_result(empty=True),
    )
    result = pipeline.run_pipeline()
    assert result.exit_code == 0
    assert result.snapshot.status == "empty"
    assert "no receipt or publication" in result.snapshot.reason
    assert result.receipt.status == result.market_value.status == "skipped"


@pytest.mark.parametrize("defect", ["missing", "invalid", "active"])
def test_missing_invalid_or_active_receipt_blocks_publication(prepared, defect):
    if defect == "missing":
        prepared.execute(
            delete(MarketIndexSnapshotCompletion).where(
                MarketIndexSnapshotCompletion.snapshot_date == D29
            )
        )
    elif defect == "invalid":
        prepared.execute(
            update(MarketIndexSnapshotCompletion)
            .where(MarketIndexSnapshotCompletion.snapshot_date == D29)
            .values(snapshot_content_digest="0" * 64)
        )
    else:
        prepared.execute(
            update(JobLock)
            .where(JobLock.lock_name == "market_index_snapshot")
            .values(status="active")
        )
    prepared.commit()
    result = pipeline.run_pipeline()
    assert result.exit_code == 1
    expected = {
        "missing": "receipt_missing",
        "invalid": "digest_mismatch",
        "active": "snapshot_in_progress",
    }
    assert expected[defect] in result.receipt.reason
    assert result.market_value.status == result.card_pirate_index.status == "skipped"


def test_cpi_failure_allows_market_value_and_retry(prepared, monkeypatch):
    real_cpi = pipeline.card_pirate_index_writer.run_writer

    def fail(db):
        raise RuntimeError("CPI unavailable")

    monkeypatch.setattr(pipeline.card_pirate_index_writer, "run_writer", fail)
    first = pipeline.run_pipeline()
    assert first.exit_code == 1
    assert first.market_value.inserted == 2
    assert first.card_pirate_index.reason == "CPI unavailable"
    monkeypatch.setattr(pipeline.card_pirate_index_writer, "run_writer", real_cpi)
    second = pipeline.run_pipeline()
    assert second.exit_code == 0
    assert second.market_value.status == "no_op"
    assert second.card_pirate_index.inserted > 0


def test_market_value_failure_allows_cpi_and_retry(prepared, monkeypatch):
    real_publish = pipeline.market_value_publisher.run_publisher

    def fail(db, **kwargs):
        raise RuntimeError("Market Value unavailable")

    monkeypatch.setattr(pipeline.market_value_publisher, "run_publisher", fail)
    first = pipeline.run_pipeline()
    assert first.exit_code == 1
    assert first.market_value.reason == "Market Value unavailable"
    assert first.card_pirate_index.inserted > 0
    monkeypatch.setattr(pipeline.market_value_publisher, "run_publisher", real_publish)
    second = pipeline.run_pipeline()
    assert second.exit_code == 0
    assert second.market_value.inserted == 2
    assert second.card_pirate_index.status == "no_op"


def test_overlapping_coordinator_refuses_and_reports_locked(prepared):
    with with_job_lock(pipeline.LOCK_NAME):
        result = pipeline.run_pipeline()
    assert result.exit_code == 2
    assert result.snapshot.status == "locked"
    assert result.receipt.status == result.market_value.status == "skipped"


def test_snapshot_result_utc_date_survives_clock_rollover(prepared, monkeypatch):
    receipt(prepared, D25)
    observed = []
    real_verify = pipeline.verify_market_index_snapshot_completion

    def verify(db, day):
        observed.append(day)
        return real_verify(db, day)

    monkeypatch.setattr(pipeline, "verify_market_index_snapshot_completion", verify)
    monkeypatch.setattr(
        pipeline.snapshot_market_index,
        "snapshot_market_index",
        lambda db: snapshot_result(day=D25),
    )
    result = pipeline.run_pipeline()
    assert result.exit_code == 0
    assert observed == [D25]
    assert result.snapshot.dates == result.receipt.dates == (D25,)


def test_producer_lock_failure(prepared, monkeypatch):

    def held(db):
        raise pipeline.LockHeldError(
            "market_index_snapshot", "other", datetime.now(timezone.utc)
        )

    monkeypatch.setattr(pipeline.snapshot_market_index, "snapshot_market_index", held)
    result = pipeline.run_pipeline()
    assert result.exit_code == 2
    assert result.snapshot.status == "locked"
    assert result.receipt.status == "skipped"


def test_main_prints_stage_json_and_exit_status(prepared, capsys):
    assert pipeline.main() == 0
    report = capsys.readouterr().out
    assert '"receipt":' in report and '"market_value":' in report
    assert '"exit_code": 0' in report
