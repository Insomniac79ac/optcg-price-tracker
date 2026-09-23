from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models import Card, Source, SourceCardMapping
from app.schemas import SourceCardMappingUpdateIn
from app.services.current_source_mapping import lookup_current_mapping
from app.services.current_source_mapping import current_identity_conflict
from app.services.mapping_listing_report import mapping_listing_report
from app.services.backup import export_backup, restore_backup, validate_backup


def seed(db):
    source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    card = Card(card_code="OP01-001", set_code="OP01", rarity="L", language="jp")
    db.add_all([source, card])
    db.flush()
    return source, card


def mapping(db, source, card, url, **kwargs):
    row = SourceCardMapping(source_id=source.id, card_id=card.id,
                            source_card_id="OP01-001", source_url=url, **kwargs)
    db.add(row)
    db.flush()
    return row


def test_lookup_duplicate_history_and_report(db_session):
    db = db_session
    source, card = seed(db)
    url = "https://snkrdunk.com/apparels/104428"
    assert lookup_current_mapping(db, source=source, url=url).current is None
    current = mapping(db, source, card, url, review_status="rejected")
    assert current.canonical_source_listing_identity == "104428"
    assert lookup_current_mapping(db, source=source, url=url).current is current
    db.commit()
    with pytest.raises(IntegrityError):
        mapping(db, source, card, "https://snkrdunk.com/en/trading-cards/104428?q=1")
    db.rollback()
    current = db.get(SourceCardMapping, current.id)
    old = mapping(
        db, source, card, "https://snkrdunk.com/en/trading-cards/104428?q=1",
        superseded_at=datetime.now(timezone.utc), superseded_by_mapping_id=current.id,
        supersession_reason="Historical compatibility evidence retained", is_active=False,
    )
    result = lookup_current_mapping(db, source=source, url=url)
    assert result.current is current and result.historical == (old,)
    report = mapping_listing_report(db)
    assert report["duplicate_current_canonical_identities"] == 0
    assert report["superseded_historical_rows"] == 1
    assert current.review_status == "rejected"


@pytest.mark.parametrize("invalid", [
    {"superseded_at": datetime.now(timezone.utc)},
    {"superseded_by_mapping_id": 1},
    {"supersession_reason": "why"},
    {"superseded_at": datetime.now(timezone.utc), "superseded_by_mapping_id": 1, "supersession_reason": " \t\n", "is_active": False},
    {"superseded_at": datetime.now(timezone.utc), "superseded_by_mapping_id": 1, "supersession_reason": "why", "is_active": True},
    {"superseded_at": datetime.now(timezone.utc), "superseded_by_mapping_id": 1, "supersession_reason": "why", "is_active": False},
])
def test_lifecycle_refuses_invalid_metadata(db_session, invalid):
    source, card = seed(db_session)
    with pytest.raises(IntegrityError):
        mapping(db_session, source, card, "https://snkrdunk.com/apparels/1", **invalid)
    db_session.rollback()


def test_client_cannot_supply_identity():
    with pytest.raises(ValidationError):
        SourceCardMappingUpdateIn(canonical_source_listing_identity="fake")


def test_historical_only_lookup_never_reuses_history(db_session):
    source, card = seed(db_session)
    successor = mapping(db_session, source, card, "https://snkrdunk.com/apparels/2")
    old = mapping(db_session, source, card, "https://snkrdunk.com/en/trading-cards/1",
                  superseded_at=datetime.now(timezone.utc), superseded_by_mapping_id=successor.id,
                  supersession_reason="Historical correction", is_active=False)
    result = lookup_current_mapping(db_session, source=source, url="https://snkrdunk.com/apparels/1")
    assert result.current is None
    assert result.historical == (old,)
    assert old.is_active is False


