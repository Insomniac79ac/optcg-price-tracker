"""Dry-run CSV validation for the larger bulk-import flows - see POST
/admin/import-validation/{import_type} and docs/operations.md's "CSV import
validation workflow". This module is deliberately upload-and-report only:
validate_import_csv() never adds/flushes/commits a row to the database, no
matter how clean the file is - the only DB access it performs is read-only
lookups needed to say what a real import *would* do (would_create/
would_update/would_skip) and to surface warnings (duplicate rows, low-
confidence matches, likely-duplicate cards, ...).

Column requirements per import_type are the single source of truth for both
this module and app.services.import_templates (which only describes them
for a human/CSV download - see that module's docstring). Row-level parsing
here is intentionally a separate, finer-grained implementation from the
actual importers (app.services.card_catalog_import/collection_csv/
wishlist_csv) rather than a wrapper around them: those importers report one
error per row and stop, where this module reports every (field, code,
message) problem it can find on a row, plus warnings the importers don't
have a vocabulary for at all (normalized-value notices, likely-duplicate
scoring, match-confidence estimates, ...). Reusing this module's read-only
lookups can never desync from what a real import does, since both ultimately
query the same tables the same way (card_code (+set_code/rarity/variant/
language) identity for cards, (source_id, source_url) for mappings, source_url
for candidates, (card_id, condition_label, purchase_source) for collection
items, (card_id, preferred_condition, preferred_source) for wishlist items).

No AI/LLM anywhere in this module - every check is a fixed rule or reuses an
existing deterministic scorer (app.services.card_matching,
app.services.card_identity_merge, app.services.source_mapping_confidence).
Never scrapes anything; never bypasses website protections; this only ever
reads rows a human already put in a CSV file.
"""

from __future__ import annotations

import csv
import difflib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Card,
    CollectionItem,
    Source,
    SourceCardMapping,
)
from app.models.collection_item import COLLECTION_ITEM_STATUSES
from app.models.snkrdunk_candidate import MATCH_STATUSES, SnkrdunkCandidate
from app.models.source_card_mapping import REVIEW_STATUSES
from app.models.wishlist_item import WISHLIST_PRIORITIES, WISHLIST_STATUSES
from app.services.card_catalog_import import (
    DEFAULT_LANGUAGE,
    DEFAULT_RARITY,
    LANGUAGE_SYNONYMS,
    METADATA_DATE_FIELDS,
    METADATA_INT_FIELDS,
    METADATA_STRING_FIELDS,
    VARIANT_SYNONYMS,
)
from app.services.card_identity_merge import calculate_duplicate_score, duplicate_confidence_label
from app.services.card_matching import (
    AMBIGUOUS_TIE_MARGIN,
    SUGGESTED_SCORE_THRESHOLD,
    calculate_candidate_match,
    extract_card_code,
    normalize_card_code,
)
from app.services.collection_csv import REQUIRED_IMPORT_COLUMNS as _COLLECTION_REQUIRED_COLUMNS
from app.services.wishlist import find_conflicting_wishlist_item
from app.services.wishlist_csv import REQUIRED_IMPORT_COLUMNS as _WISHLIST_REQUIRED_COLUMNS
from app.services.source_mapping_confidence import evaluate_source_mapping

IMPORT_TYPES = (
    "card_catalog",
    "source_mappings",
    "snkrdunk_candidates",
    "collection",
    "wishlist",
)

DEFAULT_MAX_PREVIEW_ROWS = 100

# Cards whose duplicate score (against another row sharing the same
# card_code) is at least this good is worth flagging - matches
# app.services.card_identity_merge's own "likely_duplicate"/"exact_duplicate"
# labels, not a separately invented threshold.
_DUPLICATE_WARNING_LABELS = ("exact_duplicate", "likely_duplicate")

_DEFAULT_COLLECTION_STATUS = "hold"
_DEFAULT_WISHLIST_PRIORITY = "medium"
_DEFAULT_WISHLIST_STATUS = "watching"


@dataclass
class ImportTypeSpec:
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...]


