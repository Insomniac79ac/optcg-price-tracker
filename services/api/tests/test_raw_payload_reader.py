"""Mock-first evidence recovery, corruption refusal and plaintext backup lineage."""

import base64
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import RawSnapshot, Source
from app.services.backup import _serialize_row, _deserialize_row
from opcg_source_identity.raw_payload import (
    MAX_BYTES,
    PREFIX,
    RawPayloadError,
    decode,
    encode,
    sha256,
)

OLD = (
    "<html>" + "カード 海賊 RAW original content " * 1000 + "<price>100</price></html>"
).encode()
NEW = OLD.replace(b"100</price>", b"250</price>")


def stored():
    return encode(NEW, base_id=1, base_body=OLD)


def mutate(**fields):
    value = json.loads(stored()[len(PREFIX) :])
    value.update(fields)
    return PREFIX + json.dumps(value)


def test_independent_reconstruction_preserves_every_byte_and_hash():
    assert decode(stored(), expected_hash=sha256(NEW), load_base=lambda _: OLD) == NEW
    assert len(stored()) < len(NEW) / 20


@pytest.mark.parametrize(
    "fields",
    [
        {"base_id": True},
        {"base_id": 0},
        {"byte_length": True},
        {"byte_length": MAX_BYTES + 1},
        {"byte_length": len(NEW) + 1},
        {"sha256": "0" * 64},
        {"base_sha256": "0" * 64},
        {"data": "invalid!"},
        {"data": base64.b64encode(b"broken frame").decode()},
        {"unknown_version": 2},
    ],
)
def test_corrupt_or_unbounded_encoding_refuses_before_identity_use(fields):
    with pytest.raises(RawPayloadError):
        decode(mutate(**fields), expected_hash=sha256(NEW), load_base=lambda _: OLD)


def test_missing_or_changed_base_never_becomes_empty_evidence():
    for base in (None, b"different body", b"", b"x" * (MAX_BYTES + 1)):
        with pytest.raises(RawPayloadError):
            decode(stored(), expected_hash=sha256(NEW), load_base=lambda _: base)


def test_plaintext_writer_never_implicitly_activates_the_codec():
    snapshot = RawSnapshot(raw_content=NEW.decode(), content_hash=sha256(NEW))
    assert snapshot._stored_raw_content == snapshot.raw_content == NEW.decode()
    with pytest.raises(RawPayloadError):
        snapshot.raw_content = stored()


def seed(db):
    source = Source(name="codec-fixture", base_url="https://example.test")
    db.add(source)
    db.flush()
    root = RawSnapshot(
        id=1,
        source_id=source.id,
        source_url="https://example.test/product/1",
        fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        http_status=200,
        content_hash=sha256(OLD),
        raw_content=OLD.decode(),
        parser_version="fixture-v1",
    )
    child = RawSnapshot(
        id=2,
        source_id=source.id,
        source_url=root.source_url,
        fetched_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        http_status=200,
        content_hash=sha256(NEW),
        raw_content=NEW.decode(),
        parser_version=root.parser_version,
    )
    child._stored_raw_content = stored()  # Fixture only; no application writer exists.
    db.add_all([root, child])
    db.commit()
    db.expire_all()
    return root, child


def test_orm_reader_and_export_restore_original_text_and_metadata(db_session):
    root, child = seed(db_session)
    assert child.raw_content.encode() == NEW
    assert db_session.scalar(
        select(RawSnapshot.raw_content).where(RawSnapshot.id == 2)
    ).startswith(PREFIX)
    exported = _serialize_row(child)
    assert exported["raw_content"].encode() == NEW
    assert exported["content_hash"] == sha256(NEW)
    assert exported["fetched_at"].startswith("2026-10-02")
    restored = RawSnapshot(**_deserialize_row(RawSnapshot, exported))
    assert restored.raw_content.encode() == NEW
    assert not restored._stored_raw_content.startswith(PREFIX)
    assert restored.content_hash == child.content_hash
    assert (
        restored.source_id == child.source_id
        and restored.source_url == child.source_url
    )
    assert root.raw_content.encode() == OLD  # Dictionary is never modified.


@pytest.mark.parametrize(
    "change", ["source", "parser", "hash", "chain", "future", "missing"]
)
def test_orm_base_ownership_and_chain_guard(db_session, change):
    root, child = seed(db_session)
    if change == "source":
        child.source_id += 1
    elif change == "parser":
        root.parser_version = "different"
    elif change == "hash":
        root.content_hash = "0" * 64
    elif change == "chain":
        root._stored_raw_content = stored()
    elif change == "future":
        child.id = 1
    elif change == "missing":
        db_session.delete(root)
        db_session.flush()
    with pytest.raises(RawPayloadError):
        _ = child.raw_content


def test_detached_encoded_row_refuses_instead_of_fetching_a_source(db_session):
    _, child = seed(db_session)
    db_session.refresh(child)
    db_session.expunge(child)
    with pytest.raises(RawPayloadError):
        _ = child.raw_content


def test_plaintext_sibling_at_another_url_is_a_valid_dictionary(db_session):
    root, child = seed(db_session)
    root.source_url = "https://example.test/product/9"
    db_session.flush()
    assert child.raw_content.encode() == NEW


LATER = NEW.replace(b"250</price>", b"300</price>")


def seed_anchor(db):
    """Plaintext sibling 1 (other URL), anchor 2 encoded on 1, child 3 encoded on 2."""
    root, anchor = seed(db)
    root.source_url = "https://example.test/product/9"
    third = RawSnapshot(
        id=3,
        source_id=anchor.source_id,
        source_url=anchor.source_url,
        fetched_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        http_status=200,
        content_hash=sha256(LATER),
        raw_content=LATER.decode(),
        parser_version=anchor.parser_version,
    )
    third._stored_raw_content = encode(LATER, base_id=2, base_body=NEW)
    db.add(third)
    db.commit()
    db.expire_all()
    return root, anchor, third


def test_two_level_anchor_reconstructs_every_byte(db_session):
    _, anchor, third = seed_anchor(db_session)
    assert third.raw_content.encode() == LATER
    assert anchor.raw_content.encode() == NEW


@pytest.mark.parametrize("change", ["anchor_url", "three_levels", "anchor_hash"])
def test_anchor_is_bounded_and_fails_closed(db_session, change):
    root, anchor, third = seed_anchor(db_session)
    if change == "anchor_url":
        anchor.source_url = "https://example.test/product/8"
    elif change == "three_levels":
        # The anchor's own dictionary is encoded: a third level is refused.
        root._stored_raw_content = PREFIX + "{}"
    elif change == "anchor_hash":
        anchor.content_hash = "0" * 64
    db_session.flush()
    with pytest.raises(RawPayloadError) as refused:
        _ = third.raw_content
    if change != "anchor_hash":
        assert "plaintext dictionary required" in str(refused.value)
