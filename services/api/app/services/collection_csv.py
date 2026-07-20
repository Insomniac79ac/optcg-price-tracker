import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, CollectorGroup, CollectorTag
from app.models.collection_item import COLLECTION_ITEM_STATUSES
from app.services.cache import delete_cache_prefix
from app.services.collector import (
    ensure_collection_item_group,
    ensure_collection_item_tag,
    get_groups_for_collection_items,
    get_or_create_group,
    get_or_create_tag,
    get_tags_for_collection_items,
)
from app.services.grading import get_submissions_for_items, latest_submission

EXPORT_COLUMNS = (
    "card_code",
    "name_en",
    "name_jp",
    "set_code",
    "rarity",
    "variant",
    "language",
    "quantity",
    "condition_label",
    "purchase_price_jpy",
    "purchase_date",
    "purchase_source",
    "target_sell_price_jpy",
    "status",
    "notes",
    "tags",
    "groups",
    "grading_status",
    "grading_company",
    "final_grade",
    "cert_number",
    "graded_value_jpy",
    "created_at",
    "updated_at",
)

NAME_LIST_SEPARATOR = ";"

REQUIRED_IMPORT_COLUMNS = ("card_code", "quantity")

IMPORT_MODES = ("upsert", "append")

DEFAULT_STATUS = "hold"

# Cache prefixes invalidated by any collection write - see 'Cache
# invalidation' in docs/operations.md. Shared (not duplicated) between
# app.api.collection's direct create/update/delete/import routes and
# app.services.file_jobs' background collection_import processing, so both
# paths stay in sync.
COLLECTION_WRITE_CACHE_PREFIXES = (
    "dashboard",
    "collection_valuation",
    "collection_history",
    "collection_analytics",
    "wishlist_analytics",
    "market_opportunities",
    "market_signals",
    "wishlist_summary",
    "grading_summary",
    "sell_decisions",
    "buy_decisions",
)


def invalidate_collection_write_caches() -> None:
    for prefix in COLLECTION_WRITE_CACHE_PREFIXES:
        delete_cache_prefix(prefix)


def _blank(value: str) -> str:
    return "" if value is None else str(value)


class _RowSink:
    """Minimal file-like object for csv.writer: write() just stashes the
    latest chunk instead of appending to a growing in-memory buffer - the
    standard trick for turning csv.writer's row-at-a-time writes into a
    generator (see iter_collection_csv_rows below), so a StreamingResponse
    or a background export job can emit/persist each row as it's produced
    rather than holding the whole rendered CSV text in memory at once."""

    def __init__(self) -> None:
        self.value = ""

    def write(self, s: str) -> int:
        self.value = s
        return len(s)