# Collection/wishlist columns intentionally mirror
# app.services.collection_csv/wishlist_csv's own import column handling (see
# their _parse_row) rather than the two modules' EXPORT_COLUMNS, which
# additionally include computed/derived columns (tags, groups, grading_*)
# that an import never reads.
TYPE_SPECS: dict[str, ImportTypeSpec] = {
    "card_catalog": ImportTypeSpec(
        required_columns=("card_code", "name_en"),
        optional_columns=(
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
        ),
    ),
    "source_mappings": ImportTypeSpec(
        required_columns=("source_name", "source_url", "card_code"),
        optional_columns=(
            "source_card_id",
            "source_card_code",
            "review_status",
            "is_active",
            "manual_verified",
            "review_notes",
        ),
    ),
    "snkrdunk_candidates": ImportTypeSpec(
        required_columns=("source_url", "title"),
        optional_columns=(
            "price_jpy",
            "image_url",
            "listing_count",
            "condition_label",
            "raw_text",
            "normalized_title",
            "detected_card_code",
            "set_code",
            "rarity",
            "variant",
            "match_status",
        ),
    ),
    "collection": ImportTypeSpec(
        required_columns=_COLLECTION_REQUIRED_COLUMNS,
        optional_columns=(
            "condition_label",
            "purchase_price_jpy",
            "purchase_date",
            "purchase_source",
            "target_sell_price_jpy",
            "status",
            "notes",
            "tags",
            "groups",
        ),
    ),
    "wishlist": ImportTypeSpec(
        required_columns=_WISHLIST_REQUIRED_COLUMNS,
        optional_columns=(
            "priority",
            "status",
            "target_buy_price_jpy",
            "max_buy_price_jpy",
            "preferred_condition",
            "preferred_source",
            "desired_quantity",
            "acquired_quantity",
            "notes",
        ),
    ),
}


@dataclass
class RowIssue:
    row_number: int
    field: str | None
    value: Any
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "field": self.field,
            "value": self.value,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class PreviewRow:
    row_number: int
    action: str
    normalized_values: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "action": self.action,
            "normalized_values": self.normalized_values,
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass
class ValidationSummary:
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    warning_rows: int = 0
    duplicate_rows: int = 0
    would_create: int = 0
    would_update: int = 0
    would_skip: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "error_rows": self.error_rows,
            "warning_rows": self.warning_rows,
            "duplicate_rows": self.duplicate_rows,
            "would_create": self.would_create,
            "would_update": self.would_update,
            "would_skip": self.would_skip,
        }


@dataclass
class ColumnsInfo:
    required_columns: list[str]
    optional_columns: list[str]
    received_columns: list[str]
    missing_required_columns: list[str]
    unknown_columns: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "required_columns": self.required_columns,
            "optional_columns": self.optional_columns,
            "received_columns": self.received_columns,
            "missing_required_columns": self.missing_required_columns,
            "unknown_columns": self.unknown_columns,
        }


@dataclass
class ValidationResult:
    import_type: str
    valid: bool
    summary: ValidationSummary
    columns: ColumnsInfo
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)
    preview: list[PreviewRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_type": self.import_type,
            "valid": self.valid,
            "summary": self.summary.to_dict(),
            "columns": self.columns.to_dict(),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "preview": [p.to_dict() for p in self.preview],
        }


@dataclass
class RowOutcome:
    errors: list[RowIssue]
    warnings: list[RowIssue]
    action: str
    normalized_values: dict[str, Any]
    dedupe_key: Any = None


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _infer_set_code(card_code: str) -> str:
    return card_code.split("-", 1)[0]


def _normalize_language(raw: str) -> str | None:
    return LANGUAGE_SYNONYMS.get(raw.strip().lower())


def _normalize_variant(raw: str) -> str:
    lowered = raw.strip().lower()
    return VARIANT_SYNONYMS.get(lowered, lowered)


def _parse_bool(raw: str) -> bool | None:
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes", "y"):
        return True
    if lowered in ("false", "0", "no", "n"):
        return False
    return None


_CARD_CODE_FORMAT_RE = re.compile(r"^[A-Za-z]{1,5}\d{0,2}-[A-Za-z0-9]{1,4}$")


def _is_valid_card_code_format(card_code: str) -> bool:
    """OP01-001, ST01-001, EB01-001, P-001, P-EX01, ... all match; anything
    with no hyphen at all (or an otherwise unrecognizable shape) doesn't -
    see the spec note this implements: "error if invalid card_code format
    unless import type is promo P-xxx and can be inferred". A bare "P-001"
    already satisfies this same regex, so no separate promo carve-out is
    needed - it's just a set_code with no trailing digits."""
    return bool(_CARD_CODE_FORMAT_RE.match(card_code))


# --- card_catalog --------------------------------------------------------


def _card_catalog_changes(existing: Card, normalized: dict[str, Any]) -> bool:
    """Approximates whether a real import (app.services.card_catalog_import)
    would touch `existing` - a lightweight comparison for preview purposes
    only, not a reimplementation of that importer's overwrite/keep-blank
    field_strategy semantics."""
    for name in METADATA_STRING_FIELDS:
        if name in normalized and normalized[name] != (getattr(existing, name) or None):
            return True
    for name in METADATA_INT_FIELDS:
        if name in normalized and normalized[name] != getattr(existing, name):
            return True
    for name in METADATA_DATE_FIELDS:
        if name in normalized:
            existing_value = getattr(existing, name)
            existing_str = existing_value.isoformat() if existing_value else None
            if normalized[name] != existing_str:
                return True
    return False


