"""Staging-only, bounded NEW evidence encoding and lossless local recovery.

This is an optional storage representation, not identity/price processing. A
snapshot must still be pending INSERT in the caller's transaction. Both bodies
and the dependency ledger commit before parsing. Existing evidence is never
rewritten by the writer. Disabled configuration performs no extra SQL.
"""

import json
import os
import re
from urllib.parse import parse_qsl, urlsplit

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
PARSERS = frozenset(
    {
        "yuyutei-collector-v3",
        "snkrdunk-collector-v2",
        "yuyutei-recurring-discovery-v1",
        "snkr-published-discovery-v1",
    }
)
CANARY_LIMIT = 200
DAILY_ROWS = 8192
DAILY_BYTES = 32 * 1024 * 1024
RECENT_BASE_ROWS = 32
SIBLING_RECENT_ROWS = 64
SIBLING_ID_WINDOW = 50_000
SIBLING_LEDGER_ROWS = 128
LOCK = 734027410


def admission(session):
    """Charge retained ledger rows; recovery never releases storage admission."""
    mode = os.getenv("RAW_DICTIONARY_STORAGE_MODE", "canary")
    if mode == "canary":
        count = session.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries"))
        return count < CANARY_LIMIT, None
    if mode != "daily-v1":
        raise RawPayloadError("unknown dictionary storage admission mode")
    indexes = session.execute(text("""
        SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()
        AND indexname IN ('ix_raw_dictionary_created', 'ix_raw_snapshot_dictionary_scope')
    """)).scalars().all()
    if len(indexes) != 2:
        raise RawPayloadError(
            "daily dictionary admission requires installed lookup indexes"
        )
    # Both bounds use the transaction's UTC day and match ledger server timestamps.
    # The indexed scan is bounded by one admitted day, rather than lifetime history.
    count, used = session.execute(text("""
        SELECT count(*), coalesce(sum(encoded_bytes), 0)
        FROM raw_snapshot_dictionaries
        WHERE created_at >= date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
          AND created_at < (date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + interval '1 day') AT TIME ZONE 'UTC'
    """)).one()
    return count < DAILY_ROWS and used < DAILY_BYTES, DAILY_BYTES - used


def dictionary_base(session, model, snapshot):
    """At most 32 recent bodies, then the oldest retained same-URL row.

    The scope index avoids scanning unrelated URLs. Without siblings an
    encoding always has an older plaintext same-scope dependency, so the
    oldest surviving scoped row is plaintext. With siblings a URL's first
    check may be encoded on another page; it is then used as a bounded anchor.
    Full URL equality still guards hash-index collisions. A changed page that
    cannot encode is kept plain and becomes the recent base.
    """
    scope = (
        model.source_id == snapshot.source_id,
        model.parser_version == snapshot.parser_version,
        func.md5(model.source_url) == func.md5(snapshot.source_url),
        model.source_url == snapshot.source_url,
        model.http_status == 200,
    )
    # Separate bounded projection from base loading: placing a raw-content
    # filter outside an IN/LIMIT subquery can let PostgreSQL evaluate that
    # predicate against unrelated historical rows before applying the IDs.
    # Select IDs without a body expression. PostgreSQL may evaluate a projected
    # expression before sorting scoped history, even when SQL has LIMIT 32.
    # A second statement contains only the bounded IDs as its row predicate;
    # the body marker is a projection, never a predicate on historical rows.
    ids = session.scalars(
        select(model.id).where(*scope).order_by(model.id.desc()).limit(RECENT_BASE_ROWS)
    ).all()
    if not ids:
        return None
    projected = select(model.id, model._stored_raw_content.startswith(PREFIX))
    recent = session.execute(
        projected.where(model.id.in_(ids)).order_by(model.id.desc())
    ).all()
    base_id = next(
        (snapshot_id for snapshot_id, encoded in recent if not encoded), None
    )
    if base_id is None:
        oldest_id = session.scalar(
            select(model.id).where(*scope).order_by(model.id).limit(1)
        )
        oldest = session.execute(projected.where(model.id == oldest_id)).first()
        if oldest is None:
            return None
        if oldest[1]:
            # Only a sibling-encoded first check is encoded at the bottom of
            # its URL history; with siblings ON it becomes a bounded anchor.
            return anchor_base(session, model, snapshot, oldest[0]) if sibling() else None
        base_id = oldest[0]
    # Retain the same-scope, plaintext, hash and shared-row-lock guards on the
    # exact base used to encode; the projection cannot authorise a changed row.
    return session.execute(
        select(model, func.pg_column_size(model._stored_raw_content))
        .where(
            model.id == base_id, *scope, ~model._stored_raw_content.startswith(PREFIX)
        )
        .with_for_update(read=True)
    ).first()


def url_class(url):
    """Page family: scheme, host, path with digit runs folded, sorted query keys."""
    parts = urlsplit(url)
    keys = sorted({key for key, _ in parse_qsl(parts.query, keep_blank_values=True)})
    return (parts.scheme, parts.netloc, re.sub(r"[0-9]+", "#", parts.path), tuple(keys))