def test_writer_derives_identity_and_refuses_clearing_it(db_session):
    source, card = seed(db_session)
    row = mapping(db_session, source, card, "https://snkrdunk.com/apparels/142632",
                  canonical_source_listing_identity="client-forged")
    assert row.canonical_source_listing_identity == "142632"
    row.source_url = "https://unsupported.test/unknown"
    with pytest.raises(ValueError, match="source_url_not_canonical"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("old_archive", [False, True])
def test_backup_duplicates_unparseable_and_old_archive(db_session, old_archive):
    source, card = seed(db_session)
    current = mapping(db_session, source, card, "https://snkrdunk.com/apparels/104428")
    old = mapping(
        db_session, source, card, "https://snkrdunk.com/en/trading-cards/104428",
        superseded_at=datetime.now(timezone.utc), superseded_by_mapping_id=current.id,
        supersession_reason="Historical duplicate retained", is_active=False,
    )
    mapping(db_session, source, card, "https://unsupported.test/legacy")
    db_session.commit()
    archive = export_backup(db_session)
    if old_archive:
        archive["metadata"]["backup_version"] = 12
        # v12 cannot encode supersession, so an explicit v12-compatible
        # archive includes the current mapping and omits the historical row.
        archive["tables"]["source_card_mappings"] = [
            row for row in archive["tables"]["source_card_mappings"] if row["id"] != old.id
        ]
        for row in archive["tables"]["source_card_mappings"]:
            for field in ("canonical_source_listing_identity", "superseded_at", "superseded_by_mapping_id", "supersession_reason"):
                row.pop(field, None)
    validation = validate_backup(archive)
    assert validation.valid, validation.errors
    assert validation.summary["duplicate_current_canonical_identities"] == 0
    result = restore_backup(db_session, archive, dry_run=False, mode="merge", skip_lock=True)
    assert result.valid, result.errors
    assert mapping_listing_report(db_session)["unparseable_canonical_identities"] == 1


def test_backup_supersession_chain(db_session):
    source, card = seed(db_session)
    current = mapping(db_session, source, card, "https://snkrdunk.com/apparels/93522")
    old = mapping(db_session, source, card, "https://snkrdunk.com/en/trading-cards/93522",
                  superseded_at=datetime.now(timezone.utc), superseded_by_mapping_id=current.id,
                  supersession_reason="Keep historical decision", is_active=False, review_status="rejected")
    db_session.commit()
    archive = export_backup(db_session)
    archive["tables"]["source_card_mappings"].reverse()
    result = restore_backup(db_session, archive, dry_run=False, mode="replace", confirm="RESTORE", skip_lock=True)
    assert result.valid, result.errors
    db_session.expire_all()
    restored = db_session.get(SourceCardMapping, old.id)
    assert restored.superseded_by_mapping_id == current.id
    assert restored.review_status == "rejected"


@pytest.mark.parametrize("version", [12, 13])
def test_backup_refuses_two_current_rows_for_one_listing(db_session, version):
    source, card = seed(db_session)
    current = mapping(db_session, source, card, "https://snkrdunk.com/apparels/104428")
    old = mapping(
        db_session, source, card, "https://snkrdunk.com/en/trading-cards/104428",
        superseded_at=datetime.now(timezone.utc), superseded_by_mapping_id=current.id,
        supersession_reason="Historical duplicate", is_active=False,
    )
    db_session.commit()
    archive = export_backup(db_session)
    archive["metadata"]["backup_version"] = version
    for row in archive["tables"]["source_card_mappings"]:
        if row["id"] == old.id:
            row.update(superseded_at=None, superseded_by_mapping_id=None,
                       supersession_reason=None, is_active=True)
        if version == 12:
            for field in ("canonical_source_listing_identity", "superseded_at",
                          "superseded_by_mapping_id", "supersession_reason"):
                row.pop(field, None)
    validation = validate_backup(archive)
    assert not validation.valid
    assert validation.summary["duplicate_current_canonical_identities"] == 1
    assert any("duplicate current canonical listing identities" in error for error in validation.errors)
    result = restore_backup(db_session, archive, dry_run=False, mode="replace", confirm="RESTORE", skip_lock=True)
    assert not result.valid
    db_session.expire_all()
    assert db_session.get(SourceCardMapping, old.id).superseded_by_mapping_id == current.id


def test_backup_v13_restores_two_historical_rows_before_current(db_session):
    source, card = seed(db_session)
    current = mapping(db_session, source, card, "https://snkrdunk.com/apparels/93522")
    historical_ids = []
    for suffix in ("?legacy=one", "?legacy=two"):
        old = mapping(
            db_session, source, card,
            "https://snkrdunk.com/en/trading-cards/93522" + suffix,
            superseded_at=datetime.now(timezone.utc),
            superseded_by_mapping_id=current.id,
            supersession_reason="Historical duplicate", is_active=False,
        )
        historical_ids.append(old.id)
    db_session.commit()
    archive = export_backup(db_session)
    assert archive["metadata"]["backup_version"] == 13
    assert validate_backup(archive).valid
    archive["tables"]["source_card_mappings"].reverse()
    result = restore_backup(db_session, archive, dry_run=False, mode="replace", confirm="RESTORE", skip_lock=True)
    assert result.valid, result.errors
    db_session.expire_all()
    assert all(db_session.get(SourceCardMapping, id_).superseded_by_mapping_id == current.id
               for id_ in historical_ids)
    assert mapping_listing_report(db_session)["duplicate_current_canonical_identities"] == 0


def test_unique_index_race_is_translated_and_pending_write_rolled_back(db_session):
    source, card = seed(db_session)
    db_session.commit()
    db_session.add(SourceCardMapping(
        source_id=source.id, card_id=card.id, source_card_id="OP01-001",
        source_url="https://snkrdunk.com/apparels/123456",
    ))

    class DuplicateCurrent(Exception):
        diag = type("Diagnostic", (), {"constraint_name": "uq_mapping_current_canonical_listing_identity"})()

    conflict = current_identity_conflict(db_session, IntegrityError("INSERT", {}, DuplicateCurrent()))
    assert conflict is not None and conflict.code == "listing_already_mapped"
    assert db_session.query(SourceCardMapping).count() == 0
