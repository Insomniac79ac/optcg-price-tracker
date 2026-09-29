"""Receipts travel with their archive; restore cannot silently repair evidence."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app import snapshot_market_index as writer
from app.models import MarketIndexSnapshot, MarketIndexSnapshotCompletion
from app.services.backup import (
    BACKUP_VERSION,
    export_backup,
    restore_backup,
    validate_backup,
)
from app.services.market_index_completion import verify_market_index_snapshot_completion
from tests.test_snapshot_market_index import catalogue  # noqa: F401


def test_receipts_share_price_history_backup_flag(db_session, catalogue):
    writer.snapshot_market_index(db_session, skip_lock=True)
    assert BACKUP_VERSION == 15
    assert (
        "market_index_snapshot_completions" not in export_backup(db_session)["tables"]
    )
    archive = export_backup(db_session, include_prices=True)
    assert len(archive["tables"]["market_index_snapshot_completions"]) == 1
    assert validate_backup(archive).valid
    del archive["tables"]["market_index_snapshot_completions"]
    assert not validate_backup(archive).valid


def test_replace_roundtrip_and_merge_preserve_exact_receipt(db_session, catalogue):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    archive = export_backup(db_session, include_prices=True)
    for mode in ["replace", "merge"]:
        restored = restore_backup(
            db_session,
            archive,
            dry_run=False,
            mode=mode,
            confirm="RESTORE",
            skip_lock=True,
        )
        assert restored.valid, restored.errors
        assert verify_market_index_snapshot_completion(
            db_session, result.snapshot_date
        ).valid
        after = export_backup(db_session, include_prices=True)
        assert (
            after["tables"]["market_index_snapshot_completions"]
            == archive["tables"]["market_index_snapshot_completions"]
        )
        assert (
            after["tables"]["market_index_snapshots"]
            == archive["tables"]["market_index_snapshots"]
        )
    assert restored.summary["updated"]["market_index_snapshot_completions"] == 0


@pytest.mark.parametrize("tamper", ["receipt", "snapshot"])
def test_restore_conflict_rolls_back_the_entire_restore(db_session, catalogue, tamper):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    original = export_backup(db_session, include_prices=True)
    archive = deepcopy(original)
    if tamper == "receipt":
        archive["tables"]["market_index_snapshot_completions"][0][
            "snapshot_content_digest"
        ] = ("0" * 64)
    else:
        archive["tables"]["market_index_snapshots"][0]["index_value_jpy"] += 1
    restored = restore_backup(db_session, archive, dry_run=False, skip_lock=True)
    assert not restored.valid
    assert any(
        "receipt conflict" in error or "digest_mismatch" in error
        for error in restored.errors
    )
    assert verify_market_index_snapshot_completion(
        db_session, result.snapshot_date
    ).valid
    assert (
        export_backup(db_session, include_prices=True)["tables"] == original["tables"]
    )


@pytest.mark.parametrize("version", [12, 13, 14])
def test_older_backup_restores_legacy_rows_without_fabricating_receipts(
    db_session, catalogue, version
):
    result = writer.snapshot_market_index(db_session, skip_lock=True)
    archive = export_backup(db_session, include_prices=True)
    archive["metadata"]["backup_version"] = version
    del archive["tables"]["market_index_snapshot_completions"]
    db_session.query(MarketIndexSnapshotCompletion).delete()
    db_session.commit()
    restored = restore_backup(
        db_session,
        archive,
        dry_run=False,
        mode="replace",
        confirm="RESTORE",
        skip_lock=True,
    )
    assert restored.valid, restored.errors
    assert db_session.query(MarketIndexSnapshot).count() == 4
    assert db_session.scalar(select(MarketIndexSnapshotCompletion.id)) is None
    assert verify_market_index_snapshot_completion(
        db_session, result.snapshot_date
    ).failure_reasons == ("receipt_missing",)
