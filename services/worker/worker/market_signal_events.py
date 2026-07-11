"""Persists worker/market_signals.py's computed signals as reviewable,
trackable events. Mirrors
services/api/app/services/market_signal_events.py exactly - see
worker/market_signals.py's module docstring for why this is a duplicate
rather than a shared import.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from worker.market_signals import compute_all_signals
from worker.models import MarketSignalEvent


def build_dedupe_key(
    signal_type: str,
    card_id: int | None,
    collection_item_id: int | None,
    suggested_action: str,
) -> str:
    """Stable identity for a signal occurrence. Owned (per-item) signals key
    on collection_item_id rather than card_id, since a single card can have
    multiple collection items each independently above/below their own
    target/purchase price."""
    if collection_item_id is not None:
        subject = f"item:{collection_item_id}"
    elif card_id is not None:
        subject = f"card:{card_id}"
    else:
        subject = "global"
    return f"{signal_type}:{subject}:{suggested_action}"


@dataclass
class SnapshotResult:
    created: int
    updated: int
    resolved: int
    total_active: int


def resolve_missing_signals(
    db: Session, current_dedupe_keys: set[str], now: datetime
) -> int:
    """Marks previously open/watching events as resolved if their dedupe_key
    is no longer present in the latest signal set. Dismissed events are left
    alone."""
    candidates = (
        db.query(MarketSignalEvent)
        .filter(MarketSignalEvent.status.in_(("open", "watching")))
        .all()
    )

    resolved = 0
    for event in candidates:
        if event.dedupe_key in current_dedupe_keys:
            continue
        event.status = "resolved"
        event.resolved_at = now
        resolved += 1

    return resolved


def snapshot_market_signals(db: Session) -> SnapshotResult:
    now = datetime.now(timezone.utc)

    signals = compute_all_signals(db)

    created = 0
    updated = 0
    seen_dedupe_keys: set[str] = set()

    for signal in signals:
        dedupe_key = build_dedupe_key(
            signal.signal_type,
            signal.card.id,
            signal.collection_item_id,
            signal.suggested_action,
        )
        seen_dedupe_keys.add(dedupe_key)
        payload = signal.to_payload_dict()

        event = (
            db.query(MarketSignalEvent).filter(MarketSignalEvent.dedupe_key == dedupe_key).first()
        )
        if event is None:
            db.add(
                MarketSignalEvent(
                    signal_type=signal.signal_type,
                    dedupe_key=dedupe_key,
                    card_id=signal.card.id,
                    collection_item_id=signal.collection_item_id,
                    severity=signal.severity,
                    suggested_action=signal.suggested_action,
                    status="open",
                    message=signal.message,
                    first_seen_at=now,
                    last_seen_at=now,
                    seen_count=1,
                    last_payload_json=payload,
                )
            )
            created += 1
        else:
            event.last_seen_at = now
            event.seen_count += 1
            event.severity = signal.severity
            event.message = signal.message
            event.suggested_action = signal.suggested_action
            event.last_payload_json = payload
            if event.status == "resolved":
                event.status = "open"
                event.resolved_at = None
            updated += 1

    db.flush()
    resolved = resolve_missing_signals(db, seen_dedupe_keys, now)
    db.commit()

    total_active = (
        db.query(MarketSignalEvent)
        .filter(MarketSignalEvent.status.in_(("open", "watching")))
        .count()
    )

    return SnapshotResult(
        created=created, updated=updated, resolved=resolved, total_active=total_active
    )