def _validate_card_catalog_row(
    db: Session, row_number: int, row: dict[str, str], *, ctx: dict, user_id: int | None = None
) -> RowOutcome:
    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []
    normalized: dict[str, Any] = {}

    card_code = _clean(row.get("card_code"))
    if card_code is None:
        errors.append(
            RowIssue(row_number, "card_code", row.get("card_code"), "required_field_missing", "card_code is required")
        )
    name_en = _clean(row.get("name_en"))
    if name_en is None:
        errors.append(
            RowIssue(row_number, "name_en", row.get("name_en"), "required_field_missing", "name_en is required")
        )

    if card_code is None or name_en is None:
        return RowOutcome(errors, warnings, "invalid", normalized, None)

    normalized["card_code"] = card_code
    normalized["name_en"] = name_en

    if not _is_valid_card_code_format(card_code):
        errors.append(
            RowIssue(
                row_number,
                "card_code",
                card_code,
                "invalid_card_code_format",
                f"card_code '{card_code}' does not look like a valid card code (expected e.g. OP01-001 or P-001)",
            )
        )

    inferred_set_code = _infer_set_code(card_code)
    set_code_raw = _clean(row.get("set_code"))
    if set_code_raw is None:
        set_code = inferred_set_code
        warnings.append(
            RowIssue(
                row_number, "set_code", None, "inferred_value", f"set_code inferred as '{set_code}' from card_code"
            )
        )
    else:
        set_code = set_code_raw
        if set_code.upper() != inferred_set_code.upper():
            warnings.append(
                RowIssue(
                    row_number,
                    "set_code",
                    set_code_raw,
                    "set_code_mismatch",
                    f"set_code '{set_code_raw}' does not match the set code inferred from card_code ('{inferred_set_code}')",
                )
            )
    normalized["set_code"] = set_code

    rarity = _clean(row.get("rarity"))
    if rarity is not None:
        normalized["rarity"] = rarity

    variant_raw = _clean(row.get("variant"))
    variant: str | None = None
    if variant_raw is not None:
        variant = _normalize_variant(variant_raw)
        if variant != variant_raw.strip().lower():
            warnings.append(
                RowIssue(
                    row_number,
                    "variant",
                    variant_raw,
                    "normalized_value",
                    f"variant will be normalized to '{variant}'",
                )
            )
        normalized["variant"] = variant

    language_raw = _clean(row.get("language")) or DEFAULT_LANGUAGE
    language = _normalize_language(language_raw)
    if language is None:
        errors.append(
            RowIssue(
                row_number,
                "language",
                language_raw,
                "invalid_value",
                f"Invalid language '{language_raw}'. Must be jp or en (or a recognized synonym).",
            )
        )
    else:
        if language != language_raw.strip().lower():
            warnings.append(
                RowIssue(
                    row_number,
                    "language",
                    language_raw,
                    "normalized_value",
                    f"language will be normalized to '{language}'",
                )
            )
        normalized["language"] = language

    for name in METADATA_INT_FIELDS:
        raw = _clean(row.get(name))
        if raw is None:
            continue
        try:
            normalized[name] = int(raw)
        except ValueError:
            errors.append(RowIssue(row_number, name, raw, "invalid_number", f"{name} must be a valid integer"))

    for name in METADATA_DATE_FIELDS:
        raw = _clean(row.get(name))
        if raw is None:
            continue
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            normalized[name] = raw
        except ValueError:
            errors.append(RowIssue(row_number, name, raw, "invalid_date", f"{name} must be in YYYY-MM-DD format"))

    for name in METADATA_STRING_FIELDS:
        if name == "name_en":
            continue
        val = _clean(row.get(name))
        if val is not None:
            normalized[name] = val

    dedupe_key = (card_code.upper(), set_code.upper(), variant or "base", language or language_raw)

    if errors:
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    filters = [Card.card_code == card_code, Card.set_code == set_code, Card.language == language]
    if rarity is not None:
        filters.append(Card.rarity == rarity)
    if variant is not None:
        filters.append(Card.variant == variant)
    else:
        filters.append(Card.variant.is_(None))
    matches = db.scalars(select(Card).where(*filters)).all()

    if len(matches) > 1:
        errors.append(
            RowIssue(
                row_number,
                None,
                None,
                "ambiguous_match",
                f"{len(matches)} existing cards match card_code '{card_code}'; specify rarity to disambiguate",
            )
        )
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    existing = matches[0] if matches else None

    siblings = db.scalars(
        select(Card).where(Card.card_code == card_code, Card.id != (existing.id if existing else -1))
    ).all()
    differing_siblings = [s for s in siblings if (s.variant or None) != variant or s.language != language]
    if differing_siblings:
        warnings.append(
            RowIssue(
                row_number,
                None,
                None,
                "similar_existing_card",
                f"{len(differing_siblings)} existing card(s) share card_code '{card_code}' with a different variant/language",
            )
        )

    if existing is None and siblings:
        transient = Card(
            card_code=card_code,
            set_code=set_code,
            rarity=rarity or DEFAULT_RARITY,
            variant=variant,
            language=language,
            name_en=name_en,
            name_jp=normalized.get("name_jp"),
            character=normalized.get("character"),
            card_type=normalized.get("card_type"),
            color=normalized.get("color"),
        )
        best_score = -1
        best_sibling: Card | None = None
        for sibling in siblings:
            result = calculate_duplicate_score(transient, sibling)
            if result.score > best_score:
                best_score = result.score
                best_sibling = sibling
        if best_sibling is not None and duplicate_confidence_label(best_score) in _DUPLICATE_WARNING_LABELS:
            warnings.append(
                RowIssue(
                    row_number,
                    None,
                    None,
                    "possible_duplicate",
                    f"Looks like a possible duplicate of existing card id={best_sibling.id} "
                    f"({best_sibling.card_code}, score={best_score})",
                )
            )

    if existing is None:
        action = "would_create"
    elif _card_catalog_changes(existing, normalized):
        action = "would_update"
    else:
        action = "would_skip"

    return RowOutcome(errors, warnings, action, normalized, dedupe_key)


