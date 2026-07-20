"""Persists app/services/market_signals.py's computed signals as reviewable,
trackable events, so recurring opportunities can be watched or dismissed
instead of recomputed fresh on every page load.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, MarketSignalEvent
from app.schemas import MarketSignalEventOut
from app.services.cache import delete_cache_prefix
from app.services.job_locks import with_job_lock
from app.services.market_signals import get_market_signals

# See 'Cache invalidation' in docs/operations.md.
_MARKET_SIGNAL_SNAPSHOT_CACHE_INVALIDATES = (
    "dashboard",
    "market_signals",
    "market_signal_events",
    "market_opportunities",
    "market_report",
    "sell_decisions",
    "buy_decisions",
)


def owned_quantity_for_card(db: Session, card_id: int | None) -> int:
    """Global (not per-user) owned quantity across every collection - matches
    the rest of the market-signals/opportunities subsystem, which is an
    admin-facing aggregate view rather than a per-user one."""
    if card_id is None:
        return 0
    total = db.scalar(
        select(func.coalesce(func.sum(CollectionItem.quantity), 0)).where(
            CollectionItem.card_id == card_id
        )
    )
    return int(total or 0)


def event_to_out(event: MarketSignalEvent, card: Card | None, owned_quantity: int) -> MarketSignalEventOut:
    return MarketSignalEventOut(
        id=event.id,
        signal_type=event.signal_type,
        status=event.status,
        severity=event.severity,
        suggested_action=event.suggested_action,
        card_id=event.card_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        set_code=card.set_code if card is not None else None,
        rarity=card.rarity if card is not None else None,
        variant=card.variant if card is not None else None,
        language=card.language if card is not None else None,
        collection_item_id=event.collection_item_id,
        owned_quantity=owned_quantity,
        message=event.message,
        notes=event.notes,
        first_seen_at=event.first_seen_at,
        last_seen_at=event.last_seen_at,
        seen_count=event.seen_count,
        last_payload=event.last_payload_json,
        dismissed_at=event.dismissed_at,
        resolved_at=event.resolved_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )

# Large enough to cover the entire catalog in one pass - snapshotting needs
# the full current signal set, not a paginated page of it.
SNAPSHOT_SIGNAL_LIMIT = 10_000


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
    alone - a card the user has already dismissed shouldn't resurface just
    because the underlying condition briefly cleared and reappeared."""
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


def snapshot_market_signals(db: Session, *, skip_lock: bool = False) -> SnapshotResult:
    """Acquires the 'market_signal_snapshot' concurrency lock for the call -
    shared by app/snapshot_market_signals.py's CLI, POST
    /admin/actions/snapshot-market-signals, and the corresponding step
    inside POST /admin/actions/full-market-refresh. skip_lock is
    test/dev-CLI only. See 'Worker job concurrency locking' in
    docs/operations.md."""
    with with_job_lock("market_signal_snapshot", skip_lock=skip_lock):
        return _snapshot_market_signals_locked(db)


def _snapshot_market_signals_locked(db: Session) -> SnapshotResult:
    now = datetime.now(timezone.utc)

    response = get_market_signals(db, limit=SNAPSHOT_SIGNAL_LIMIT, offset=0)

    created = 0
    updated = 0
    seen_dedupe_keys: set[str] = set()

    for signal in response.signals:
        dedupe_key = build_dedupe_key(
            signal.signal_type,
            signal.card_id,
            signal.collection_item_id,
            signal.suggested_action,
        )
        seen_dedupe_keys.add(dedupe_key)
        payload = signal.model_dump(mode="json")

        event = (
            db.query(MarketSignalEvent).filter(MarketSignalEvent.dedupe_key == dedupe_key).first()
        )
        if event is None:
            db.add(
                MarketSignalEvent(
                    signal_type=signal.signal_type,
                    dedupe_key=dedupe_key,
                    card_id=signal.card_id,
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
            # A dismissed event stays dismissed (still gets last_seen_at/
            # seen_count bumped above) - only a resolved event reopens, since
            # "resolved" just means "wasn't present last time", not "user
            # doesn't want to hear about this again".
            if event.status == "resolved":
                event.status = "open"
                event.resolved_at = None
            updated += 1

    db.flush()
    resolved = resolve_missing_signals(db, seen_dedupe_keys, now)
    db.commit()
    for prefix in _MARKET_SIGNAL_SNAPSHOT_CACHE_INVALIDATES:
        delete_cache_prefix(prefix)

    total_active = (
        db.query(MarketSignalEvent)
        .filter(MarketSignalEvent.status.in_(("open", "watching")))
        .count()
    )

    return SnapshotResult(
        created=created, updated=updated, resolved=resolved, total_active=total_active
    )
