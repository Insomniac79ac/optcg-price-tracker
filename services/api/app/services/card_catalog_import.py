"""Bulk import/normalize canonical `cards` rows from a CSV - see POST
/admin/cards/import.csv and `python -m app.import_cards_csv`. Only touches
the `cards` table itself: no scraping, no source-mapping writes, no price
data. Mirrors app.services.collection_csv's parse-then-apply shape (per-row
ParsedRow/RowError, a preview of what would happen, dry_run leaving the DB
untouched) - a generic reusable "row diff preview" concept, not the same
domain, so duplicated here rather than imported.

Row identity and matching
--------------------------
The `cards` table's real identity is the 5-column
(card_code, set_code, rarity, variant, language) unique constraint (see
app.models.card.Card). A CSV row only ever *requires* card_code + name_en,
so this module has to decide which existing row (if any) a sparse row
refers to:

- set_code is always resolved (inferred from card_code if the column is
  blank - see _infer_set_code) and always used as an exact match filter.
- language always resolves to a concrete value (defaults to "jp") and is
  always used as an exact match filter.
- variant is nullable in the DB, and "not given in this row" is treated as
  meaning exactly that: filtered as IS NULL, not left unfiltered - a row
  with no variant column should not silently match some other row's
  parallel/alt-art printing.
- rarity is NOT NULL in the DB, so "not given in this row" can never mean
  "matches a null rarity" - there's no such row. It's instead left
  unfiltered (matches any rarity), and if more than one existing row
  matches once every other field is applied, that's reported as a row
  error asking for an explicit rarity rather than silently guessing.

On create, a still-unresolved rarity defaults to "unknown" (the DB column
is NOT NULL) - a deliberately visible placeholder, not a guess, that
card_audit's missing/invalid checks and a follow-up import can find and
fix.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card

REQUIRED_IMPORT_COLUMNS = ("card_code", "name_en")

DEFAULT_LANGUAGE = "jp"
DEFAULT_RARITY = "unknown"

# Raw (lowercased/stripped) CSV value -> canonical stored value.
LANGUAGE_SYNONYMS = {
    "japanese": "jp",
    "jp": "jp",
    "japan": "jp",
    "english": "en",
    "en": "en",
}

VARIANT_SYNONYMS = {
    "base": "base",
    "normal": "base",
    "parallel": "parallel",
    "para": "parallel",
    "alt": "alt_art",
    "alt_art": "alt_art",
    "alternate": "alt_art",
    "manga": "manga",
    "sp": "sp",
    "special": "sp",
    "leader": "leader",
    "leader_parallel": "leader_parallel",
}

# Fields this importer will create/update on a Card row, beyond the identity
# columns (card_code/set_code/rarity/variant/language) handled separately by
# _resolve_identity/_find_existing_card. Order matches the spec's CSV column
# list (and therefore the export column order too).
METADATA_STRING_FIELDS = (
    "name_en",
    "name_jp",
    "image_url",
    "artist",
    "character",
    "color",
    "card_type",
    "attribute",
    "effect_text",
    "trigger_text",
    "notes",
)
METADATA_INT_FIELDS = ("cost", "power", "counter")
METADATA_DATE_FIELDS = ("release_date",)

ALL_ROW_FIELDS = (
    "set_code",
    "rarity",
    "variant",
    "language",
    *METADATA_STRING_FIELDS,
    *METADATA_DATE_FIELDS,
    *METADATA_INT_FIELDS,
)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _infer_set_code(card_code: str) -> str:
    """OP01-001 -> OP01, EB01-001 -> EB01, ST01-001 -> ST01, P-001 -> P -
    the set code is always the text before the first hyphen."""
    return card_code.split("-", 1)[0]


def _normalize_language(raw: str) -> str | None:
    canonical = LANGUAGE_SYNONYMS.get(raw.strip().lower())
    return canonical


def _normalize_variant(raw: str) -> str:
    """Known synonyms map to their canonical form; anything else passes
    through unchanged (lowercased) - variant is an open-ended print/edition
    label, not a closed enum, so an unrecognized value is stored as-is and
    left for card_audit's invalid_variant check to surface, not rejected
    here."""
    lowered = raw.strip().lower()
    return VARIANT_SYNONYMS.get(lowered, lowered)


@dataclass
class ParsedRow:
    row_number: int
    card_code: str
    set_code: str
    rarity: str | None
    variant: str | None
    language: str
    fields: dict[str, str | int | date | None]


@dataclass
class RowError:
    row_number: int
    card_code: str | None
    error: str

    def to_dict(self) -> dict:
        return {"row_number": self.row_number, "card_code": self.card_code, "error": self.error}


@dataclass
class FieldChange:
    old: str | int | None
    new: str | int | None

    def to_dict(self) -> dict:
        return {"old": self.old, "new": self.new}


@dataclass
class RowOutcome:
    row_number: int
    card_code: str
    action: str
    changes: dict[str, FieldChange] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "card_code": self.card_code,
            "action": self.action,
            "changes": {k: v.to_dict() for k, v in self.changes.items()},
        }


@dataclass
class ImportResult:
    dry_run: bool
    overwrite: bool
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)
    preview: list[RowOutcome] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "overwrite": self.overwrite,
            "summary": {
                "total_rows": self.total_rows,
                "valid_rows": self.valid_rows,
                "error_rows": self.error_rows,
                "created": self.created,
                "updated": self.updated,
                "skipped": self.skipped,
            },
            "errors": [e.to_dict() for e in self.errors],
            "preview": [p.to_dict() for p in self.preview],
        }


def _parse_row(row_number: int, row: dict[str, str]) -> tuple[ParsedRow | None, RowError | None]:
    card_code = _clean(row.get("card_code"))
    if card_code is None:
        return None, RowError(row_number, None, "card_code is required")

    name_en = _clean(row.get("name_en"))
    if name_en is None:
        return None, RowError(row_number, card_code, "name_en is required")

    set_code = _clean(row.get("set_code")) or _infer_set_code(card_code)

    rarity = _clean(row.get("rarity"))

    variant_raw = _clean(row.get("variant"))
    variant = _normalize_variant(variant_raw) if variant_raw is not None else None

    language_raw = _clean(row.get("language")) or DEFAULT_LANGUAGE
    language = _normalize_language(language_raw)
    if language is None:
        return None, RowError(
            row_number, card_code, f"Invalid language '{language_raw}'. Must be jp or en (or a recognized synonym)."
        )

    fields: dict[str, str | int | date | None] = {"name_en": name_en}
    for name in METADATA_STRING_FIELDS:
        if name == "name_en":
            continue
        fields[name] = _clean(row.get(name))

    for name in METADATA_INT_FIELDS:
        raw = _clean(row.get(name))
        if raw is None:
            fields[name] = None
            continue
        try:
            fields[name] = int(raw)
        except ValueError:
            return None, RowError(row_number, card_code, f"{name} must be a valid integer")

    for name in METADATA_DATE_FIELDS:
        raw = _clean(row.get(name))
        if raw is None:
            fields[name] = None
            continue
        try:
            fields[name] = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None, RowError(row_number, card_code, f"{name} must be in YYYY-MM-DD format")

    return (
        ParsedRow(
            row_number=row_number,
            card_code=card_code,
            set_code=set_code,
            rarity=rarity,
            variant=variant,
            language=language,
            fields=fields,
        ),
        None,
    )


def _find_existing_card(db: Session, parsed: ParsedRow) -> tuple[Card | None, str | None]:
    """Returns (card, error_message). error_message is set (and card is
    None) when the row is ambiguous - more than one existing card matches
    once the fields actually given in this row are applied as filters."""
    filters = [
        Card.card_code == parsed.card_code,
        Card.set_code == parsed.set_code,
        Card.language == parsed.language,
    ]
    if parsed.rarity is not None:
        filters.append(Card.rarity == parsed.rarity)
    if parsed.variant is not None:
        filters.append(Card.variant == parsed.variant)
    else:
        filters.append(Card.variant.is_(None))

    matches = db.scalars(select(Card).where(*filters)).all()
    if len(matches) == 0:
        return None, None
    if len(matches) == 1:
        return matches[0], None
    return None, (
        f"{len(matches)} existing cards match card_code '{parsed.card_code}' "
        f"(set_code={parsed.set_code}, language={parsed.language}); "
        "specify rarity to disambiguate"
    )


def _identity_changes(card: Card | None, parsed: ParsedRow) -> dict[str, FieldChange]:
    changes: dict[str, FieldChange] = {}
    existing_set_code = card.set_code if card is not None else None
    if parsed.set_code != existing_set_code:
        changes["set_code"] = FieldChange(existing_set_code, parsed.set_code)

    existing_language = card.language if card is not None else None
    if parsed.language != existing_language:
        changes["language"] = FieldChange(existing_language, parsed.language)

    existing_variant = card.variant if card is not None else None
    if parsed.variant != existing_variant:
        changes["variant"] = FieldChange(existing_variant, parsed.variant)

    existing_rarity = card.rarity if card is not None else None
    new_rarity = parsed.rarity if parsed.rarity is not None else (existing_rarity or DEFAULT_RARITY)
    if new_rarity != existing_rarity:
        changes["rarity"] = FieldChange(existing_rarity, new_rarity)

    return changes


def _resolve_field(
    existing_value: str | int | date | None,
    new_value: str | int | date | None,
    *,
    overwrite: bool,
) -> tuple[str | int | date | None, bool]:
    """Returns (final_value, changed). A blank/absent CSV value never
    touches an existing value. A non-blank CSV value only overwrites an
    already-non-empty existing value when overwrite=True."""
    if new_value is None:
        return existing_value, False
    is_existing_empty = existing_value is None or (
        isinstance(existing_value, str) and existing_value.strip() == ""
    )
    if not is_existing_empty and not overwrite:
        return existing_value, False
    if existing_value == new_value:
        return existing_value, False
    return new_value, True


def _metadata_changes(
    card: Card | None, parsed: ParsedRow, *, overwrite: bool
) -> dict[str, FieldChange]:
    changes: dict[str, FieldChange] = {}
    for name in (*METADATA_STRING_FIELDS, *METADATA_INT_FIELDS, *METADATA_DATE_FIELDS):
        existing_value = getattr(card, name) if card is not None else None
        new_value = parsed.fields.get(name)
        final_value, changed = _resolve_field(existing_value, new_value, overwrite=overwrite)
        if changed:
            changes[name] = FieldChange(existing_value, final_value)
    return changes


def _apply_changes(card: Card, changes: dict[str, FieldChange]) -> None:
    for name, change in changes.items():
        setattr(card, name, change.new)


def import_cards_csv(
    db: Session, csv_text: str, *, dry_run: bool = True, overwrite: bool = False
) -> ImportResult:
    """Parses and (optionally) applies a canonical card catalog CSV import.
    Never touches source_card_mappings/price_observations - only the
    `cards` table itself. Safe to call repeatedly; dry_run leaves the DB
    untouched (including id assignment - no rows are even flushed)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    missing_columns = [c for c in REQUIRED_IMPORT_COLUMNS if c not in fieldnames]
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {missing_columns}")

    result = ImportResult(dry_run=dry_run, overwrite=overwrite)

    for row_number, row in enumerate(reader, start=2):
        result.total_rows += 1
        parsed, row_error = _parse_row(row_number, row)
        if row_error is not None:
            result.error_rows += 1
            result.errors.append(row_error)
            continue

        card, match_error = _find_existing_card(db, parsed)
        if match_error is not None:
            result.error_rows += 1
            result.errors.append(RowError(row_number, parsed.card_code, match_error))
            continue

        result.valid_rows += 1

        identity_changes = _identity_changes(card, parsed)
        metadata_changes = _metadata_changes(card, parsed, overwrite=overwrite)
        changes = {**identity_changes, **metadata_changes}

        if card is None:
            action_verb = "create"
        elif changes:
            action_verb = "update"
        else:
            action_verb = "skip"

        if action_verb == "create":
            result.created += 1
        elif action_verb == "update":
            result.updated += 1
        else:
            result.skipped += 1

        action = f"would_{action_verb}" if dry_run else action_verb
        result.preview.append(RowOutcome(row_number=row_number, card_code=parsed.card_code, action=action, changes=changes))

        if dry_run:
            continue

        if card is None:
            new_card = Card(
                card_code=parsed.card_code,
                set_code=parsed.set_code,
                rarity=parsed.rarity or DEFAULT_RARITY,
                variant=parsed.variant,
                language=parsed.language,
            )
            _apply_changes(new_card, metadata_changes)
            db.add(new_card)
            db.flush()
        elif changes:
            _apply_changes(card, changes)
            db.flush()

    if not dry_run:
        db.commit()

    return result