# --- source_mappings -------------------------------------------------------


def _validate_source_mappings_row(
    db: Session, row_number: int, row: dict[str, str], *, ctx: dict, user_id: int | None = None
) -> RowOutcome:
    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []
    normalized: dict[str, Any] = {}

    source_name = _clean(row.get("source_name"))
    source_url = _clean(row.get("source_url"))
    card_code = _clean(row.get("card_code"))

    if source_name is None:
        errors.append(
            RowIssue(row_number, "source_name", row.get("source_name"), "required_field_missing", "source_name is required")
        )
    if source_url is None:
        errors.append(
            RowIssue(row_number, "source_url", row.get("source_url"), "required_field_missing", "source_url is required")
        )
    if card_code is None:
        errors.append(
            RowIssue(row_number, "card_code", row.get("card_code"), "required_field_missing", "card_code is required")
        )

    if source_name is None or source_url is None or card_code is None:
        return RowOutcome(errors, warnings, "invalid", normalized, None)

    normalized.update(source_name=source_name, source_url=source_url, card_code=card_code)

    source = ctx["sources_by_name"].get(source_name.strip().lower())
    if source is None:
        errors.append(
            RowIssue(row_number, "source_name", source_name, "source_not_found", f"Source '{source_name}' does not exist")
        )

    card = db.scalars(select(Card).where(Card.card_code == card_code, Card.is_active.is_(True))).first()
    if card is None:
        errors.append(
            RowIssue(row_number, "card_code", card_code, "card_not_found", f"No active card found for card_code '{card_code}'")
        )
        close = difflib.get_close_matches(card_code, ctx["active_card_codes"], n=1, cutoff=0.6)
        if close:
            warnings.append(
                RowIssue(
                    row_number,
                    "card_code",
                    card_code,
                    "close_match_available",
                    f"No exact match for card_code '{card_code}', but '{close[0]}' is a close match",
                )
            )

    review_status = _clean(row.get("review_status")) or "needs_review"
    if review_status not in REVIEW_STATUSES:
        errors.append(
            RowIssue(
                row_number,
                "review_status",
                review_status,
                "invalid_value",
                f"review_status must be one of {list(REVIEW_STATUSES)}",
            )
        )
    normalized["review_status"] = review_status

    for bool_field in ("is_active", "manual_verified"):
        raw = _clean(row.get(bool_field))
        if raw is None:
            continue
        parsed = _parse_bool(raw)
        if parsed is None:
            errors.append(
                RowIssue(row_number, bool_field, raw, "invalid_boolean", f"{bool_field} must be a boolean (true/false)")
            )
        else:
            normalized[bool_field] = parsed

    review_notes = _clean(row.get("review_notes"))
    if review_notes is not None:
        normalized["review_notes"] = review_notes

    dedupe_key = (source_name.strip().lower(), source_url.strip().lower())

    if errors:
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    existing_mapping = None
    if source is not None:
        existing_mapping = db.scalars(
            select(SourceCardMapping).where(
                SourceCardMapping.source_id == source.id, SourceCardMapping.source_url == source_url
            )
        ).first()
        if existing_mapping is not None:
            warnings.append(
                RowIssue(
                    row_number,
                    "source_url",
                    source_url,
                    "duplicate_source_url",
                    f"source_url already exists in source_card_mappings (mapping id={existing_mapping.id})",
                )
            )

    if source is not None and card is not None:
        transient = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=_clean(row.get("source_card_id")) or _clean(row.get("source_card_code")) or source_url,
            source_url=source_url,
        )
        item = evaluate_source_mapping(
            db, transient, card=card, source=source, latest_price_observed_at=None, is_duplicate=False
        )
        if item.match_confidence_label in ("low", "very_low"):
            warnings.append(
                RowIssue(
                    row_number,
                    None,
                    None,
                    "low_confidence_match",
                    f"Estimated match confidence is {item.match_confidence_label} ({item.match_confidence})",
                )
            )

    action = "would_update" if existing_mapping is not None else "would_create"
    return RowOutcome(errors, warnings, action, normalized, dedupe_key)


