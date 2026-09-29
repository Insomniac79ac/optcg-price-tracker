"""Real PostgreSQL publication, rollback, isolation and producer race proofs."""

from dataclasses import replace

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError

from app import market_value_publisher as publisher
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_point import MarketValuePoint
from app.services.job_locks import LockHeldError, acquire_lock, release_lock
from tests import test_market_index_completion_postgres as completion_postgres
from tests._market_value_publication_helpers import D26, D28, D29, archive_state, seed

# Reuse the disposable, fully migrated PostgreSQL fixture and real lock sessions.
pg_engine = completion_postgres.pg_engine
db_session = completion_postgres.db_session


def count(engine):
    with engine.connect() as connection:
        return connection.scalar(text("SELECT count(*) FROM market_value_points"))


def test_forward_commit_visibility_and_retry_with_real_locks(
    db_session, pg_engine, monkeypatch
):
    seed(db_session)
    before = archive_state(db_session)
    real_verify = publisher.verify_market_value_points
    observations = []

    def verify(db, drafts, **kwargs):
        result = real_verify(db, drafts, **kwargs)
        if result.expected == 6:
            assert result.ok
            observations.append(count(pg_engine))
        return result

    monkeypatch.setattr(publisher, "verify_market_value_points", verify)
    first = publisher.run_publisher(db_session, mode="write")
    assert first.inserted == 2 and first.plan.publication_dates == (D29,)
    assert observations == [4]  # independent connection sees no pending rows
    after = archive_state(db_session)
    assert after["market_value_points"][:4] == before["market_value_points"]
    assert after["market_index_snapshots"] == before["market_index_snapshots"]
    assert (
        after["market_index_snapshot_completions"]
        == before["market_index_snapshot_completions"]
    )
    monkeypatch.setattr(publisher, "verify_market_value_points", real_verify)
    for requested in (None, D29):
        retry = publisher.run_publisher(
            db_session, mode="write", publication_date=requested
        )
        assert retry.inserted == 0 and retry.plan.existing_verified == 6
        assert archive_state(db_session) == after


def test_dry_run_has_repeatable_read_only_and_no_job_lock_writes(
    db_session, pg_engine, monkeypatch
):
    seed(db_session)
    real_loader = publisher.load_market_value_replay_input

    def loader(db, **kwargs):
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        return real_loader(db, **kwargs)

    monkeypatch.setattr(publisher, "load_market_value_replay_input", loader)
    result = publisher.run_publisher(db_session, mode="dry-run")
    assert result.inserted == 0 and len(result.plan.new_drafts) == 2
    with pg_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM job_locks WHERE lock_name='market_value_writer'"
                )
            )
            == 0
        )
    assert count(pg_engine) == 4


def test_producer_cannot_start_after_gate_until_publication_transaction_ends(
    db_session, pg_engine, monkeypatch
):
    seed(db_session)
    real_loader = publisher.load_market_value_replay_input
    attempted = []

    def loader(db, **kwargs):
        assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert db.scalar(text("SHOW transaction_read_only")) == "off"
        with pg_engine.connect() as producer:
            producer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                producer.execute(
                    text(
                        "UPDATE job_locks SET status='active' WHERE lock_name='market_index_snapshot'"
                    )
                )
            producer.rollback()
        attempted.append(True)
        return real_loader(db, **kwargs)

    monkeypatch.setattr(publisher, "load_market_value_replay_input", loader)
    result = publisher.run_publisher(db_session, mode="write")
    assert result.inserted == 2 and attempted == [True]
    # The guard is released by commit, not left behind as an active job lock.
    with pg_engine.connect() as producer:
        producer.execute(
            text(
                "SELECT status FROM job_locks WHERE lock_name='market_index_snapshot' FOR UPDATE NOWAIT"
            )
        )
        producer.rollback()


def test_uncommitted_producer_transition_refuses_instead_of_using_stale_status(
    db_session, pg_engine
):
    seed(db_session)
    with pg_engine.connect() as producer:
        producer.execute(
            text(
                "UPDATE job_locks SET status='active' WHERE lock_name='market_index_snapshot'"
            )
        )
        with pytest.raises(OperationalError):
            publisher.run_publisher(db_session, mode="write")
        producer.rollback()
    assert count(pg_engine) == 4


