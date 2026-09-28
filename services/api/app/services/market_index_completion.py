"""Versioned snapshot evidence, append-only receipts and a read-only verifier.

The caller owns transactions. This module never commits, rolls back, takes a
job lock, calculates prices, or retrospectively certifies an existing archive.
See docs/market_index_snapshot_completion.md for the canonical hash contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import Date, literal, select
from sqlalchemy.orm import Session

from app.models.job_lock import JobLock
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion

DIGEST_VERSION = 1
CONTENT_FIELDS = (
    "card_print_id",
    "snapshot_date",
    "calculated_at",
    "index_value_jpy",
    "calculation_method",
    "source_count",
    "coverage_status",
    "confidence",
    "source_price_range_low_jpy",
    "source_price_range_high_jpy",
    "index_version",
    "source_semantics_version",
    "freshest_eligible_source_at",
    "stalest_eligible_source_at",
    "provenance",
)


class SnapshotCompletionError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Snapshot completion refused: {reason}")


def utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def selected_print_ids_digest(print_ids: Sequence[int]) -> str:
    if any(type(value) is not int or value <= 0 for value in print_ids) or len(
        set(print_ids)
    ) != len(print_ids):
        raise SnapshotCompletionError("selected_print_ids_mismatch")
    return _digest(
        {"format": "market-index-selected-prints-v1", "ids": sorted(print_ids)}
    )


def snapshot_content_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return _digest(
        {
            "format": "market-index-snapshot-content-v1",
            "rows": [
                {key: row[key] for key in CONTENT_FIELDS}
                for row in sorted(rows, key=lambda row: row["card_print_id"])
            ],
        }
    )


def batch_facts(
    rows: Sequence[Mapping[str, Any]], snapshot_date: date
) -> dict[str, Any]:
    """Facts from computed or stored rows; no current catalogue inference."""
    if not rows:
        raise SnapshotCompletionError("empty_selection")
    times = {utc(row["calculated_at"]) for row in rows}
    if len(times) != 1 or any(row["snapshot_date"] != snapshot_date for row in rows):
        raise SnapshotCompletionError("calculated_at_mismatch")
    calculated_at = next(iter(times))
    if calculated_at.date() != snapshot_date:
        raise SnapshotCompletionError("calculated_at_mismatch")
    versions = {(row["index_version"], row["source_semantics_version"]) for row in rows}
    if len(versions) != 1 or any(a <= 0 or b <= 0 for a, b in versions):
        raise SnapshotCompletionError("version_mismatch")
    index_version, source_semantics_version = next(iter(versions))
    return {
        "snapshot_date": snapshot_date,
        "calculated_at": calculated_at,
        "snapshot_row_count": len(rows),
        "selected_print_ids_digest": selected_print_ids_digest(
            [row["card_print_id"] for row in rows]
        ),
        "snapshot_content_digest": snapshot_content_digest(rows),
        "index_version": index_version,
        "source_semantics_version": source_semantics_version,
        "digest_version": DIGEST_VERSION,
    }


@dataclass(frozen=True)
class SnapshotCompletionVerification:
    snapshot_date: date
    receipt_exists: bool
    expected_rows: int | None
    observed_rows: int
    calculated_at: datetime | None
    calculated_at_coherent: bool
    version_coherent: bool
    selected_ids_match: bool
    content_digest_match: bool
    selected_print_ids_digest: str | None
    receipt_id: int | None
    run_id: str | None
    failure_reasons: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.failure_reasons

    def require_valid(self) -> None:
        if not self.valid:
            raise SnapshotCompletionError(self.failure_reasons[0])


def _verify_completion(
    db: Session, snapshot_date: date, *, producer_check: bool
) -> SnapshotCompletionVerification:
    receipt = MarketIndexSnapshotCompletion.__table__
    snapshot = MarketIndexSnapshot.__table__
    lock = JobLock.__table__
    day = select(literal(snapshot_date, type_=Date).label("day")).subquery()
    # One statement, no identity-map cache and no autoflush: all evidence is
    # from one PostgreSQL statement snapshot, even at READ COMMITTED.
    statement = select(
        *(c.label("receipt_" + c.name) for c in receipt.c),
        *(snapshot.c[key].label("row_" + key) for key in ("id", *CONTENT_FIELDS)),
        lock.c.status.label("producer_status"),
    ).select_from(
        day.outerjoin(receipt, receipt.c.snapshot_date == day.c.day)
        .outerjoin(snapshot, snapshot.c.snapshot_date == day.c.day)
        .outerjoin(lock, lock.c.lock_name == "market_index_snapshot")
    )
    with db.no_autoflush:
        records = list(db.execute(statement).mappings())
    receipts = {r["receipt_id"] for r in records if r["receipt_id"] is not None}
    rows = list(
        {
            r["row_id"]: {key: r["row_" + key] for key in CONTENT_FIELDS}
            for r in records
            if r["row_id"] is not None
        }.values()
    )
    stored = {key: records[0]["receipt_" + key] for key in receipt.c.keys()}
    reasons = []
    count = stored["expected_print_count"]
    calculated_at = stored["calculated_at"]
    time_match = version_match = ids_match = digest_match = False
    if not receipts:
        reasons.append("receipt_missing")
    elif len(receipts) != 1:
        reasons.append("duplicate_receipt")
    else:
        if not rows or count != len(rows) or stored["snapshot_row_count"] != len(rows):
            reasons.append("row_count_mismatch")
        time_match = bool(rows) and all(
            utc(row["calculated_at"]) == utc(calculated_at)
            and utc(row["calculated_at"]).date() == snapshot_date
            for row in rows
        )
        if not time_match:
            reasons.append("calculated_at_mismatch")
        version_match = bool(rows) and all(
            row["index_version"] == stored["index_version"]
            and row["source_semantics_version"] == stored["source_semantics_version"]
            for row in rows
        )
        if not version_match:
            reasons.append("version_mismatch")
        try:
            ids_match = (
                selected_print_ids_digest([r["card_print_id"] for r in rows])
                == stored["selected_print_ids_digest"]
            )
            digest_match = (
                snapshot_content_digest(rows) == stored["snapshot_content_digest"]
            )
        except (ValueError, SnapshotCompletionError):
            pass
        if not ids_match:
            reasons.append("selected_print_ids_mismatch")
        if not digest_match:
            reasons.append("digest_mismatch")
        if (
            stored["digest_version"] != DIGEST_VERSION
            or stored["receipt_kind"] != "atomic"
            or not stored["run_id"].strip()
            or count <= 0
            or stored["index_version"] <= 0
            or stored["source_semantics_version"] <= 0
            or utc(stored["completed_at"]) < utc(calculated_at)
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", stored[key])
                for key in ("selected_print_ids_digest", "snapshot_content_digest")
            )
        ):
            reasons.append("receipt_invalid")
    if producer_check and records[0]["producer_status"] == "active":
        # An expired lease alone does not prove the producer terminated.
        reasons.append("snapshot_in_progress")
    return SnapshotCompletionVerification(
        snapshot_date,
        bool(receipts),
        count,
        len(rows),
        utc(calculated_at) if calculated_at else None,
        time_match,
        version_match,
        ids_match,
        digest_match,
        stored["selected_print_ids_digest"],
        stored["id"],
        stored["run_id"],
        tuple(reasons),
    )


def verify_market_index_snapshot_completion(
    db: Session, snapshot_date: date
) -> SnapshotCompletionVerification:
    """Read-only durable gate, including refusal while the producer is active.

    A downstream caller must use a fresh transaction after producer completion.
    This helper cannot prove that its caller has committed its own pending rows.
    """
    return _verify_completion(db, snapshot_date, producer_check=True)


def verify_pending_snapshot_completion(
    db: Session, snapshot_date: date
) -> SnapshotCompletionVerification:
    """Producer-only pre-commit consistency check, while its job lock is held."""
    return _verify_completion(db, snapshot_date, producer_check=False)


def insert_atomic_completion(
    db: Session,
    *,
    rows: Sequence[Mapping[str, Any]],
    selected_ids: Sequence[int],
    snapshot_date: date,
    run_id: str,
) -> None:
    """Insert evidence only after pending archive rows match computed facts.

    Caller has already established an empty day under the snapshot job lock.
    A duplicate receipt is an integrity error, not an upsert/certification path.
    """
    expected = batch_facts(rows, snapshot_date)
    if expected["selected_print_ids_digest"] != selected_print_ids_digest(selected_ids):
        raise SnapshotCompletionError("selected_print_ids_mismatch")
    table = MarketIndexSnapshot.__table__
    persisted = list(
        db.execute(
            select(*(table.c[key] for key in CONTENT_FIELDS)).where(
                table.c.snapshot_date == snapshot_date
            )
        ).mappings()
    )
    observed = batch_facts(persisted, snapshot_date)
    if observed != expected:
        raise SnapshotCompletionError("pending_batch_mismatch")
    db.add(
        MarketIndexSnapshotCompletion(
            **observed,
            expected_print_count=len(selected_ids),
            run_id=run_id,
            completed_at=datetime.now(timezone.utc),
            receipt_kind="atomic",
        )
    )
    db.flush()