def iter_collection_csv_rows(db: Session, *, user_id: int) -> Iterator[str]:
    """Yields the current user's collection_items (joined with their card)
    as CSV text chunks - a header chunk, then one chunk per row. Missing/
    null values are exported as blank cells rather than the literal string
    "None". export_collection_csv() below is just this joined into one
    string, kept for callers (the export CLI, tests) that want the whole
    result at once.

    Note: this still runs the underlying item/tag/group/grading queries
    eagerly (same as before) rather than a server-side cursor - what's
    streamed incrementally is CSV *rendering*, not the database read. For
    this app's per-user collection sizes that's the practical trade-off -
    see "Large import/export jobs" in docs/operations.md."""
    items = db.scalars(
        select(CollectionItem)
        .join(Card, CollectionItem.card_id == Card.id)
        .where(CollectionItem.user_id == user_id)
        .order_by(CollectionItem.id)
    ).all()

    card_ids = {item.card_id for item in items}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }

    item_ids = {item.id for item in items}
    tags_by_item = get_tags_for_collection_items(db, item_ids)
    groups_by_item = get_groups_for_collection_items(db, item_ids)
    submissions_by_item = get_submissions_for_items(db, item_ids)

    sink = _RowSink()
    writer = csv.DictWriter(sink, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    yield sink.value

    for item in items:
        card = cards_by_id[item.card_id]
        latest = latest_submission(submissions_by_item, item.id)
        writer.writerow(
            {
                "card_code": card.card_code,
                "name_en": _blank(card.name_en),
                "name_jp": _blank(card.name_jp),
                "set_code": card.set_code,
                "rarity": card.rarity,
                "variant": _blank(card.variant),
                "language": card.language,
                "quantity": item.quantity,
                "condition_label": _blank(item.condition_label),
                "purchase_price_jpy": _blank(item.purchase_price_jpy),
                "purchase_date": item.purchase_date.isoformat() if item.purchase_date else "",
                "purchase_source": _blank(item.purchase_source),
                "target_sell_price_jpy": _blank(item.target_sell_price_jpy),
                "status": item.status,
                "notes": _blank(item.notes),
                "tags": NAME_LIST_SEPARATOR.join(t.name for t in tags_by_item.get(item.id, [])),
                "groups": NAME_LIST_SEPARATOR.join(
                    g.name for g in groups_by_item.get(item.id, [])
                ),
                "grading_status": _blank(latest.submission_status if latest else None),
                "grading_company": _blank(latest.grading_company if latest else None),
                "final_grade": _blank(latest.final_grade if latest else None),
                "cert_number": _blank(latest.cert_number if latest else None),
                "graded_value_jpy": _blank(latest.graded_value_jpy if latest else None),
                "created_at": item.created_at.isoformat() if item.created_at else "",
                "updated_at": item.updated_at.isoformat() if item.updated_at else "",
            }
        )
        yield sink.value


def export_collection_csv(db: Session, *, user_id: int) -> str:
    """Whole-string convenience wrapper around iter_collection_csv_rows -
    used by the export CLI and tests; the direct HTTP export endpoint and
    background export jobs use the generator directly instead."""
    return "".join(iter_collection_csv_rows(db, user_id=user_id))


def export_filename(today: date | None = None) -> str:
    day = today or datetime.now(timezone.utc).date()
    return f"collection_export_{day.strftime('%Y%m%d')}.csv"


@dataclass
class ParsedRow:
    row_number: int
    card_code: str
    card_id: int
    quantity: int
    condition_label: str | None
    purchase_price_jpy: int | None
    purchase_date: date | None
    purchase_source: str | None
    target_sell_price_jpy: int | None
    status: str
    notes: str | None
    tag_names: list[str]
    group_names: list[str]


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
    quantity: int
    status: str
    tags: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


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
    tags_created: list[str] = field(default_factory=list)
    groups_created: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_name_list(value: str | None) -> list[str]:
    if not value:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for part in value.split(NAME_LIST_SEPARATOR):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


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
            row_number,
            card_code,
            f"Card code matches {len(matches)} cards; ambiguous match",
        )
    card = matches[0]

    quantity_raw = _clean(row.get("quantity"))
    if quantity_raw is None:
        return None, RowError(row_number, card_code, "quantity is required")
    try:
        quantity = int(quantity_raw)
    except ValueError:
        return None, RowError(row_number, card_code, "quantity must be a valid integer")
    if quantity < 1:
        return None, RowError(row_number, card_code, "quantity must be >= 1")

    purchase_price_raw = _clean(row.get("purchase_price_jpy"))
    purchase_price_jpy: int | None = None
    if purchase_price_raw is not None:
        try:
            purchase_price_jpy = int(purchase_price_raw)
        except ValueError:
            return None, RowError(
                row_number, card_code, "purchase_price_jpy must be a valid integer"
            )
        if purchase_price_jpy < 0:
            return None, RowError(
                row_number, card_code, "purchase_price_jpy must be >= 0"
            )

    target_sell_raw = _clean(row.get("target_sell_price_jpy"))
    target_sell_price_jpy: int | None = None
    if target_sell_raw is not None:
        try:
            target_sell_price_jpy = int(target_sell_raw)
        except ValueError:
            return None, RowError(
                row_number, card_code, "target_sell_price_jpy must be a valid integer"
            )
        if target_sell_price_jpy < 0:
            return None, RowError(
                row_number, card_code, "target_sell_price_jpy must be >= 0"
            )

    status_raw = _clean(row.get("status"))
    status = status_raw if status_raw is not None else DEFAULT_STATUS
    if status not in COLLECTION_ITEM_STATUSES:
        return None, RowError(
            row_number,
            card_code,
            f"Invalid status '{status}'. Must be one of {list(COLLECTION_ITEM_STATUSES)}",
        )

    purchase_date_raw = _clean(row.get("purchase_date"))
    purchase_date_value: date | None = None
    if purchase_date_raw is not None:
        try:
            purchase_date_value = datetime.strptime(purchase_date_raw, "%Y-%m-%d").date()
        except ValueError:
            return None, RowError(
                row_number,
                card_code,
                "purchase_date must be in YYYY-MM-DD format",
            )

    return (
        ParsedRow(
            row_number=row_number,
            card_code=card_code,
            card_id=card.id,
            quantity=quantity,
            condition_label=_clean(row.get("condition_label")),
            purchase_price_jpy=purchase_price_jpy,
            purchase_date=purchase_date_value,
            purchase_source=_clean(row.get("purchase_source")),
            target_sell_price_jpy=target_sell_price_jpy,
            status=status,
            notes=_clean(row.get("notes")),
            tag_names=_parse_name_list(row.get("tags")),
            group_names=_parse_name_list(row.get("groups")),
        ),
        None,
    )