def plaintext(session, ids):
    """Of these snapshot IDs, those with no active ledger encoding (no body reads)."""
    if not ids:
        return set()
    encoded = session.scalars(
        text("""
        SELECT id FROM raw_snapshot_dictionaries
        WHERE id = ANY(:ids) AND expanded_at IS NULL
    """),
        {"ids": list(ids)},
    ).all()
    return set(ids) - set(encoded)


def anchor_base(session, model, snapshot, anchor_id):
    """The URL's first encoded check, only when its own dictionary is plaintext.

    Readers stop one level below an anchor, so an anchor never depends on
    another encoding. The savings rule uses the plaintext bottom's stored size.
    """
    ledger = session.execute(
        text("""
        SELECT base_snapshot_id FROM raw_snapshot_dictionaries
        WHERE id=:id AND expanded_at IS NULL
    """),
        {"id": anchor_id},
    ).first()
    if ledger is None or not plaintext(session, [ledger[0]]):
        return None
    bottom_bytes = session.scalar(
        select(func.pg_column_size(model._stored_raw_content)).where(
            model.id == ledger[0],
            model.id < anchor_id,
            model.source_id == snapshot.source_id,
            model.parser_version == snapshot.parser_version,
            model.http_status == 200,
            ~model._stored_raw_content.startswith(PREFIX),
        )
    )
    if bottom_bytes is None:
        return None
    anchor = session.scalar(
        select(model)
        .where(
            model.id == anchor_id,
            model.source_id == snapshot.source_id,
            model.parser_version == snapshot.parser_version,
            model.source_url == snapshot.source_url,
            model.http_status == 200,
        )
        .with_for_update(read=True)
    )
    return None if anchor is None else (anchor, bottom_bytes)


def sibling_base(session, model, snapshot):
    """Newest plaintext page of the same family (source, parser, URL class).

    Candidates are bounded: the newest rows of a recent ID window plus the
    bases of recent ledger rows, then one exact row with the plaintext guard.
    """
    family = (
        model.source_id == snapshot.source_id,
        model.parser_version == snapshot.parser_version,
        model.http_status == 200,
    )
    top = session.scalar(select(func.max(model.id)))
    if top is None:
        return None
    recent = session.execute(
        select(model.id, model.source_url)
        .where(*family, model.id > top - SIBLING_ID_WINDOW)
        .order_by(model.id.desc())
        .limit(SIBLING_RECENT_ROWS)
    ).all()
    # Recent ledger rows are bounded by daily admission; the join reads row
    # headers, never bodies. Bases already used by this family are proven.
    recent += session.execute(
        text("""
        SELECT DISTINCT r.id, r.source_url
        FROM raw_snapshot_dictionaries d JOIN raw_snapshots r ON r.id = d.base_snapshot_id
        WHERE d.created_at >= now() - interval '2 days'
          AND r.source_id = :source AND r.parser_version = :parser AND r.http_status = 200
        ORDER BY r.id DESC LIMIT :limit
    """),
        {
            "source": snapshot.source_id,
            "parser": snapshot.parser_version,
            "limit": SIBLING_LEDGER_ROWS,
        },
    ).all()
    wanted = url_class(snapshot.source_url)
    candidates = {
        snapshot_id
        for snapshot_id, url in recent
        if url != snapshot.source_url and url_class(url) == wanted
    }
    for base_id in sorted(plaintext(session, candidates), reverse=True):
        found = session.execute(
            select(model, func.pg_column_size(model._stored_raw_content))
            .where(
                model.id == base_id,
                *family,
                ~model._stored_raw_content.startswith(PREFIX),
            )
            .with_for_update(read=True)
        ).first()
        if found is not None:
            return found
    return None


def sibling():
    """Second switch: sibling and anchor dictionaries. OFF keeps same-URL only."""
    return os.getenv("RAW_DICTIONARY_SIBLING", "false").lower() == "true"


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
    writer. Default canary admission retains the global 200-row ceiling.
    Explicit daily-v1 admission needs installed indexes and UTC row/byte bounds;
    recovered rows remain charged in both modes. Missing/changed dictionaries remain newly captured plain
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
    admitted, remaining_bytes = admission(session)
    if not admitted:
        return False
    model = type(snapshot)
    # Prevent this pending INSERT from autoflushing into the base selection.
    with session.no_autoflush:
        base_result = dictionary_base(session, model, snapshot)
        if base_result is None and sibling():
            base_result = sibling_base(session, model, snapshot)
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
    # PostgreSQL already compresses plaintext. Require savings against measured
    # physical base bytes, not an inflated uncompressed HTML denominator.
    if packed_bytes * 4 > current_stored_bytes * 3:
        return False
    # Reserve the captured ID before the first INSERT, so the envelope is the
    # only row version ever written. Inserting plaintext and then updating it
    # left a dead TOAST body behind until vacuum. Reconstruction is verified
    # before any write; a mismatch leaves no row and no ledger charge.
    snapshot.id = session.scalar(
        text("SELECT nextval(pg_get_serial_sequence(:table, 'id'))"),
        {"table": model.__tablename__},
    )
    if base.id >= snapshot.id:
        raise RawPayloadError("dictionary base must be older than the new snapshot")
    snapshot._stored_raw_content = packed
    if snapshot.raw_content.encode("utf-8") != body:
        raise RawPayloadError("attached reader reconstruction mismatch")
    session.flush()
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
    session.flush()
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