# --- snkrdunk_candidates ----------------------------------------------------


def _validate_snkrdunk_candidates_row(
    db: Session, row_number: int, row: dict[str, str], *, ctx: dict, user_id: int | None = None
) -> RowOutcome:
    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []
    normalized: dict[str, Any] = {}

    source_url = _clean(row.get("source_url"))
    title = _clean(row.get("title"))
    if source_url is None:
        errors.append(
            RowIssue(row_number, "source_url", row.get("source_url"), "required_field_missing", "source_url is required")
        )
    if title is None:
        errors.append(RowIssue(row_number, "title", row.get("title"), "required_field_missing", "title is required"))

    if source_url is None or title is None:
        return RowOutcome(errors, warnings, "invalid", normalized, None)

    normalized["source_url"] = source_url
    normalized["title"] = title

    raw_price = _clean(row.get("price_jpy"))
    if raw_price is not None:
        try:
            normalized["price_jpy"] = int(raw_price)
        except ValueError:
            errors.append(RowIssue(row_number, "price_jpy", raw_price, "invalid_number", "price_jpy must be a valid integer"))

    raw_listing_count = _clean(row.get("listing_count"))
    if raw_listing_count is not None:
        try:
            normalized["listing_count"] = int(raw_listing_count)
        except ValueError:
            errors.append(
                RowIssue(row_number, "listing_count", raw_listing_count, "invalid_number", "listing_count must be a valid integer")
            )

    match_status = _clean(row.get("match_status")) or "unmatched"
    if match_status not in MATCH_STATUSES:
        errors.append(
            RowIssue(row_number, "match_status", match_status, "invalid_value", f"match_status must be one of {list(MATCH_STATUSES)}")
        )
    normalized["match_status"] = match_status

    detected_card_code = _clean(row.get("detected_card_code")) or extract_card_code(title)
    detected_set_code = _clean(row.get("set_code"))
    detected_rarity = _clean(row.get("rarity"))
    detected_variant = _clean(row.get("variant"))
    normalized_title = _clean(row.get("normalized_title")) or title
    raw_text = _clean(row.get("raw_text"))

    for key, val in (
        ("detected_card_code", detected_card_code),
        ("set_code", detected_set_code),
        ("rarity", detected_rarity),
        ("variant", detected_variant),
        ("condition_label", _clean(row.get("condition_label"))),
        ("image_url", _clean(row.get("image_url"))),
    ):
        if val is not None:
            normalized[key] = val

    dedupe_key = source_url.strip().lower()
    already_exists = dedupe_key in ctx["existing_candidate_urls"]
    if already_exists:
        warnings.append(
            RowIssue(row_number, "source_url", source_url, "duplicate_source_url", "source_url already exists in snkrdunk_candidates")
        )

    if errors:
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    if detected_card_code:
        norm_code = normalize_card_code(detected_card_code)
        candidate_cards = ctx["cards_by_code"].get(norm_code, [])
        if not candidate_cards:
            warnings.append(
                RowIssue(
                    row_number,
                    None,
                    None,
                    "no_good_match",
                    f"No active card found for detected_card_code '{detected_card_code}'",
                )
            )
        else:
            transient = SimpleNamespace(
                title=title,
                normalized_title=normalized_title,
                raw_text=raw_text,
                detected_card_code=detected_card_code,
                detected_set_code=detected_set_code,
                detected_rarity=detected_rarity,
                detected_variant=detected_variant,
            )
            scored = sorted(
                (calculate_candidate_match(transient, c) for c in candidate_cards),
                key=lambda r: -r.score,
            )
            top = scored[0]
            ambiguous = (
                len(scored) > 1
                and (scored[0].score - scored[1].score) <= AMBIGUOUS_TIE_MARGIN
                and not top.exact_card_code_match
            )
            if ambiguous:
                warnings.append(
                    RowIssue(
                        row_number,
                        None,
                        None,
                        "ambiguous_match",
                        f"{len(scored)} cards tie closely for detected_card_code '{detected_card_code}'",
                    )
                )
            elif top.score < SUGGESTED_SCORE_THRESHOLD:
                warnings.append(
                    RowIssue(
                        row_number,
                        None,
                        None,
                        "low_confidence_match",
                        f"Best match confidence is {top.confidence_label} (score={top.score})",
                    )
                )
    else:
        warnings.append(
            RowIssue(row_number, None, None, "no_good_match", "No card code detected in title; cannot estimate a match")
        )

    action = "would_update" if already_exists else "would_create"
    return RowOutcome(errors, warnings, action, normalized, dedupe_key)


# --- collection -------------------------------------------------------------


