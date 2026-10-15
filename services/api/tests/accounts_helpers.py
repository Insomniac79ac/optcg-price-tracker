"""Shared fixtures for the collector-account tests (not a conftest; see _auth_helpers)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.accounts.models import CollectionEntry, CollectionEntryEvent
from app.models import MarketIndexSnapshot
from app.services.market_index_completion import CONTENT_FIELDS, insert_atomic_completion

SNKR_FLOOR = ("snkrdunk", "listing_floor")
YUYU_SELL = ("yuyutei", "retail_sell")


def source_values(value, contributors=(SNKR_FLOOR,)):
    return [
        {
            "source": source,
            "reference_type": reference_type,
            "contributes_to_index": value is not None,
            "eligible": value is not None,
            "value_jpy": value,
        }
        for source, reference_type in contributors
    ]


def snapshot_row(
    card_print_id, day, value, *, contributors=(SNKR_FLOOR,), index_version=3, semantics=3, checked_at=None
):
    return MarketIndexSnapshot(
        freshest_eligible_source_at=checked_at,
        card_print_id=card_print_id,
        calculated_at=datetime.combine(day, time(20, 0), tzinfo=timezone.utc),
        snapshot_date=day,
        index_value_jpy=value,
        calculation_method="test",
        source_count=1 if value is not None else 0,
        coverage_status="limited" if value is not None else "none",
        confidence="medium" if value is not None else "low",
        index_version=index_version,
        source_semantics_version=semantics,
        provenance={"source_values": source_values(value, contributors), "auxiliary_values": []},
    )


def receipt(db, day, run_id=None):
    """A real atomic completion receipt over whatever rows the day holds."""
    table = MarketIndexSnapshot.__table__
    rows = list(
        db.execute(
            select(*(table.c[key] for key in CONTENT_FIELDS)).where(table.c.snapshot_date == day)
        ).mappings()
    )
    insert_atomic_completion(
        db,
        rows=rows,
        selected_ids=[row["card_print_id"] for row in rows],
        snapshot_date=day,
        run_id=run_id or f"test-{day.isoformat()}",
    )
    db.commit()


def archive(db, day, values, *, receipted=True, **kwargs):
    """values: {card_print_id: value or None}. One completed snapshot day."""
    for print_id, value in values.items():
        db.add(snapshot_row(print_id, day, value, **kwargs))
    db.commit()
    if receipted:
        receipt(db, day)


def archive_range(db, first: date, last: date, values_for, *, skip=()):
    day = first
    while day <= last:
        if day not in skip:
            archive(db, day, values_for(day))
        day += timedelta(days=1)


def hold(db, user_id, card_print_id, quantity, at: datetime, *, before=0, entry=True, **fields):
    """Directly record a holding with a back-dated ledger event."""
    if entry:
        existing = db.scalar(
            select(CollectionEntry).where(
                CollectionEntry.user_id == user_id, CollectionEntry.card_print_id == card_print_id
            )
        )
        if existing is None:
            db.add(
                CollectionEntry(
                    user_id=user_id,
                    card_print_id=card_print_id,
                    quantity=quantity,
                    resolution="exact",
                    **fields,
                )
            )
        else:
            existing.quantity = quantity
    db.add(
        CollectionEntryEvent(
            user_id=user_id,
            card_print_id=card_print_id,
            quantity_before=before,
            quantity_after=quantity,
            occurred_at=at,
        )
    )
    db.commit()


def at(day: date, hour=12) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=timezone.utc)
