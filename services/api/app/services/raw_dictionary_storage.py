"""Staging-only, bounded NEW evidence encoding and lossless local recovery.

This is an optional storage representation, not identity/price processing. A
snapshot must still be pending INSERT in the caller's transaction. Both bodies
and the dependency ledger commit before parsing. Existing evidence is never
rewritten by the writer. Disabled configuration performs no extra SQL.
"""

import json
import os

from sqlalchemy import func, select, text
from opcg_source_identity.raw_payload import (
    MAX_BYTES,
    PREFIX,
    STAGING_ENVIRONMENT,
    RawPayloadError,
    encode,
    sha256,
)

PROJECT = "c613898d-bf03-43a6-8813-761f72e1c00a"
PARSERS = frozenset({"yuyutei-collector-v3", "snkrdunk-collector-v2"})
CANARY_LIMIT = 200
LOCK = 734027410


def enabled():
    if os.getenv("RAW_DICTIONARY_STORAGE_ENABLED", "false").lower() != "true":
        return False
    if (
        os.getenv("RAILWAY_PROJECT_ID") != PROJECT
        or os.getenv("RAILWAY_ENVIRONMENT_ID") != STAGING_ENVIRONMENT
        or os.getenv("APP_ENV") != "staging"
    ):
        raise RawPayloadError("dictionary writes require pinned staging environment")
    return True


def encode_new_snapshot(session, snapshot):
    """Return whether this NEW snapshot obtained a protected encoding.

    Try-lock admission avoids extending source-job deadlines behind another
    writer. The global 200-row ceiling includes recovered rows; retries cannot
    reset the canary. Missing/changed dictionaries remain newly captured plain
    evidence; invalid hashes and lost transaction ownership fail closed.
    """
    with session.no_autoflush:
        return _encode_new_snapshot(session, snapshot)


def _encode_new_snapshot(session, snapshot):
    if not enabled() or snapshot.parser_version not in PARSERS:
        return False
    if session.get_bind().dialect.name != "postgresql":
        raise RawPayloadError(
            "dictionary writes require PostgreSQL dependency protection"
        )
    if snapshot not in session.new or snapshot.id is not None:
        raise RawPayloadError("dictionary writer requires a pending new snapshot")
    body = snapshot.raw_content.encode("utf-8")
    if sha256(body) != snapshot.content_hash:
        raise RawPayloadError("new source evidence hash mismatch")
    if not 0 < len(body) <= MAX_BYTES or snapshot.http_status != 200:
        return False
    if not session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock)"), {"lock": LOCK}
    ):
        return False
    count = session.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries"))
    if count >= CANARY_LIMIT:
        return False
    model = type(snapshot)
    # Prevent this pending INSERT from autoflushing into the base selection.
    with session.no_autoflush:
        base_result = session.execute(
            select(model, func.pg_column_size(model._stored_raw_content))
            .where(
                model.source_id == snapshot.source_id,
                model.source_url == snapshot.source_url,
                model.parser_version == snapshot.parser_version,
                model.http_status == 200,
                ~model._stored_raw_content.startswith(PREFIX),
            )
            .order_by(model.id.desc())
            .limit(1)
            .with_for_update(read=True)
        ).first()
    if base_result is None:
        return False
    base, current_stored_bytes = base_result
    base_body = base.raw_content.encode("utf-8")
    if sha256(base_body) != base.content_hash:
        raise RawPayloadError("retained dictionary hash mismatch")
    if not 0 < len(base_body) <= MAX_BYTES:
        return False
    packed = encode(body, base_id=base.id, base_body=base_body)
    packed_bytes = len(packed.encode("utf-8"))
    # PostgreSQL already compresses plaintext. Require savings against measured
    # physical base bytes, not an inflated uncompressed HTML denominator.
    if packed_bytes * 4 > current_stored_bytes * 3:
        return False
    session.flush()
    if base.id >= snapshot.id:
        raise RawPayloadError("dictionary base must be older than the new snapshot")
    session.execute(
        text("""
        INSERT INTO raw_snapshot_dictionaries
        (id, base_snapshot_id, original_sha256, base_sha256,
         original_bytes, encoded_bytes)
        VALUES (:id, :base, :hash, :base_hash, :size, :packed)
    """),
        {
            "id": snapshot.id,
            "base": base.id,
            "hash": snapshot.content_hash,
            "base_hash": base.content_hash,
            "size": len(body),
            "packed": packed_bytes,
        },
    )
    snapshot._stored_raw_content = packed
    session.flush()
    if snapshot.raw_content.encode("utf-8") != body:
        raise RawPayloadError("attached reader reconstruction mismatch")
    return True


def expand_snapshot(session, model, snapshot_id):
    """Explicit bounded recovery after OFF; retain metadata and original lineage.

    No source fetches, parsing, observations or historical price edits. Caller
    supplies and commits one authorized recovery transaction. Only the guarded
    writer's representation may be expanded; already-plain rows are idempotent.
    """
    if enabled():
        raise RawPayloadError("disable dictionary writes before recovery")
    if (
        os.getenv("RAILWAY_PROJECT_ID") != PROJECT
        or os.getenv("RAILWAY_ENVIRONMENT_ID") != STAGING_ENVIRONMENT
        or os.getenv("APP_ENV") != "staging"
    ):
        raise RawPayloadError("dictionary recovery requires pinned staging environment")
    if type(snapshot_id) is not int or snapshot_id <= 0:
        raise RawPayloadError("explicit positive snapshot required")
    ledger = (
        session.execute(
            text("""
        SELECT * FROM raw_snapshot_dictionaries WHERE id=:id FOR UPDATE
    """),
            {"id": snapshot_id},
        )
        .mappings()
        .one_or_none()
    )
    if ledger is None:
        raise RawPayloadError("guarded dictionary ledger required")
    snapshot = session.scalar(
        select(model).where(model.id == snapshot_id).with_for_update()
    )
    if snapshot is None:
        raise RawPayloadError("retained snapshot required")
    body = snapshot.raw_content.encode("utf-8")
    if (
        sha256(body) != ledger["original_sha256"]
        or len(body) != ledger["original_bytes"]
    ):
        raise RawPayloadError("recovery body does not match immutable ledger")
    stored = snapshot._stored_raw_content
    if not stored.startswith(PREFIX):
        # Portable backups carry complete plaintext bodies and original ledger
        # metadata. Such a restored body needs no expansion or invented event.
        return False
    envelope = json.loads(stored[len(PREFIX) :])
    if (
        envelope["base_id"] != ledger["base_snapshot_id"]
        or envelope["base_sha256"] != ledger["base_sha256"]
    ):
        raise RawPayloadError("recovery dictionary does not match immutable ledger")
    snapshot._stored_raw_content = body.decode("utf-8")
    session.execute(
        text("""
        UPDATE raw_snapshot_dictionaries SET expanded_at=now()
        WHERE id=:id AND expanded_at IS NULL
    """),
        {"id": snapshot_id},
    )
    session.flush()
    return True
