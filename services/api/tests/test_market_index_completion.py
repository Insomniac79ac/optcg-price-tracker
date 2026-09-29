"""Completion evidence and safe snapshot retries; no pricing method changes."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from app import snapshot_market_index as writer
from app.models import MarketIndexSnapshot, MarketIndexSnapshotCompletion
from app.services.market_index_completion import (
    CONTENT_FIELDS,
    SnapshotCompletionError,
    canonical_value,
    selected_print_ids_digest,
    snapshot_content_digest,
    verify_market_index_snapshot_completion,
)
from tests.test_snapshot_market_index import catalogue  # noqa: F401


def test_content_contract_covers_all_semantic_snapshot_columns():
    assert set(CONTENT_FIELDS) == set(MarketIndexSnapshot.__table__.columns.keys()) - {
        "id",
        "created_at",
    }


def test_hashes_are_order_timezone_and_json_object_order_independent():
    now = datetime(2026, 9, 28, 12, 30, 0, 123456, tzinfo=timezone.utc)
    row = dict.fromkeys(CONTENT_FIELDS)
    row.update(
        card_print_id=2,
        snapshot_date=now.date(),
        calculated_at=now,
        provenance={"日本語": [1.0, None], "value": {"b": 2, "a": 1}},
    )
    other = dict(row, card_print_id=1)
    equivalent = deepcopy(row)
    equivalent["calculated_at"] = now.astimezone(timezone(timedelta(hours=9)))
    equivalent["provenance"] = {"value": {"a": 1, "b": 2}, "日本語": [1, None]}
    assert snapshot_content_digest([row, other]) == snapshot_content_digest(
        [other, equivalent]
    )
    assert selected_print_ids_digest([2, 1]) == selected_print_ids_digest([1, 2])
    assert canonical_value(now) == "2026-09-28T12:30:00.123456Z"
    assert len(snapshot_content_digest([row])) == 64
    equivalent["provenance"]["日本語"].reverse()
    assert snapshot_content_digest([row]) != snapshot_content_digest([equivalent])


@pytest.mark.parametrize("ids", [[1, 1], [0], [-1], [True]])
def test_selected_identity_rejects_duplicates_or_invalid_ids(ids):
    with pytest.raises(SnapshotCompletionError, match="selected_print_ids_mismatch"):
        selected_print_ids_digest(ids)


def test_new_batch_commits_once_and_retry_does_not_recalculate(
    db_session, catalogue, monkeypatch
):
    commits = []
    event.listen(db_session, "after_commit", lambda _: commits.append(True))
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    assert len(commits) == 1
    assert result.completion_receipt_created and result.completion_verified
    evidence = verify_market_index_snapshot_completion(db_session, result.snapshot_date)
    assert evidence.valid
    assert evidence.expected_rows == evidence.observed_rows == 4
    assert evidence.calculated_at_coherent and evidence.version_coherent
    assert evidence.selected_ids_match and evidence.content_digest_match
    before = db_session.scalar(
        select(MarketIndexSnapshotCompletion.snapshot_content_digest)
    )

    def no_recalculation(*args):
        pytest.fail("Completed day must not recalculate prices")

    monkeypatch.setattr(writer, "get_market_index_for_prints", no_recalculation)
    repeat = writer.snapshot_market_index(db_session, skip_lock=True)
    assert repeat.completion_status == "verified_existing"
    assert repeat.rows_created == 0 and repeat.rows_skipped_existing == 4
    assert not repeat.completion_receipt_created and repeat.completion_verified
    assert len(commits) == 1
    assert db_session.query(MarketIndexSnapshotCompletion).count() == 1
    assert db_session.query(MarketIndexSnapshot).count() == 4
    assert before == db_session.scalar(
        select(MarketIndexSnapshotCompletion.snapshot_content_digest)
    )


def test_empty_selection_is_not_a_completion(db_session):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    assert result.completion_status == "empty_selection"
    assert not result.completion_verified and not result.completion_receipt_created
    assert db_session.query(MarketIndexSnapshotCompletion).count() == 0


def test_dry_run_creates_neither_rows_nor_receipt(db_session, catalogue):
    result = writer.snapshot_market_index(db_session, skip_lock=True, dry_run=True)
    assert result.completion_status == "dry_run" and not result.completion_verified
    assert db_session.query(MarketIndexSnapshot).count() == 0
    assert db_session.query(MarketIndexSnapshotCompletion).count() == 0


def test_legacy_rows_are_never_silently_certified(db_session, catalogue):
    rows = [
        writer.build_snapshot_row(value)
        for value in writer.get_market_index_for_prints(
            db_session, writer.select_snapshottable_print_ids(db_session)
        ).values()
    ]
    writer._insert_ignoring_existing(db_session, rows)
    db_session.commit()
    evidence = verify_market_index_snapshot_completion(
        db_session, rows[0]["snapshot_date"]
    )
    assert evidence.failure_reasons == ("receipt_missing",)
    assert evidence.observed_rows == 4
    with pytest.raises(SnapshotCompletionError, match="receipt_missing"):
        writer.snapshot_market_index(db_session, skip_lock=True)
    assert db_session.query(MarketIndexSnapshotCompletion).count() == 0
    assert db_session.query(MarketIndexSnapshot).count() == 4


def test_changed_membership_fails_retry_but_not_historical_verification(
    db_session, catalogue
):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    catalogue["solo"].is_active = False
    db_session.commit()
    assert verify_market_index_snapshot_completion(
        db_session, result.snapshot_date
    ).valid
    with pytest.raises(SnapshotCompletionError, match="selected_population_changed"):
        writer.snapshot_market_index(db_session, skip_lock=True)
    assert db_session.query(MarketIndexSnapshot).count() == 4


@pytest.mark.parametrize(
    "target,field,value,reason",
    [
        ("row", "index_value_jpy", 99999, "digest_mismatch"),
        ("row", "provenance", {"altered": True}, "digest_mismatch"),
        ("row", "calculated_at", datetime(2026, 1, 1), "calculated_at_mismatch"),
        ("row", "index_version", 999, "version_mismatch"),
        ("receipt", "snapshot_content_digest", "0" * 64, "digest_mismatch"),
        (
            "receipt",
            "selected_print_ids_digest",
            "0" * 64,
            "selected_print_ids_mismatch",
        ),
    ],
)
def test_verifier_detects_contradictions(
    db_session, catalogue, target, field, value, reason
):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    model = MarketIndexSnapshot if target == "row" else MarketIndexSnapshotCompletion
    row = db_session.scalars(select(model).order_by(model.id)).first()
    setattr(row, field, value)
    db_session.commit()
    verification = verify_market_index_snapshot_completion(
        db_session, result.snapshot_date
    )
    assert not verification.valid and reason in verification.failure_reasons


def test_snapshot_date_crossing_fails_before_insert(db_session, catalogue, monkeypatch):
    original = writer.get_market_index_for_prints

    def wrong_date(db, ids):
        values = original(db, ids)
        return {
            key: row.model_copy(
                update={"calculated_at": row.calculated_at - timedelta(days=1)}
            )
            for key, row in values.items()
        }

    monkeypatch.setattr(writer, "get_market_index_for_prints", wrong_date)
    with pytest.raises(SnapshotCompletionError, match="snapshot_date_changed"):
        writer.snapshot_market_index(db_session, skip_lock=True)
    assert db_session.query(MarketIndexSnapshot).count() == 0
    assert db_session.query(MarketIndexSnapshotCompletion).count() == 0


def test_verifier_is_one_select_and_does_not_flush_pending_changes(
    db_session, catalogue
):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    receipt = db_session.scalar(select(MarketIndexSnapshotCompletion))
    receipt.snapshot_content_digest = "0" * 64  # unflushed test-only change
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        evidence = verify_market_index_snapshot_completion(
            db_session, result.snapshot_date
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert evidence.valid
    assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")
    db_session.rollback()