# --- Export ------------------------------------------------------------

EXPORT_COLUMNS = (
    "id",
    "card_code",
    "name_en",
    "name_jp",
    "set_code",
    "rarity",
    "variant",
    "language",
    "image_url",
    "release_date",
    "artist",
    "character",
    "color",
    "card_type",
    "cost",
    "power",
    "counter",
    "attribute",
    "effect_text",
    "trigger_text",
    "notes",
    "created_at",
    "updated_at",
)


def _blank(value: str | int | date | datetime | None) -> str:
    return "" if value is None else str(value)


class _RowSink:
    """Minimal file-like object for csv.writer - see
    app.services.collection_csv._RowSink (same trick, duplicated rather than
    imported since this module has no other dependency on that one)."""

    def __init__(self) -> None:
        self.value = ""

    def write(self, s: str) -> int:
        self.value = s
        return len(s)


def iter_cards_csv_rows(db: Session) -> Iterator[str]:
    """Yields the full canonical cards table as CSV text chunks - a header
    chunk, then one chunk per row."""
    cards = db.scalars(select(Card).order_by(Card.id)).all()

    sink = _RowSink()
    writer = csv.DictWriter(sink, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    yield sink.value

    for card in cards:
        writer.writerow(
            {
                "id": card.id,
                "card_code": card.card_code,
                "name_en": _blank(card.name_en),
                "name_jp": _blank(card.name_jp),
                "set_code": card.set_code,
                "rarity": card.rarity,
                "variant": _blank(card.variant),
                "language": card.language,
                "image_url": _blank(card.image_url),
                "release_date": card.release_date.isoformat() if card.release_date else "",
                "artist": _blank(card.artist),
                "character": _blank(card.character),
                "color": _blank(card.color),
                "card_type": _blank(card.card_type),
                "cost": _blank(card.cost),
                "power": _blank(card.power),
                "counter": _blank(card.counter),
                "attribute": _blank(card.attribute),
                "effect_text": _blank(card.effect_text),
                "trigger_text": _blank(card.trigger_text),
                "notes": _blank(card.notes),
                "created_at": card.created_at.isoformat() if card.created_at else "",
                "updated_at": card.updated_at.isoformat() if card.updated_at else "",
            }
        )
        yield sink.value


def export_cards_csv(db: Session) -> str:
    """Whole-string convenience wrapper around iter_cards_csv_rows - used by
    the export CLI and tests; the HTTP export endpoint streams the generator
    directly instead."""
    return "".join(iter_cards_csv_rows(db))


def export_filename(today: date | None = None) -> str:
    day = today or datetime.now(timezone.utc).date()
    return f"cards_export_{day.strftime('%Y%m%d')}.csv"