def _validate_collection_row(
    db: Session, row_number: int, row: dict[str, str], *, ctx: dict, user_id: int | None = None
) -> RowOutcome:
    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []
    normalized: dict[str, Any] = {}

    card_code = _clean(row.get("card_code"))
    if card_code is None:
        errors.append(
            RowIssue(row_number, "card_code", row.get("card_code"), "required_field_missing", "card_code is required")
        )
    else:
        normalized["card_code"] = card_code

    card: Card | None = None
    if card_code is not None:
        matches = db.scalars(select(Card).where(Card.card_code == card_code, Card.is_active.is_(True))).all()
        if not matches:
            errors.append(
                RowIssue(row_number, "card_code", card_code, "card_not_found", f"No active card found for card_code '{card_code}'")
            )
        elif len(matches) > 1:
            errors.append(
                RowIssue(row_number, "card_code", card_code, "ambiguous_match", f"{len(matches)} cards match card_code '{card_code}'")
            )
        else:
            card = matches[0]

    quantity_raw = _clean(row.get("quantity"))
    quantity: int | None = None
    if quantity_raw is None:
        errors.append(RowIssue(row_number, "quantity", row.get("quantity"), "required_field_missing", "quantity is required"))
    else:
        try:
            quantity = int(quantity_raw)
            if quantity < 1:
                errors.append(RowIssue(row_number, "quantity", quantity_raw, "invalid_value", "quantity must be >= 1"))
                quantity = None
            else:
                normalized["quantity"] = quantity
        except ValueError:
            errors.append(RowIssue(row_number, "quantity", quantity_raw, "invalid_number", "quantity must be a valid integer"))

    purchase_price_raw = _clean(row.get("purchase_price_jpy"))
    if purchase_price_raw is not None:
        try:
            value = int(purchase_price_raw)
            if value < 0:
                errors.append(
                    RowIssue(row_number, "purchase_price_jpy", purchase_price_raw, "invalid_value", "purchase_price_jpy must be >= 0")
                )
            else:
                normalized["purchase_price_jpy"] = value
        except ValueError:
            errors.append(
                RowIssue(row_number, "purchase_price_jpy", purchase_price_raw, "invalid_number", "purchase_price_jpy must be a valid integer")
            )

    purchase_date_raw = _clean(row.get("purchase_date"))
    if purchase_date_raw is not None:
        try:
            datetime.strptime(purchase_date_raw, "%Y-%m-%d")
            normalized["purchase_date"] = purchase_date_raw
        except ValueError:
            errors.append(
                RowIssue(row_number, "purchase_date", purchase_date_raw, "invalid_date", "purchase_date must be in YYYY-MM-DD format")
            )

    status = _clean(row.get("status")) or _DEFAULT_COLLECTION_STATUS
    if status not in COLLECTION_ITEM_STATUSES:
        errors.append(
            RowIssue(row_number, "status", status, "invalid_value", f"status must be one of {list(COLLECTION_ITEM_STATUSES)}")
        )
    normalized["status"] = status

    condition_label = _clean(row.get("condition_label"))
    purchase_source = _clean(row.get("purchase_source"))
    if condition_label is not None:
        normalized["condition_label"] = condition_label
    if purchase_source is not None:
        normalized["purchase_source"] = purchase_source

    dedupe_key = (card_code, condition_label, purchase_source) if card_code else None

    if errors:
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    existing_item = None
    if user_id is not None and card is not None:
        filters = [CollectionItem.card_id == card.id, CollectionItem.user_id == user_id]
        filters.append(
            CollectionItem.condition_label.is_(None) if condition_label is None else CollectionItem.condition_label == condition_label
        )
        filters.append(
            CollectionItem.purchase_source.is_(None) if purchase_source is None else CollectionItem.purchase_source == purchase_source
        )
        existing_item = db.scalars(select(CollectionItem).where(*filters)).first()
        if existing_item is not None:
            warnings.append(
                RowIssue(
                    row_number,
                    None,
                    None,
                    "likely_duplicate",
                    f"An existing collection item (id={existing_item.id}) matches this card/condition/source",
                )
            )

    action = "would_update" if existing_item is not None else "would_create"
    return RowOutcome(errors, warnings, action, normalized, dedupe_key)


# --- wishlist ----------------------------------------------------------------


