"""Downloadable CSV templates for the larger bulk-import flows - see GET
/admin/import-templates|import-templates/{template_type}.csv and
docs/operations.md's "CSV import validation workflow". Purely descriptive:
this module never touches the database, never writes anything.
required_columns/optional_columns are always read from
app.services.import_validation.TYPE_SPECS (the single source of truth for
what POST /admin/import-validation/{import_type} actually accepts), so a
downloaded template's header row can never drift from what validation
expects - only description/sample_rows/notes are template-specific content.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.services.import_validation import TYPE_SPECS

TEMPLATE_TYPES = (
    "card_catalog",
    "source_mappings",
    "snkrdunk_candidates",
    "collection",
    "wishlist",
)


@dataclass
class ImportTemplate:
    template_type: str
    filename: str
    description: str
    sample_rows: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def required_columns(self) -> tuple[str, ...]:
        return TYPE_SPECS[self.template_type].required_columns

    @property
    def optional_columns(self) -> tuple[str, ...]:
        return TYPE_SPECS[self.template_type].optional_columns

    @property
    def columns(self) -> list[str]:
        return [*self.required_columns, *self.optional_columns]

    def to_dict(self, *, download_url: str) -> dict:
        return {
            "template_type": self.template_type,
            "filename": self.filename,
            "description": self.description,
            "required_columns": list(self.required_columns),
            "optional_columns": list(self.optional_columns),
            "download_url": download_url,
            "notes": self.notes,
        }


_TEMPLATES: dict[str, ImportTemplate] = {
    "card_catalog": ImportTemplate(
        template_type="card_catalog",
        filename="card_catalog_template.csv",
        description=(
            "Canonical card catalog rows (the `cards` table). card_code + name_en "
            "identify a row; set_code/rarity/variant/language refine which existing "
            "card (if any) it updates."
        ),
        sample_rows=[
            {
                "card_code": "OP01-001",
                "name_en": "Monkey.D.Luffy",
                "name_jp": "モンキー・D・ルフィ",
                "set_code": "OP01",
                "rarity": "L",
                "variant": "base",
                "language": "en",
                "image_url": "",
                "release_date": "2022-12-02",
                "artist": "",
                "character": "Monkey D. Luffy",
                "color": "Red",
                "card_type": "Leader",
                "cost": "",
                "power": "5000",
                "counter": "",
                "attribute": "Strike",
                "effect_text": "",
                "trigger_text": "",
                "notes": "",
            },
        ],
        notes=[
            "set_code is inferred from card_code (text before the first hyphen) when left blank.",
            "language defaults to jp when left blank; en/jp and common synonyms (english/japanese) are accepted.",
            "variant accepts common synonyms (para -> parallel, alt -> alt_art, ...).",
        ],
    ),
    "source_mappings": ImportTemplate(
        template_type="source_mappings",
        filename="source_mappings_template.csv",
        description=(
            "Links a card_code to a listing on an external source (source_card_mappings). "
            "source_name must already exist in the sources table (e.g. yuyutei, snkrdunk)."
        ),
        sample_rows=[
            {
                "source_name": "yuyutei",
                "source_url": "https://yuyu-tei.jp/sell/opc/card/OP01-001",
                "card_code": "OP01-001",
                "source_card_id": "OP01-001",
                "source_card_code": "OP01-001",
                "review_status": "needs_review",
                "is_active": "true",
                "manual_verified": "false",
                "review_notes": "",
            },
        ],
        notes=[
            "review_status must be one of: approved, needs_review, rejected (defaults to needs_review).",
            "is_active/manual_verified accept true/false/1/0/yes/no.",
        ],
    ),
    "snkrdunk_candidates": ImportTemplate(
        template_type="snkrdunk_candidates",
        filename="snkrdunk_candidates_template.csv",
        description=(
            "Manually collected SNKRDUNK listing candidates awaiting card matching "
            "(snkrdunk_candidates). No live scraping is performed by this import - "
            "rows must already contain the listing data."
        ),
        sample_rows=[
            {
                "source_url": "https://snkrdunk.com/items/example-123",
                "title": "OP01-001 Monkey.D.Luffy Parallel",
                "price_jpy": "5000",
                "image_url": "",
                "listing_count": "3",
                "condition_label": "near_mint",
                "raw_text": "",
                "normalized_title": "",
                "detected_card_code": "OP01-001",
                "set_code": "OP01",
                "rarity": "L",
                "variant": "parallel",
                "match_status": "unmatched",
            },
        ],
        notes=[
            "match_status must be one of: unmatched, suggested, ambiguous, matched, rejected (defaults to unmatched).",
            "detected_card_code is used as-is when present; otherwise it is parsed from title.",
        ],
    ),
    "collection": ImportTemplate(
        template_type="collection",
        filename="collection_template.csv",
        description="Personal collection items - reuses the existing collection CSV import schema.",
        sample_rows=[
            {
                "card_code": "OP01-001",
                "quantity": "1",
                "condition_label": "near_mint",
                "purchase_price_jpy": "5000",
                "purchase_date": "2026-01-15",
                "purchase_source": "yuyutei",
                "target_sell_price_jpy": "",
                "status": "hold",
                "notes": "",
                "tags": "",
                "groups": "",
            },
        ],
        notes=["status must be one of: hold, watch, sell, sold, grading (defaults to hold)."],
    ),
    "wishlist": ImportTemplate(
        template_type="wishlist",
        filename="wishlist_template.csv",
        description="Wishlist items - reuses the existing wishlist CSV import schema.",
        sample_rows=[
            {
                "card_code": "OP01-001",
                "priority": "high",
                "status": "watching",
                "target_buy_price_jpy": "4000",
                "max_buy_price_jpy": "6000",
                "preferred_condition": "near_mint",
                "preferred_source": "",
                "desired_quantity": "1",
                "acquired_quantity": "0",
                "notes": "",
            },
        ],
        notes=[
            "priority must be one of: low, medium, high, grail (defaults to medium).",
            "status must be one of: watching, target_hit, purchased, passed, removed (defaults to watching).",
        ],
    ),
}


def list_templates() -> list[ImportTemplate]:
    return [_TEMPLATES[t] for t in TEMPLATE_TYPES]


def get_template(template_type: str) -> ImportTemplate | None:
    return _TEMPLATES.get(template_type)


def generate_template_csv(template_type: str) -> str | None:
    """Returns the template's header row plus its sample row(s) as CSV text,
    or None if template_type isn't recognized."""
    template = get_template(template_type)
    if template is None:
        return None

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(template.columns))
    writer.writeheader()
    for row in template.sample_rows:
        writer.writerow({col: row.get(col, "") for col in template.columns})

    return buffer.getvalue()