def test_committed_active_producer_refuses(db_session, pg_engine):
    seed(db_session)
    acquire_lock("market_index_snapshot", "busy-producer", 300)
    try:
        with pytest.raises(publisher.WriterAbort, match="snapshot_in_progress"):
            publisher.run_publisher(db_session, mode="write")
        assert count(pg_engine) == 4
    finally:
        release_lock("market_index_snapshot", "busy-producer")


def test_shares_recovery_writer_lock(db_session, pg_engine):
    seed(db_session)
    acquire_lock("market_value_writer", "recovery-in-progress", 300)
    try:
        with pytest.raises(LockHeldError):
            publisher.run_publisher(db_session, mode="write")
        assert count(pg_engine) == 4
    finally:
        release_lock("market_value_writer", "recovery-in-progress")


def test_receipt_and_replay_inputs_share_one_consistent_snapshot(
    db_session, pg_engine, monkeypatch
):
    seed(db_session)
    real_loader = publisher.load_market_value_replay_input

    def loader(db, **kwargs):
        # A malicious/noncooperating external edit after the receipt gate must
        # not alter what this already-verified transaction derives from.
        with pg_engine.begin() as external:
            external.execute(
                text(
                    "UPDATE market_index_snapshots SET index_value_jpy=999999 WHERE snapshot_date='2026-09-29'"
                )
            )
        return real_loader(db, **kwargs)

    monkeypatch.setattr(publisher, "load_market_value_replay_input", loader)
    result = publisher.run_publisher(db_session, mode="write")
    assert result.inserted == 2
    with pg_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT tracked_value_jpy FROM market_value_points WHERE scope_kind='overall' AND point_date='2026-09-29'"
                )
            )
            == 16000
        )


def test_postgres_retains_exact_repeating_decimal_replay(db_session, pg_engine):
    seed(db_session, repeating=True)
    result = publisher.run_publisher(db_session, mode="write")
    assert result.inserted == 2
    before = archive_state(db_session)
    assert publisher.run_publisher(db_session, mode="write").inserted == 0
    assert archive_state(db_session) == before


def test_failure_at_final_gate_rolls_back_all_pending_points(
    db_session, pg_engine, monkeypatch
):
    seed(db_session, receipt_days=(D28, D29))
    real_verify = publisher.verify_market_value_points

    def fail_final(db, drafts, **kwargs):
        result = real_verify(db, drafts, **kwargs)
        if result.expected == 8:
            assert result.ok and count(pg_engine) == 4
            return replace(result, missing_keys=(drafts[-1].natural_key,))
        return result

    monkeypatch.setattr(publisher, "verify_market_value_points", fail_final)
    with pytest.raises(
        publisher.WriterAbort, match="post-publication verification failed"
    ):
        publisher.run_publisher(db_session, mode="write")
    assert count(pg_engine) == 4


def test_invalid_later_receipt_aborts_entire_extension(db_session, pg_engine):
    seed(db_session, receipt_days=(D28, D29))
    db_session.execute(
        update(MarketIndexSnapshotCompletion)
        .where(MarketIndexSnapshotCompletion.snapshot_date == D29)
        .values(snapshot_content_digest="0" * 64)
    )
    db_session.commit()
    with pytest.raises(publisher.WriterAbort, match="invalid snapshot completion"):
        publisher.run_publisher(db_session, mode="write")
    assert count(pg_engine) == 4


def test_prefix_corruption_never_gets_repaired(db_session, pg_engine):
    seed(db_session)
    db_session.execute(
        update(MarketValuePoint)
        .where(MarketValuePoint.point_date == D26)
        .values(tracked_value_jpy=999999)
    )
    db_session.commit()
    before = archive_state(db_session)
    with pytest.raises(publisher.WriterAbort, match="history conflicts"):
        publisher.run_publisher(db_session, mode="write")
    assert count(pg_engine) == 4 and archive_state(db_session) == before
