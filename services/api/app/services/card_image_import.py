"""Admin CSV workflow for attaching a verified image to an *existing* card
row - see POST /admin/cards/import-images.csv and GET
/admin/cards/import-images-template.csv.

This is deliberately a separate, narrower module from
app.services.card_catalog_import (the general cards-table importer), not an
extension of it, for two reasons:

1. Ambiguity safety. The general importer treats a blank `rarity` column as
   "matches any rarity" (a sparse-row convenience). An image is a
   variant-specific asset - the whole point of this workflow is "attach
   *this* image to *this exact printing*, never a different rarity/variant
   of the same card_code" - so here every identity field
   (card_code/set_code/rarity/variant/language) is required and used as an
   exact filter; zero or multiple matches is always a row error, never a
   guess. This importer also never creates a new card row - it only ever
   attaches an image to a card that already exists.
2. URL content validation. Attaching an image means fetching the URL
   server-side and confirming it actually returns image content (not an
   HTML error/login/CAPTCHA page a broken or blocked URL would return) -
   see `_validate_image_url`. The general importer has no equivalent
   concept; it just stores whatever string is in the `image_url` column.

Approved sources only (see docs/staging_data.md "Approved price sources"):
"yuyutei" and "snkrdunk" - matching app.api.source_mappings.SUPPORTED_SOURCES.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card

REQUIRED_IMPORT_COLUMNS = (
    "card_code",
    "rarity",
    "variant",
    "image_url",
    "image_source",
    "image_source_url",
)

TEMPLATE_COLUMNS = (
    "card_code",
    "set_code",
    "rarity",
    "variant",
    "language",
    "image_url",
    "image_source",
    "image_source_url",
)

APPROVED_IMAGE_SOURCES = ("yuyutei", "snkrdunk")

DEFAULT_LANGUAGE = "jp"

# Kept generous (default httpx client timeout is unset/None, i.e. no
# timeout) - this is a synchronous admin action on a handful of rows, not a
# background job, so a bounded per-request timeout matters more than
# throughput.
_FETCH_TIMEOUT_SECONDS = 10.0


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _infer_set_code(card_code: str) -> str:
    """OP01-001 -> OP01 - same rule as card_catalog_import._infer_set_code,
    duplicated rather than imported (see module docstring)."""
    return card_code.split("-", 1)[0]


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


@dataclass
class ParsedRow:
    row_number: int
    card_code: str
    set_code: str
    rarity: str
    variant: str | None
    language: str
    image_url: str
    image_source: str
    image_source_url: str


@dataclass
class RowError:
    row_number: int
    card_code: str | None
    error: str

    def to_dict(self) -> dict:
        return {"row_number": self.row_number, "card_code": self.card_code, "error": self.error}


@dataclass
class RowOutcome:
    row_number: int
    card_code: str
    card_id: int
    action: str
    image_url: str
    image_source: str

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "card_code": self.card_code,
            "card_id": self.card_id,
            "action": self.action,
            "image_url": self.image_url,
            "image_source": self.image_source,
        }


@dataclass
class ImageImportResult:
    dry_run: bool
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    applied: int = 0
    errors: list[RowError] = field(default_factory=list)
    preview: list[RowOutcome] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "summary": {
                "total_rows": self.total_rows,
                "valid_rows": self.valid_rows,
                "error_rows": self.error_rows,
                "applied": self.applied,
            },
            "errors": [e.to_dict() for e in self.errors],
            "preview": [p.to_dict() for p in self.preview],
        }


def _parse_row(row_number: int, row: dict[str, str]) -> tuple[ParsedRow | None, RowError | None]:
    card_code = _clean(row.get("card_code"))
    if card_code is None:
        return None, RowError(row_number, None, "card_code is required")

    rarity = _clean(row.get("rarity"))
    if rarity is None:
        return None, RowError(
            row_number, card_code, "rarity is required (this importer never guesses a variant)"
        )

    # A blank variant column means "this printing has no variant" (matches
    # Card.variant IS NULL), not "unspecified" - see module docstring on why
    # this importer never leaves an identity field unfiltered.
    variant = _clean(row.get("variant"))

    set_code = _clean(row.get("set_code")) or _infer_set_code(card_code)
    language = _clean(row.get("language")) or DEFAULT_LANGUAGE

    image_url = _clean(row.get("image_url"))
    if image_url is None:
        return None, RowError(row_number, card_code, "image_url is required")
    if not _is_https_url(image_url):
        return None, RowError(row_number, card_code, f"image_url must be an https URL: {image_url!r}")

    image_source = _clean(row.get("image_source"))
    if image_source not in APPROVED_IMAGE_SOURCES:
        return None, RowError(
            row_number,
            card_code,
            f"image_source must be one of {APPROVED_IMAGE_SOURCES}, got {image_source!r}",
        )

    image_source_url = _clean(row.get("image_source_url"))
    if image_source_url is None:
        return None, RowError(
            row_number, card_code, "image_source_url is required (the public page this was verified against)"
        )
    if not _is_https_url(image_source_url):
        return None, RowError(
            row_number, card_code, f"image_source_url must be an https URL: {image_source_url!r}"
        )

    return (
        ParsedRow(
            row_number=row_number,
            card_code=card_code,
            set_code=set_code,
            rarity=rarity,
            variant=variant,
            language=language,
            image_url=image_url,
            image_source=image_source,
            image_source_url=image_source_url,
        ),
        None,
    )


def _find_existing_card(db: Session, parsed: ParsedRow) -> tuple[Card | None, str | None]:
    """Returns (card, error_message). Every identity field is used as an
    exact filter - a card must already exist and match uniquely, or this is
    a row error. Never creates a card."""
    filters = [
        Card.card_code == parsed.card_code,
        Card.set_code == parsed.set_code,
        Card.rarity == parsed.rarity,
        Card.language == parsed.language,
    ]
    if parsed.variant is not None:
        filters.append(Card.variant == parsed.variant)
    else:
        filters.append(Card.variant.is_(None))

    matches = db.scalars(select(Card).where(*filters)).all()
    if len(matches) == 0:
        return None, (
            f"No existing card matches card_code={parsed.card_code!r} set_code={parsed.set_code!r} "
            f"rarity={parsed.rarity!r} variant={parsed.variant!r} language={parsed.language!r} - "
            "this importer never creates a card, only attaches an image to one that already exists"
        )
    if len(matches) == 1:
        return matches[0], None
    return None, (
        f"{len(matches)} existing cards match this row's identity - ambiguous, refusing to guess "
        "(this should be impossible given cards' own unique constraint; check for duplicate rows)"
    )


def _validate_image_url(image_url: str, *, client: httpx.Client | None = None) -> str | None:
    """Fetches image_url and confirms it returns real image content, not an
    HTML error/login/CAPTCHA page. Returns an error string, or None if valid.
    A HEAD request is tried first (cheaper, no body download); some hosts
    don't support HEAD for asset URLs, so a ranged GET is the fallback."""
    owns_client = client is None
    client = client or httpx.Client(
        timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": "OPTCGVault-ImageImport/1.0"}
    )
    try:
        try:
            resp = client.head(image_url)
            content_type = resp.headers.get("content-type", "")
            if resp.status_code == 200 and content_type.startswith("image/"):
                return None
        except httpx.HTTPError:
            pass

        try:
            resp = client.get(image_url, headers={"Range": "bytes=0-2047"})
        except httpx.HTTPError as exc:
            return f"Could not fetch image_url: {exc}"

        if resp.status_code not in (200, 206):
            return f"image_url returned HTTP {resp.status_code}, not a usable image"
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return f"image_url returned content-type {content_type!r}, not an image (likely an HTML error page)"
        return None
    finally:
        if owns_client:
            client.close()


