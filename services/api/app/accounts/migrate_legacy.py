"""Copy legacy collection and wishlist rows into the collector account tables (PLAN B2).

    python -m app.accounts.migrate_legacy --dry-run    # read-only report (default)
    python -m app.accounts.migrate_legacy --write      # copy, idempotent

A legacy row maps to a CardPrint only when its legacy ``card_id`` reaches
EXACTLY ONE active CardPrint through current, active, approved
``source_card_mappings``. Anything else is copied with ``card_print_id`` NULL
and ``resolution='unresolved'``, keeping ``legacy_card_id``, so its owner can
choose the version; it is never priced. Card codes are never used to match.

Idempotent on ``legacy_collection_item_id`` / ``legacy_wishlist_item_id``: a
row already copied is skipped. Rows that cannot be stored faithfully (two
legacy rows for the same user resolving to the same print, a quantity below 1,
a note longer than 500 characters) are reported and not copied.

The dry run sets the transaction read-only on PostgreSQL and never commits.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.accounts.models import NOTE_MAX_LENGTH, CollectionEntry, CollectionEntryEvent, WatchlistEntry
from app.models.card import Card
from app.models.card_print import CardPrint
from app.models.collection_item import CollectionItem
from app.models.source_card_mapping import SourceCardMapping
from app.models.wishlist_item import WishlistItem


def resolve_legacy_cards(db: Session, card_ids: set[int] | None = None) -> dict[int, set[int]]:
    """Legacy card id -> the active CardPrints its current approved mappings reach."""
    query = (
        select(SourceCardMapping.card_id, SourceCardMapping.card_print_id)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .where(
            SourceCardMapping.card_id.is_not(None),
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            CardPrint.is_active.is_(True),
        )
    )
    if card_ids is not None:
        if not card_ids:
            return {}
        query = query.where(SourceCardMapping.card_id.in_(card_ids))
    reached: dict[int, set[int]] = defaultdict(set)
    for card_id, print_id in db.execute(query):
        reached[card_id].add(print_id)
    return reached


def _bucket(prints: set[int]) -> str:
    if len(prints) == 1:
        return "exact"
    return "multiple_prints" if prints else "no_print"


def plan(db: Session) -> dict[str, Any]:
    """Every decision the copy would make, without writing anything."""
    items = list(db.scalars(select(CollectionItem).order_by(CollectionItem.id)))
    wishes = list(db.scalars(select(WishlistItem).order_by(WishlistItem.id)))
    reached = resolve_legacy_cards(db, {row.card_id for row in items} | {row.card_id for row in wishes})
    # Before the migration the new tables do not exist yet; nothing is copied.
    tables_present = inspect(db.connection()).has_table(CollectionEntry.__tablename__)
    copied_items: set[int] = set()
    copied_wishes: set[int] = set()
    held: set[tuple[int, int]] = set()
    watched: set[tuple[int, int]] = set()
    if tables_present:
        copied_items = set(
            db.scalars(
                select(CollectionEntry.legacy_collection_item_id).where(
                    CollectionEntry.legacy_collection_item_id.is_not(None)
                )
            )
        )
        copied_wishes = set(
            db.scalars(
                select(WatchlistEntry.legacy_wishlist_item_id).where(
                    WatchlistEntry.legacy_wishlist_item_id.is_not(None)
                )
            )
        )
        held = {
            (row.user_id, row.card_print_id)
            for row in db.execute(
                select(CollectionEntry.user_id, CollectionEntry.card_print_id).where(
                    CollectionEntry.card_print_id.is_not(None)
                )
            )
        }
        watched = {
            (row.user_id, row.card_print_id)
            for row in db.execute(
                select(WatchlistEntry.user_id, WatchlistEntry.card_print_id).where(
                    WatchlistEntry.card_print_id.is_not(None)
                )
            )
        }

    def decide(rows, copied, taken, *, quantity_of, note_of):
        decisions = []
        for row in rows:
            prints = reached.get(row.card_id, set())
            bucket = _bucket(prints)
            print_id = next(iter(prints)) if bucket == "exact" else None
            if row.id in copied:
                action = "already_copied"
            elif quantity_of(row) is not None and quantity_of(row) < 1:
                action = "skip_quantity_below_one"
            elif note_of(row) is not None and len(note_of(row)) > NOTE_MAX_LENGTH:
                action = "skip_note_too_long"
            elif print_id is not None and (row.user_id, print_id) in taken:
                action = "skip_duplicate_print"
            else:
                action = "copy_exact" if print_id is not None else "copy_unresolved"
                if print_id is not None:
                    taken.add((row.user_id, print_id))
            decisions.append(
                {
                    "legacy_id": row.id,
                    "user_id": row.user_id,
                    "legacy_card_id": row.card_id,
                    "resolution_bucket": bucket,
                    "card_print_id": print_id,
                    "action": action,
                }
            )
        return decisions

    collection = decide(
        items, copied_items, held, quantity_of=lambda r: r.quantity, note_of=lambda r: r.notes
    )
    watchlist = decide(
        wishes, copied_wishes, watched, quantity_of=lambda r: None, note_of=lambda r: r.notes
    )

    all_cards = list(db.scalars(select(Card.id)))
    every = resolve_legacy_cards(db)
    card_buckets = Counter(_bucket(every.get(card_id, set())) for card_id in all_cards)
    return {
        "account_tables_present": tables_present,
        "collection_items": collection,
        "wishlist_items": watchlist,
        "summary": {
            "collection_items": _summary(collection),
            "wishlist_items": _summary(watchlist),
            "legacy_cards": {
                "total": len(all_cards),
                "exact": card_buckets["exact"],
                "multiple_prints": card_buckets["multiple_prints"],
                "no_print": card_buckets["no_print"],
            },
        },
    }


def _summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    actions = Counter(d["action"] for d in decisions)
    buckets = Counter(d["resolution_bucket"] for d in decisions)
    return {
        "rows": len(decisions),
        "exact": buckets["exact"],
        "unresolved": buckets["multiple_prints"] + buckets["no_print"],
        "actions": dict(sorted(actions.items())),
    }


def write(db: Session, decided: dict[str, Any]) -> dict[str, int]:
    items = {row.id: row for row in db.scalars(select(CollectionItem))}
    wishes = {row.id: row for row in db.scalars(select(WishlistItem))}
    now = datetime.now(timezone.utc)
    written = Counter()
    for decision in decided["collection_items"]:
        if not decision["action"].startswith("copy_"):
            continue
        item = items[decision["legacy_id"]]
        db.add(
            CollectionEntry(
                user_id=item.user_id,
                card_print_id=decision["card_print_id"],
                quantity=item.quantity,
                paid_jpy_per_card=item.purchase_price_jpy,
                acquired_on=item.purchase_date,
                note=item.notes,
                legacy_collection_item_id=item.id,
                legacy_card_id=item.card_id,
                resolution="exact" if decision["card_print_id"] is not None else "unresolved",
            )
        )
        if decision["card_print_id"] is not None:
            db.add(
                CollectionEntryEvent(
                    user_id=item.user_id,
                    card_print_id=decision["card_print_id"],
                    quantity_before=0,
                    quantity_after=item.quantity,
                    occurred_at=now,
                )
            )
        written["collection_entries"] += 1
    for decision in decided["wishlist_items"]:
        if not decision["action"].startswith("copy_"):
            continue
        wish = wishes[decision["legacy_id"]]
        target = wish.target_buy_price_jpy
        db.add(
            WatchlistEntry(
                user_id=wish.user_id,
                card_print_id=decision["card_print_id"],
                target_jpy=target if target is not None and target > 0 else None,
                note=wish.notes,
                legacy_wishlist_item_id=wish.id,
                legacy_card_id=wish.card_id,
                resolution="exact" if decision["card_print_id"] is not None else "unresolved",
            )
        )
        written["watchlist_entries"] += 1
    db.commit()
    return {"collection_entries": written["collection_entries"], "watchlist_entries": written["watchlist_entries"]}


def run(db: Session, *, write_rows: bool) -> dict[str, Any]:
    if write_rows and not inspect(db.connection()).has_table(CollectionEntry.__tablename__):
        raise SystemExit("collector account tables are absent; run the migration first")
    if not write_rows and db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    decided = plan(db)
    report = {
        "mode": "write" if write_rows else "dry-run",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        **decided,
    }
    if write_rows:
        report["written"] = write(db, decided)
    else:
        db.rollback()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--write", action="store_true", help="copy rows; idempotent")
    args = parser.parse_args(argv)

    from app.db import SessionLocal

    with SessionLocal() as db:
        report = run(db, write_rows=args.write)
    json.dump(report, sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
