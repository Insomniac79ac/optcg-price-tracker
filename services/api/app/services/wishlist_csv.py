import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, WishlistItem
from app.models.wishlist_item import WISHLIST_PRIORITIES, WISHLIST_STATUSES
from app.services.cache import delete_cache_prefix
from app.services.wishlist import find_conflicting_wishlist_item

EXPORT_COLUMNS = (
    "card_code",
    "priority",
    "status",
    "target_buy_price_jpy",
    "max_buy_price_jpy",
    "preferred_condition",
    "preferred_source",
    "desired_quantity",
    "acquired_quantity",
    "notes",
)

REQUIRED_IMPORT_COLUMNS = ("card_code",)

IMPORT_MODES = ("upsert", "append")

DEFAULT_PRIORITY = "medium"
DEFAULT_STATUS = "watching"

# Cache prefixes invalidated by any wishlist write - see 'Cache
# invalidation' in docs/operations.md. Shared (not duplicated) between
# app.api.wishlist's direct create/update/delete/import routes and
# app.services.file_jobs' background wishlist_import processing, so both
# paths stay in sync.
WISHLIST_WRITE_CACHE_PREFIXES = (
    "dashboard",
    "wishlist",
    "wishlist_summary",
    "collection_analytics",
    "wishlist_analytics",
    "market_opportunities",
    "market_signals",
    "sell_decisions",
    "buy_decisions",
    "portfolio_risk",
    "analytics_digest",
    "admin/catalog_coverage",
)


def invalidate_wishlist_write_caches() -> None:
    for prefix in WISHLIST_WRITE_CACHE_PREFIXES:
        delete_cache_prefix(prefix)


def _blank(value) -> str:
    return "" if value is None else str(value)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


class _RowSink:
    """Minimal file-like object for csv.writer - see collection_csv.py's
    _RowSink (same trick, kept as a separate copy here rather than a shared
    import, since this module otherwise has no dependency on
    collection_csv.py and one tiny class isn't worth introducing one)."""

    def __init__(self) -> None:
        self.value = ""

    def write(self, s: str) -> int:
        self.value = s
        return len(s)


def iter_wishlist_csv_rows(db: Session, *, user_id: int) -> Iterator[str]:
    """Yields the current user's wishlist_items (joined with their card) as
    CSV text chunks - a header chunk, then one chunk per row. Missing/null
    values are exported as blank cells rather than the literal string
    "None". export_wishlist_csv() below is just this joined into one
    string, kept for callers (the export CLI, tests) that want the whole
    result at once."""
    items = db.scalars(
        select(WishlistItem)
        .join(Card, WishlistItem.card_id == Card.id)
        .where(WishlistItem.user_id == user_id)
        .order_by(WishlistItem.id)
    ).all()

    card_ids = {item.card_id for item in items}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }

    sink = _RowSink()
    writer = csv.DictWriter(sink, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    yield sink.value

    for item in items:
        card = cards_by_id[item.card_id]
        writer.writerow(
            {
                "card_code": card.card_code,
                "priority": item.priority,
                "status": item.status,
                "target_buy_price_jpy": _blank(item.target_buy_price_jpy),
                "max_buy_price_jpy": _blank(item.max_buy_price_jpy),
                "preferred_condition": _blank(item.preferred_condition),
                "preferred_source": _blank(item.preferred_source),
                "desired_quantity": item.desired_quantity,
                "acquired_quantity": item.acquired_quantity,
                "notes": _blank(item.notes),
            }
        )
        yield sink.value


def export_wishlist_csv(db: Session, *, user_id: int) -> str:
    """Whole-string convenience wrapper around iter_wishlist_csv_rows - used
    by tests; the direct HTTP export endpoint and background export jobs
    use the generator directly instead."""
    return "".join(iter_wishlist_csv_rows(db, user_id=user_id))


def export_filename(today: date | None = None) -> str:
    day = today or datetime.now(timezone.utc).date()
    return f"wishlist_export_{day.strftime('%Y%m%d')}.csv"


@dataclass
class ParsedRow:
    row_number: int
    card_code: str
    card_id: int
    priority: str
    status: str
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_condition: str | None
    preferred_source: str | None
    desired_quantity: int
    acquired_quantity: int
    notes: str | None


@dataclass
class RowError:
    row_number: int
    card_code: str | None
    error: str


@dataclass
class RowOutcome:
    row_number: int
    card_code: str
    matched_card_id: int
    action: str
    priority: str
    status: str


@dataclass
class ImportResult:
    dry_run: bool
    mode: str
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)
    preview: list[RowOutcome] = field(default_factory=list)