def import_card_images_csv(db: Session, csv_text: str, *, dry_run: bool = True) -> ImageImportResult:
    """Parses and (optionally) applies a card-image CSV import. Every row's
    image_url is fetched and content-type-checked even in dry_run, so the
    preview reflects real reachability rather than just row shape - see
    `_validate_image_url`. Only ever updates image_url/image_source/
    image_source_url/image_status/image_last_verified_at on an existing
    card; never creates a card, never touches any other field."""
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames or []
    missing_columns = [c for c in REQUIRED_IMPORT_COLUMNS if c not in fieldnames]
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {missing_columns}")

    result = ImageImportResult(dry_run=dry_run)
    now = datetime.now(timezone.utc)

    with httpx.Client(
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "OPTCGVault-ImageImport/1.0"},
    ) as client:
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

            validation_error = _validate_image_url(parsed.image_url, client=client)
            if validation_error is not None:
                result.error_rows += 1
                result.errors.append(RowError(row_number, parsed.card_code, validation_error))
                continue

            result.valid_rows += 1
            action = "would_apply" if dry_run else "applied"
            result.preview.append(
                RowOutcome(
                    row_number=row_number,
                    card_code=parsed.card_code,
                    card_id=card.id,
                    action=action,
                    image_url=parsed.image_url,
                    image_source=parsed.image_source,
                )
            )

            if dry_run:
                continue

            card.image_url = parsed.image_url
            card.image_source = parsed.image_source
            card.image_source_url = parsed.image_source_url
            card.image_status = "verified"
            card.image_last_verified_at = now
            result.applied += 1
            db.flush()

    if not dry_run:
        db.commit()

    return result


def image_import_template_csv() -> str:
    """The CSV template referenced by Phase 2/3 of the collector-first
    redesign audit - header row only plus one commented-style example so an
    operator sees the expected shape without it being parsed as real data
    (the example row's card_code starts with '#', which will never match a
    real card and will surface as a clear, harmless row error if ever
    submitted as-is)."""
    lines = [
        ",".join(TEMPLATE_COLUMNS),
        "#EXAMPLE-001,OP01,L,base,jp,https://card.yuyu-tei.jp/opc/front/op01/10001.jpg,yuyutei,https://yuyu-tei.jp/sell/opc/card/op01/10001",
    ]
    return "\n".join(lines) + "\n"
