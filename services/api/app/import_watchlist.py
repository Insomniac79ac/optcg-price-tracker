import argparse
import csv
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Card, Source, SourceCardMapping

SOURCE_URL_COLUMNS = {
    "yuyutei": "yuyutei_url",
    "snkrdunk": "snkrdunk_url",
}

SOURCE_BASE_URLS = {
    "yuyutei": "https://yuyu-tei.jp",
    "snkrdunk": "https://snkrdunk.com",
}

TRUE_VALUES = {"true", "1", "yes", "y", "t"}

REQUIRED_COLUMNS = ("card_code", "set_code", "rarity", "language")


@dataclass
class ImportSummary:
    cards_created: int = 0
    cards_updated: int = 0
    mappings_created: int = 0
    mappings_updated: int = 0
    mappings_skipped_empty_url: int = 0
    duplicate_urls_skipped: int = 0
    skipped_rows: int = 0

    def print_report(self) -> None:
        print(f"cards_created: {self.cards_created}")
        print(f"cards_updated: {self.cards_updated}")
        print(f"mappings_created: {self.mappings_created}")
        print(f"mappings_updated: {self.mappings_updated}")
        print(f"mappings_skipped_empty_url: {self.mappings_skipped_empty_url}")
        print(f"duplicate_urls_skipped: {self.duplicate_urls_skipped}")
        print(f"skipped_rows: {self.skipped_rows}")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _get_or_create_source(db: Session, name: str) -> Source:
    source = db.query(Source).filter_by(name=name).one_or_none()
    if source is None:
        source = Source(name=name, base_url=SOURCE_BASE_URLS.get(name, ""))
        db.add(source)
        db.flush()
    return source


def _upsert_mapping(
    db: Session,
    card: Card,
    source: Source,
    card_code: str,
    url: str,
    manual_verified: bool,
    seen_urls: set[tuple[int, str]],
    summary: ImportSummary,
) -> None:
    """Upsert a source_card_mappings row keyed by (source_id, source_url), so
    a card can have multiple mappings per source (raw/graded pages, reprints,
    multiple listings, etc)."""
    key = (source.id, url)
    if key in seen_urls:
        summary.duplicate_urls_skipped += 1
        return
    seen_urls.add(key)

    mapping = (
        db.query(SourceCardMapping)
        .filter_by(source_id=source.id, source_url=url)
        .one_or_none()
    )
    if mapping is None:
        mapping = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=card_code,
            source_url=url,
            manual_verified=manual_verified,
        )
        db.add(mapping)
        summary.mappings_created += 1
    else:
        mapping.card_id = card.id
        mapping.source_card_id = card_code
        mapping.manual_verified = manual_verified
        mapping.match_confidence = None
        summary.mappings_updated += 1

    # A row the watchlist itself vouches for (manual_verified=true) is
    # authoritative - re-importing it should un-reject/re-activate it even if
    # an earlier review had flagged it, since a curated watchlist entry is a
    # stronger signal than a prior auto-match review decision.
    if manual_verified:
        mapping.is_active = True
        mapping.review_status = "approved"


def _import_row(
    db: Session, row: dict[str, str], summary: ImportSummary, seen_urls: set[tuple[int, str]]
) -> None:
    if any(not _clean(row.get(column)) for column in REQUIRED_COLUMNS):
        summary.skipped_rows += 1
        return

    card_code = _clean(row.get("card_code"))
    set_code = _clean(row.get("set_code"))
    rarity = _clean(row.get("rarity"))
    variant = _clean(row.get("variant"))
    language = _clean(row.get("language"))
    manual_verified = parse_bool(row.get("manual_verified"))

    card = (
        db.query(Card)
        .filter_by(card_code=card_code, variant=variant, language=language)
        .first()
    )

    if card is None:
        card = Card(
            card_code=card_code,
            name_en=_clean(row.get("name_en")),
            name_jp=_clean(row.get("name_jp")),
            set_code=set_code,
            rarity=rarity,
            variant=variant,
            language=language,
            image_url=_clean(row.get("image_url")),
        )
        db.add(card)
        db.flush()
        summary.cards_created += 1
    else:
        card.name_en = _clean(row.get("name_en"))
        card.name_jp = _clean(row.get("name_jp"))
        card.set_code = set_code
        card.rarity = rarity
        card.image_url = _clean(row.get("image_url"))
        summary.cards_updated += 1

    for source_name, column in SOURCE_URL_COLUMNS.items():
        url = _clean(row.get(column))
        if not url:
            summary.mappings_skipped_empty_url += 1
            continue

        source = _get_or_create_source(db, source_name)
        _upsert_mapping(db, card, source, card_code, url, manual_verified, seen_urls, summary)


def import_watchlist(csv_path: str, db: Session | None = None) -> ImportSummary:
    summary = ImportSummary()
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        seen_urls: set[tuple[int, str]] = set()
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                _import_row(db, row, summary, seen_urls)
        db.commit()
    finally:
        if owns_session:
            db.close()

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a card watchlist CSV.")
    parser.add_argument("csv_path", help="Path to the watchlist CSV file")
    args = parser.parse_args()

    summary = import_watchlist(args.csv_path)
    summary.print_report()


if __name__ == "__main__":
    main()