def _upsert_key(parsed: ParsedRow) -> tuple[int, str | None, str | None]:
    return (parsed.card_id, parsed.condition_label, parsed.purchase_source)


def _find_existing_item(db: Session, parsed: ParsedRow, *, user_id: int) -> CollectionItem | None:
    filters = [CollectionItem.card_id == parsed.card_id, CollectionItem.user_id == user_id]
    if parsed.condition_label is None:
        filters.append(CollectionItem.condition_label.is_(None))
    else:
        filters.append(CollectionItem.condition_label == parsed.condition_label)
    if parsed.purchase_source is None:
        filters.append(CollectionItem.purchase_source.is_(None))
    else:
        filters.append(CollectionItem.purchase_source == parsed.purchase_source)
    return db.scalars(select(CollectionItem).where(*filters)).first()


def _apply_row_to_item(item: CollectionItem, parsed: ParsedRow) -> None:
    item.quantity = parsed.quantity
    item.condition_label = parsed.condition_label
    item.purchase_price_jpy = parsed.purchase_price_jpy
    item.purchase_date = parsed.purchase_date
    item.purchase_source = parsed.purchase_source
    item.target_sell_price_jpy = parsed.target_sell_price_jpy
    item.status = parsed.status
    item.notes = parsed.notes


def _create_item(db: Session, parsed: ParsedRow, *, user_id: int) -> CollectionItem:
    item = CollectionItem(
        user_id=user_id,
        card_id=parsed.card_id,
        quantity=parsed.quantity,
        condition_label=parsed.condition_label,
        purchase_price_jpy=parsed.purchase_price_jpy,
        purchase_date=parsed.purchase_date,
        purchase_source=parsed.purchase_source,
        target_sell_price_jpy=parsed.target_sell_price_jpy,
        status=parsed.status,
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
        quantity=parsed.quantity,
        status=parsed.status,
        tags=parsed.tag_names,
        groups=parsed.group_names,
    )


def _assign_tags_and_groups(
    db: Session,
    item_id: int,
    parsed: ParsedRow,
    created_tag_names: set[str],
    created_group_names: set[str],
    *,
    user_id: int,
) -> None:
    for name in parsed.tag_names:
        tag, created = get_or_create_tag(db, name, user_id=user_id)
        if created:
            created_tag_names.add(name)
        ensure_collection_item_tag(db, item_id, tag.id)
    for name in parsed.group_names:
        group, created = get_or_create_group(db, name, user_id=user_id)
        if created:
            created_group_names.add(name)
        ensure_collection_item_group(db, item_id, group.id)


