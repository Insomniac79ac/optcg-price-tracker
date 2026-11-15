"""RAW first: every response is stored and committed before anything parses it (plan §2.4).

Storage. The protected dictionary encoding (a body stored as a zstd delta against an older
same-URL body) is what the Dorasuta storage estimate assumes (SV §2.1: about 6 KB per list page
against 191-338 KB plaintext). Its writer, app.services.raw_dictionary_storage, admits only the two
existing parsers, and that file is a runtime input of both existing collectors (plan §2.7), so the
kit keeps its own copy of the admission step for its own parser versions and reuses the module's
guards unchanged: the pinned-staging `enabled()` switch, the shared daily `admission()` bounds, the
`dictionary_base()` choice and the `raw_snapshot_dictionaries` ledger. Readers decode both the same
way (opcg_source_identity.raw_payload). Off unless RAW_DICTIONARY_STORAGE_ENABLED is true in the
pinned staging environment; otherwise bodies are stored plain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import RawSnapshot
from app.services.raw_dictionary_storage import LOCK, admission, dictionary_base, enabled
from opcg_source_identity.raw_payload import MAX_BYTES, RawPayloadError, encode, sha256

from source_collector_kit.fetch import Response
from source_collector_kit.registry import registered

def response_text(response: Response) -> str:
    """The body as text. UTF-8 first (both new sources serve UTF-8, MEASURED), then the declared
    charset; anything else is refused rather than stored lossily."""
    try:
        return response.body.decode("utf-8")
    except UnicodeDecodeError:
        content_type = {k.lower(): v for k, v in response.headers.items()}.get("content-type", "")
        charset = content_type.partition("charset=")[2].split(";")[0].strip()
        if not charset:
            raise
        return response.body.decode(charset)


def write_raw(
    db: Session, *, source_id: int, response: Response, parser_version: str, fetched_at: datetime
) -> RawSnapshot:
    """Add and flush the RAW row for one response; the caller commits before parsing."""
    body = response_text(response)
    snapshot = RawSnapshot(
        source_id=source_id,
        source_url=response.url[:1024],
        fetched_at=fetched_at,
        http_status=response.status,
        content_hash=sha256(body.encode("utf-8")),
        raw_content=body,
        parser_version=parser_version,
    )
    db.add(snapshot)
    encode_new_snapshot(db, snapshot)
    db.flush()
    return snapshot


def encode_new_snapshot(session: Session, snapshot: RawSnapshot) -> bool:
    """The guarded dictionary encoding for kit parsers; same steps as the shared writer."""
    with session.no_autoflush:
        return _encode(session, snapshot)


def _encode(session: Session, snapshot: RawSnapshot) -> bool:
    # Only a registered kit parser's pages, so verify-lossless can re-parse what was stored.
    if snapshot.parser_version not in registered() or not enabled():
        return False
    if session.get_bind().dialect.name != "postgresql":
        raise RawPayloadError("dictionary writes require PostgreSQL dependency protection")
    if snapshot not in session.new or snapshot.id is not None:
        raise RawPayloadError("dictionary writer requires a pending new snapshot")
    body = snapshot.raw_content.encode("utf-8")
    if sha256(body) != snapshot.content_hash:
        raise RawPayloadError("new source evidence hash mismatch")
    if not 0 < len(body) <= MAX_BYTES or snapshot.http_status != 200:
        return False
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:lock)"), {"lock": LOCK}):
        return False
    admitted, remaining_bytes = admission(session)
    if not admitted:
        return False
    model = type(snapshot)
    base_result = dictionary_base(session, model, snapshot)
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
    if remaining_bytes is not None and packed_bytes > remaining_bytes:
        return False
    if packed_bytes * 4 > current_stored_bytes * 3:
        return False
    snapshot.id = session.scalar(
        text("SELECT nextval(pg_get_serial_sequence(:table, 'id'))"), {"table": model.__tablename__}
    )
    if base.id >= snapshot.id:
        raise RawPayloadError("dictionary base must be older than the new snapshot")
    snapshot._stored_raw_content = packed
    if snapshot.raw_content.encode("utf-8") != body:
        raise RawPayloadError("attached reader reconstruction mismatch")
    session.flush()
    session.execute(
        text(
            "INSERT INTO raw_snapshot_dictionaries (id, base_snapshot_id, original_sha256, base_sha256,"
            " original_bytes, encoded_bytes) VALUES (:id, :base, :hash, :base_hash, :size, :packed)"
        ),
        {
            "id": snapshot.id,
            "base": base.id,
            "hash": snapshot.content_hash,
            "base_hash": base.content_hash,
            "size": len(body),
            "packed": packed_bytes,
        },
    )
    session.flush()
    return True
