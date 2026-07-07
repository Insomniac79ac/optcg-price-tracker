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
    skipped_rows: int = 0

    def print_report(self) -> None:
        print(f"cards_created: {self.cards_created}")
        print(f"cards_updated: {self.cards_updated}")
        print(f"mappings_created: {self.mappings_created}")
        print(f"mappings_updated: {self.mappings_updated}")
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


def _import_row(db: Session, row: dict[str, str], summary: ImportSummary) -> None:
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
            continue

        source = _get_or_create_source(db, source_name)
        mapping = (
            db.query(SourceCardMapping)
            .filter_by(card_id=card.id, source_id=source.id)
            .one_or_none()
        )
        if mapping is None:
            db.add(
                SourceCardMapping(
                    card_id=card.id,
                    source_id=source.id,
                    source_card_id=card_code,
                    source_url=url,
                    manual_verified=manual_verified,
                )
            )
            summary.mappings_created += 1
        else:
            mapping.source_url = url
            mapping.manual_verified = manual_verified
            summary.mappings_updated += 1


def import_watchlist(csv_path: str, db: Session | None = None) -> ImportSummary:
    summary = ImportSummary()
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                _import_row(db, row, summary)
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