def import_collection_csv(
    db: Session, csv_text: str, *, dry_run: bool, mode: str, user_id: int
) -> ImportResult:
    """Parses and (optionally) applies a collection CSV import. When
    dry_run is True, no DB writes occur - the preview shows the actions that
    *would* be taken (would_create/would_update). When False, rows are
    written and the preview shows what actually happened (created/updated).

    In upsert mode, rows within the same batch that share a
    (card_id, condition_label, purchase_source) key target the same
    collection item - the first such row in the file creates it, later rows
    in the same file update it - whether or not this is a dry run.
    """
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

    # Tag/group bookkeeping across the whole batch: under dry_run nothing is
    # written, so `all_tag_names`/`all_group_names` collect every name seen
    # and are diffed against the DB once, at the end, to report what *would*
    # be created. Under a real run, `created_tag_names`/`created_group_names`
    # are populated directly as rows are processed.
    all_tag_names: set[str] = set()
    all_group_names: set[str] = set()
    created_tag_names: set[str] = set()
    created_group_names: set[str] = set()

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
        all_tag_names.update(parsed.tag_names)
        all_group_names.update(parsed.group_names)

        if mode == "append":
            if dry_run:
                result.preview.append(_outcome(parsed, "would_create"))
            else:
                item = _create_item(db, parsed, user_id=user_id)
                _assign_tags_and_groups(
                    db, item.id, parsed, created_tag_names, created_group_names, user_id=user_id
                )
                result.created += 1
                result.preview.append(_outcome(parsed, "created"))
            continue

        # mode == "upsert": rows sharing a (card_id, condition_label,
        # purchase_source) key within this batch target the same row - the
        # first claims/creates it, later ones update it.
        key = _upsert_key(parsed)
        if key in batch_upsert_targets:
            existing_item_id = batch_upsert_targets[key]
            if dry_run:
                result.preview.append(_outcome(parsed, "would_update"))
            else:
                item = db.get(CollectionItem, existing_item_id)
                assert item is not None
                _apply_row_to_item(item, parsed)
                _assign_tags_and_groups(
                    db, item.id, parsed, created_tag_names, created_group_names, user_id=user_id
                )
                result.updated += 1
                result.preview.append(_outcome(parsed, "updated"))
            continue

        existing_item = _find_existing_item(db, parsed, user_id=user_id)
        if existing_item is not None:
            if dry_run:
                batch_upsert_targets[key] = existing_item.id
                result.preview.append(_outcome(parsed, "would_update"))
            else:
                _apply_row_to_item(existing_item, parsed)
                _assign_tags_and_groups(
                    db,
                    existing_item.id,
                    parsed,
                    created_tag_names,
                    created_group_names,
                    user_id=user_id,
                )
                result.updated += 1
                batch_upsert_targets[key] = existing_item.id
                result.preview.append(_outcome(parsed, "updated"))
        else:
            if dry_run:
                batch_upsert_targets[key] = None
                result.preview.append(_outcome(parsed, "would_create"))
            else:
                item = _create_item(db, parsed, user_id=user_id)
                _assign_tags_and_groups(
                    db, item.id, parsed, created_tag_names, created_group_names, user_id=user_id
                )
                result.created += 1
                batch_upsert_targets[key] = item.id
                result.preview.append(_outcome(parsed, "created"))

    if dry_run:
        existing_tag_names: set[str] = set()
        existing_group_names: set[str] = set()
        if all_tag_names:
            existing_tag_names = {
                t.name
                for t in db.scalars(
                    select(CollectorTag).where(
                        CollectorTag.name.in_(all_tag_names), CollectorTag.user_id == user_id
                    )
                ).all()
            }
        if all_group_names:
            existing_group_names = {
                g.name
                for g in db.scalars(
                    select(CollectorGroup).where(
                        CollectorGroup.name.in_(all_group_names), CollectorGroup.user_id == user_id
                    )
                ).all()
            }
        result.tags_created = sorted(all_tag_names - existing_tag_names)
        result.groups_created = sorted(all_group_names - existing_group_names)
        db.rollback()
    else:
        result.tags_created = sorted(created_tag_names)
        result.groups_created = sorted(created_group_names)
        db.commit()

    return result