def _validate_wishlist_row(
    db: Session, row_number: int, row: dict[str, str], *, ctx: dict, user_id: int | None = None
) -> RowOutcome:
    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []
    normalized: dict[str, Any] = {}

    card_code = _clean(row.get("card_code"))
    if card_code is None:
        errors.append(
            RowIssue(row_number, "card_code", row.get("card_code"), "required_field_missing", "card_code is required")
        )
    else:
        normalized["card_code"] = card_code

    card: Card | None = None
    if card_code is not None:
        matches = db.scalars(select(Card).where(Card.card_code == card_code, Card.is_active.is_(True))).all()
        if not matches:
            errors.append(
                RowIssue(row_number, "card_code", card_code, "card_not_found", f"No active card found for card_code '{card_code}'")
            )
        elif len(matches) > 1:
            errors.append(
                RowIssue(row_number, "card_code", card_code, "ambiguous_match", f"{len(matches)} cards match card_code '{card_code}'")
            )
        else:
            card = matches[0]

    priority = _clean(row.get("priority")) or _DEFAULT_WISHLIST_PRIORITY
    if priority not in WISHLIST_PRIORITIES:
        errors.append(
            RowIssue(row_number, "priority", priority, "invalid_value", f"priority must be one of {list(WISHLIST_PRIORITIES)}")
        )
    normalized["priority"] = priority

    status = _clean(row.get("status")) or _DEFAULT_WISHLIST_STATUS
    if status not in WISHLIST_STATUSES:
        errors.append(
            RowIssue(row_number, "status", status, "invalid_value", f"status must be one of {list(WISHLIST_STATUSES)}")
        )
    normalized["status"] = status

    def _parse_nonneg_int(field_name: str) -> int | None:
        raw = _clean(row.get(field_name))
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            errors.append(RowIssue(row_number, field_name, raw, "invalid_number", f"{field_name} must be a valid integer"))
            return None
        if value < 0:
            errors.append(RowIssue(row_number, field_name, raw, "invalid_value", f"{field_name} must be >= 0"))
            return None
        normalized[field_name] = value
        return value

    target_buy = _parse_nonneg_int("target_buy_price_jpy")
    max_buy = _parse_nonneg_int("max_buy_price_jpy")
    if target_buy is not None and max_buy is not None and target_buy > max_buy:
        warnings.append(
            RowIssue(
                row_number,
                None,
                None,
                "target_exceeds_max",
                f"target_buy_price_jpy ({target_buy}) is greater than max_buy_price_jpy ({max_buy})",
            )
        )

    desired_quantity_raw = _clean(row.get("desired_quantity"))
    if desired_quantity_raw is not None:
        try:
            desired_quantity = int(desired_quantity_raw)
            if desired_quantity < 1:
                errors.append(RowIssue(row_number, "desired_quantity", desired_quantity_raw, "invalid_value", "desired_quantity must be >= 1"))
            else:
                normalized["desired_quantity"] = desired_quantity
        except ValueError:
            errors.append(
                RowIssue(row_number, "desired_quantity", desired_quantity_raw, "invalid_number", "desired_quantity must be a valid integer")
            )

    preferred_condition = _clean(row.get("preferred_condition"))
    preferred_source = _clean(row.get("preferred_source"))
    if preferred_condition is not None:
        normalized["preferred_condition"] = preferred_condition
    if preferred_source is not None:
        normalized["preferred_source"] = preferred_source

    dedupe_key = (card_code, preferred_condition, preferred_source) if card_code else None

    if errors:
        return RowOutcome(errors, warnings, "invalid", normalized, dedupe_key)

    if card is not None:
        owned_filters = [CollectionItem.card_id == card.id]
        if user_id is not None:
            owned_filters.append(CollectionItem.user_id == user_id)
        owned = db.scalar(select(func.count()).select_from(CollectionItem).where(*owned_filters)) or 0
        if owned > 0:
            warnings.append(
                RowIssue(row_number, None, None, "already_owned", f"{owned} collection item(s) already exist for this card")
            )

    existing_item = None
    if user_id is not None and card is not None:
        existing_item = find_conflicting_wishlist_item(db, user_id, card.id, preferred_condition, preferred_source)
        if existing_item is not None:
            warnings.append(
                RowIssue(
                    row_number,
                    None,
                    None,
                    "likely_duplicate",
                    f"An existing wishlist item (id={existing_item.id}) matches this card/condition/source",
                )
            )

    action = "would_update" if existing_item is not None else "would_create"
    return RowOutcome(errors, warnings, action, normalized, dedupe_key)


_ROW_VALIDATORS = {
    "card_catalog": _validate_card_catalog_row,
    "source_mappings": _validate_source_mappings_row,
    "snkrdunk_candidates": _validate_snkrdunk_candidates_row,
    "collection": _validate_collection_row,
    "wishlist": _validate_wishlist_row,
}


def _build_ctx(db: Session, import_type: str) -> dict:
    """Prefetches whatever a type's row validator needs looked up more than
    once per call - avoids an O(rows) full-table scan (source_mappings'
    close-match suggestion, snkrdunk_candidates' card-code matching) turning
    into an O(rows * table_size) one."""
    if import_type == "source_mappings":
        sources = db.scalars(select(Source)).all()
        cards = db.scalars(select(Card.card_code).where(Card.is_active.is_(True))).all()
        return {
            "sources_by_name": {s.name.strip().lower(): s for s in sources},
            "active_card_codes": list(cards),
        }
    if import_type == "snkrdunk_candidates":
        urls = db.scalars(select(SnkrdunkCandidate.source_url)).all()
        cards = db.scalars(select(Card).where(Card.is_active.is_(True))).all()
        cards_by_code: dict[str | None, list[Card]] = defaultdict(list)
        for c in cards:
            cards_by_code[normalize_card_code(c.card_code)].append(c)
        return {
            "existing_candidate_urls": {u.strip().lower() for u in urls if u},
            "cards_by_code": cards_by_code,
        }
    return {}