def _parse_int(value: str | None, field_name: str, row_number: int, card_code: str) -> tuple[int | None, RowError | None]:
    cleaned = _clean(value)
    if cleaned is None:
        return None, None
    try:
        parsed = int(cleaned)
    except ValueError:
        return None, RowError(row_number, card_code, f"{field_name} must be a valid integer")
    if parsed < 0:
        return None, RowError(row_number, card_code, f"{field_name} must be >= 0")
    return parsed, None


def _parse_row(
    db: Session, row_number: int, row: dict[str, str]
) -> tuple[ParsedRow | None, RowError | None]:
    card_code = _clean(row.get("card_code"))
    if card_code is None:
        return None, RowError(row_number, None, "card_code is required")

    matches = db.scalars(select(Card).where(Card.card_code == card_code)).all()
    if len(matches) == 0:
        return None, RowError(row_number, card_code, "Card code not found")
    if len(matches) > 1:
        return None, RowError(
            row_number, card_code, f"Card code matches {len(matches)} cards; ambiguous match"
        )
    card = matches[0]

    priority_raw = _clean(row.get("priority"))
    priority = priority_raw if priority_raw is not None else DEFAULT_PRIORITY
    if priority not in WISHLIST_PRIORITIES:
        return None, RowError(
            row_number, card_code, f"Invalid priority '{priority}'. Must be one of {list(WISHLIST_PRIORITIES)}"
        )

    status_raw = _clean(row.get("status"))
    status = status_raw if status_raw is not None else DEFAULT_STATUS
    if status not in WISHLIST_STATUSES:
        return None, RowError(
            row_number, card_code, f"Invalid status '{status}'. Must be one of {list(WISHLIST_STATUSES)}"
        )

    target_buy_price_jpy, err = _parse_int(row.get("target_buy_price_jpy"), "target_buy_price_jpy", row_number, card_code)
    if err is not None:
        return None, err
    max_buy_price_jpy, err = _parse_int(row.get("max_buy_price_jpy"), "max_buy_price_jpy", row_number, card_code)
    if err is not None:
        return None, err

    desired_quantity_raw = _clean(row.get("desired_quantity"))
    desired_quantity = 1
    if desired_quantity_raw is not None:
        try:
            desired_quantity = int(desired_quantity_raw)
        except ValueError:
            return None, RowError(row_number, card_code, "desired_quantity must be a valid integer")
        if desired_quantity < 1:
            return None, RowError(row_number, card_code, "desired_quantity must be >= 1")

    acquired_quantity_raw = _clean(row.get("acquired_quantity"))
    acquired_quantity = 0
    if acquired_quantity_raw is not None:
        try:
            acquired_quantity = int(acquired_quantity_raw)
        except ValueError:
            return None, RowError(row_number, card_code, "acquired_quantity must be a valid integer")
        if acquired_quantity < 0:
            return None, RowError(row_number, card_code, "acquired_quantity must be >= 0")

    return (
        ParsedRow(
            row_number=row_number,
            card_code=card_code,
            card_id=card.id,
            priority=priority,
            status=status,
            target_buy_price_jpy=target_buy_price_jpy,
            max_buy_price_jpy=max_buy_price_jpy,
            preferred_condition=_clean(row.get("preferred_condition")),
            preferred_source=_clean(row.get("preferred_source")),
            desired_quantity=desired_quantity,
            acquired_quantity=acquired_quantity,
            notes=_clean(row.get("notes")),
        ),
        None,
    )


def _apply_row_to_item(item: WishlistItem, parsed: ParsedRow) -> None:
    item.priority = parsed.priority
    item.status = parsed.status
    item.target_buy_price_jpy = parsed.target_buy_price_jpy
    item.max_buy_price_jpy = parsed.max_buy_price_jpy
    item.preferred_condition = parsed.preferred_condition
    item.preferred_source = parsed.preferred_source
    item.desired_quantity = parsed.desired_quantity
    item.acquired_quantity = parsed.acquired_quantity
    item.notes = parsed.notes


