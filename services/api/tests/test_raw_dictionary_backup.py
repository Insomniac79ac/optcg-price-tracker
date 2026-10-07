"""Portable export restores original evidence and internal lineage, no codec IO."""

import copy
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import RawSnapshot, RawSnapshotDictionary, Source
from app.services.backup import export_backup, restore_backup, validate_backup
from opcg_source_identity.raw_payload import PREFIX, encode, sha256


def seed(session):
    body = "<html>" + "カード pirate mock body " * 1000 + "</html>"
    source = Source(name="backup-dictionary-mock", base_url="https://mock.invalid")
    session.add(source)
    session.flush()
    rows = []
    for original in (body, body.replace("</html>", "CHANGED</html>")):
        snapshot = RawSnapshot(
            source_id=source.id,
            source_url="https://mock.invalid/card/1",
            fetched_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
            http_status=200,
            content_hash=sha256(original.encode()),
            raw_content=original,
            parser_version="fixture",
        )
        session.add(snapshot)
        session.flush()
        rows.append(snapshot)
    base, child = rows
    original = child.raw_content
    packed = encode(
        original.encode(), base_id=base.id, base_body=base.raw_content.encode()
    )
    session.add(
        RawSnapshotDictionary(
            id=child.id,
            base_snapshot_id=base.id,
            original_sha256=child.content_hash,
            base_sha256=base.content_hash,
            original_bytes=len(original.encode()),
            encoded_bytes=len(packed.encode()),
        )
    )
    child._stored_raw_content = packed
    session.commit()
    return base.id, child.id, original


def test_full_portable_roundtrip_and_replace_delete_order(db_session):
    base_id, child_id, original = seed(db_session)
    archive = export_backup(db_session, include_raw_snapshots=True)
    assert archive["metadata"]["backup_version"] == 19
    assert validate_backup(archive).valid
    assert len(archive["tables"]["raw_snapshot_dictionaries"]) == 1
    assert archive["tables"]["raw_snapshot_dictionaries"][0]["expanded_at"] is None
    assert all(
        not row["raw_content"].startswith(PREFIX)
        for row in archive["tables"]["raw_snapshots"]
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as target:
            target.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
            for mode in ("merge", "replace"):
                result = restore_backup(
                    target,
                    archive,
                    dry_run=False,
                    mode=mode,
                    confirm="RESTORE",
                    skip_lock=True,
                )
                assert result.valid, result.errors
                retained = target.get(RawSnapshot, child_id)
                assert retained.raw_content == original
                assert retained._stored_raw_content == original
                ledger = target.get(RawSnapshotDictionary, child_id)
                assert ledger.base_snapshot_id == base_id
                assert ledger.expanded_at is None  # no invented source/recovery event
    finally:
        engine.dispose()


def test_omitted_raw_provenance_omits_encoding_ledger(db_session):
    seed(db_session)
    archive = export_backup(db_session, include_raw_snapshots=False)
    assert "raw_snapshots" not in archive["tables"]
    assert "raw_snapshot_dictionaries" not in archive["tables"]
    assert validate_backup(archive).valid


def test_corrupt_or_cross_source_portable_dictionary_fails_before_restore(db_session):
    seed(db_session)
    archive = export_backup(db_session, include_raw_snapshots=True)
    for field, value in (
        ("base_snapshot_id", 999999),
        ("original_sha256", "0" * 64),
        ("original_bytes", 1),
    ):
        bad = copy.deepcopy(archive)
        bad["tables"]["raw_snapshot_dictionaries"][0][field] = value
        assert not validate_backup(bad).valid
    bad = copy.deepcopy(archive)
    bad["tables"]["raw_snapshots"][0]["source_url"] += "other"
    assert not validate_backup(bad).valid