def _empty_result(import_type: str, *, code: str, message: str) -> ValidationResult:
    spec = TYPE_SPECS.get(import_type)
    columns = ColumnsInfo(
        required_columns=list(spec.required_columns) if spec else [],
        optional_columns=list(spec.optional_columns) if spec else [],
        received_columns=[],
        missing_required_columns=[],
        unknown_columns=[],
    )
    summary = ValidationSummary()
    errors = [RowIssue(0, None, None, code, message)]
    return ValidationResult(import_type, False, summary, columns, errors, [], [])


def validate_import_csv(
    db: Session,
    import_type: str,
    csv_bytes: bytes,
    *,
    strict: bool = False,
    max_preview_rows: int = DEFAULT_MAX_PREVIEW_ROWS,
    user_id: int | None = None,
) -> ValidationResult:
    if import_type not in TYPE_SPECS:
        raise ValueError(f"Unsupported import_type '{import_type}'. Must be one of {IMPORT_TYPES}")

    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return _empty_result(import_type, code="invalid_encoding", message=f"File is not valid UTF-8: {exc}")

    if not csv_text.strip():
        return _empty_result(import_type, code="empty_file", message="CSV file is empty")

    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    except csv.Error as exc:
        return _empty_result(import_type, code="malformed_csv", message=f"Could not parse CSV: {exc}")

    if not fieldnames:
        return _empty_result(import_type, code="empty_file", message="CSV file has no header row")

    spec = TYPE_SPECS[import_type]
    missing_required = [c for c in spec.required_columns if c not in fieldnames]
    known_columns = set(spec.required_columns) | set(spec.optional_columns)
    unknown_columns = [c for c in fieldnames if c not in known_columns]

    columns = ColumnsInfo(
        required_columns=list(spec.required_columns),
        optional_columns=list(spec.optional_columns),
        received_columns=fieldnames,
        missing_required_columns=missing_required,
        unknown_columns=unknown_columns,
    )

    errors: list[RowIssue] = []
    warnings: list[RowIssue] = []

    for col in missing_required:
        errors.append(RowIssue(1, col, None, "missing_required_column", f"Required column '{col}' is missing"))
    for col in unknown_columns:
        issue = RowIssue(1, col, None, "unknown_column", f"Unrecognized column '{col}'")
        (errors if strict else warnings).append(issue)

    summary = ValidationSummary(total_rows=len(rows))

    if missing_required:
        return ValidationResult(import_type, False, summary, columns, errors, warnings, [])

    if import_type in ("collection", "wishlist") and user_id is None:
        warnings.append(
            RowIssue(
                1,
                None,
                None,
                "user_scope_unknown",
                "No user_id was provided; duplicate/would_update detection against existing "
                f"{import_type} items was skipped and every valid row is reported as would_create.",
            )
        )

    ctx = _build_ctx(db, import_type)
    validator = _ROW_VALIDATORS[import_type]
    seen_keys: dict[Any, int] = {}
    preview: list[PreviewRow] = []

    for row_number, row in enumerate(rows, start=2):
        outcome = validator(db, row_number, row, ctx=ctx, user_id=user_id)

        if outcome.dedupe_key is not None:
            if outcome.dedupe_key in seen_keys:
                summary.duplicate_rows += 1
                outcome.warnings.append(
                    RowIssue(
                        row_number,
                        None,
                        None,
                        "duplicate_row",
                        f"Duplicate of row {seen_keys[outcome.dedupe_key]} in this file",
                    )
                )
            else:
                seen_keys[outcome.dedupe_key] = row_number

        errors.extend(outcome.errors)
        warnings.extend(outcome.warnings)

        if outcome.errors:
            summary.error_rows += 1
        else:
            summary.valid_rows += 1
            if outcome.action == "would_create":
                summary.would_create += 1
            elif outcome.action == "would_update":
                summary.would_update += 1
            elif outcome.action == "would_skip":
                summary.would_skip += 1
        if outcome.warnings:
            summary.warning_rows += 1

        if len(preview) < max_preview_rows:
            preview.append(
                PreviewRow(
                    row_number=row_number,
                    action=outcome.action if not outcome.errors else "invalid",
                    normalized_values=outcome.normalized_values,
                    warnings=[w.message for w in outcome.warnings],
                    errors=[e.message for e in outcome.errors],
                )
            )

    valid = len(errors) == 0
    return ValidationResult(import_type, valid, summary, columns, errors, warnings, preview)