def _create_item(db: Session, parsed: ParsedRow, *, user_id: int) -> WishlistItem:
    item = WishlistItem(
        user_id=user_id,
        card_id=parsed.card_id,
        priority=parsed.priority,
        status=parsed.status,
        target_buy_price_jpy=parsed.target_buy_price_jpy,
        max_buy_price_jpy=parsed.max_buy_price_jpy,
        preferred_condition=parsed.preferred_condition,
        preferred_source=parsed.preferred_source,
        desired_quantity=parsed.desired_quantity,
        acquired_quantity=parsed.acquired_quantity,
        notes=parsed.notes,
    )
    db.add(item)
    db.flush()
    return item


def _outcome(parsed: ParsedRow, action: str) -> RowOutcome:
    return RowOutcome(
        row_number=parsed.row_number,
        card_code=parsed.card_code,
        matched_card_id=parsed.card_id,
        action=action,
        priority=parsed.priority,
        status=parsed.status,
    )


def import_wishlist_csv(
    db: Session, csv_text: str, *, dry_run: bool, mode: str, user_id: int
) -> ImportResult:
    """Parses and (optionally) applies a wishlist CSV import, scoped to
    user_id. Never creates cards - card_code must already exist in the
    catalog. In upsert mode, rows within the same batch that share a
    (card_id, preferred_condition, preferred_source) key target the same
    wishlist item - the first such row in the file creates it, later rows in
    the same file update it - whether or not this is a dry run."""
    if mode not in IMPORT_MODES:
        raise ValueError(f"mode must be one of {IMPORT_MODES}")

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    missing_columns = [c for c in REQUIRED_IMPORT_COLUMNS if c not in fieldnames]
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {missing_columns}")

    result = ImportResult(dry_run=dry_run, mode=mode)

    # Tracks upsert targets claimed earlier in *this* batch, so repeated rows
    # for the same card/condition/source update the same row instead of each
    # creating a new one - even under dry_run, where nothing is persisted yet.
    batch_upsert_targets: dict[tuple[int, str | None, str | None], int | None] = {}

    for row_number, row in enumerate(reader, start=2):
        result.total_rows += 1
        parsed, error = _parse_row(db, row_number, row)
        if error is not None:
            result.error_rows += 1
            result.skipped += 1
            result.errors.append(error)
            continue

        assert parsed is not None
        result.valid_rows += 1

        if mode == "append":
            if dry_run:
                result.preview.append(_outcome(parsed, "would_create"))
            else:
                _create_item(db, parsed, user_id=user_id)
                result.created += 1
                result.preview.append(_outcome(parsed, "created"))
            continue

        # mode == "upsert"
        key = (parsed.card_id, parsed.preferred_condition, parsed.preferred_source)
        if key in batch_upsert_targets:
            existing_item_id = batch_upsert_targets[key]
            if dry_run:
                result.preview.append(_outcome(parsed, "would_update"))
            else:
                item = db.get(WishlistItem, existing_item_id)
                assert item is not None
                _apply_row_to_item(item, parsed)
                result.updated += 1
                result.preview.append(_outcome(parsed, "updated"))
            continue

        existing_item = find_conflicting_wishlist_item(
            db, user_id, parsed.card_id, parsed.preferred_condition, parsed.preferred_source
        )
        if existing_item is not None:
            if dry_run:
                batch_upsert_targets[key] = existing_item.id
                result.preview.append(_outcome(parsed, "would_update"))
            else:
                _apply_row_to_item(existing_item, parsed)
                result.updated += 1
                batch_upsert_targets[key] = existing_item.id
                result.preview.append(_outcome(parsed, "updated"))
        else:
            if dry_run:
                batch_upsert_targets[key] = None
                result.preview.append(_outcome(parsed, "would_create"))
            else:
                item = _create_item(db, parsed, user_id=user_id)
                result.created += 1
                batch_upsert_targets[key] = item.id
                result.preview.append(_outcome(parsed, "created"))

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return result
