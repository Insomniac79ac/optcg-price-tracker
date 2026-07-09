import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Card, Source, SourceCardMapping

SOURCES = [
    {"name": "yuyutei", "base_url": "https://yuyu-tei.jp"},
    {"name": "snkrdunk", "base_url": "https://snkrdunk.com"},
]

# Sample/demo data only - not real catalog data. Only seeded when --demo-data
# is passed, so the real card catalog (built via app.import_watchlist) never
# gets polluted with these placeholder rows by default. `source_card_id`
# matches the keys used in services/worker/fixtures/*.json so the mock
# worker has data to read.
DEMO_CARDS = [
    {"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "name_jp": "モンキー・D・ルフィ", "set_code": "OP01", "rarity": "L", "variant": "base", "language": "jp"},
    {"card_code": "OP01-013", "name_en": "Roronoa Zoro", "name_jp": "ロロノア・ゾロ", "set_code": "OP01", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP01-024", "name_en": "Nami", "name_jp": "ナミ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP01-034", "name_en": "Usopp", "name_jp": "ウソップ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP01-041", "name_en": "Sanji", "name_jp": "サンジ", "set_code": "OP01", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP02-013", "name_en": "Trafalgar Law", "name_jp": "トラファルガー・ロー", "set_code": "OP02", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP02-025", "name_en": "Nico Robin", "name_jp": "ニコ・ロビン", "set_code": "OP02", "rarity": "R", "variant": "base", "language": "jp"},
    {"card_code": "OP03-013", "name_en": "Yamato", "name_jp": "ヤマト", "set_code": "OP03", "rarity": "SR", "variant": "base", "language": "jp"},
    {"card_code": "OP04-004", "name_en": "Shanks", "name_jp": "シャンクス", "set_code": "OP04", "rarity": "SEC", "variant": "base", "language": "jp"},
    {"card_code": "OP05-119", "name_en": "Kaido", "name_jp": "カイドウ", "set_code": "OP05", "rarity": "SEC", "variant": "alt_art", "language": "jp"},
]

# Maps demo cards to demo sources.
DEMO_MAPPINGS = [
    {"card_code": "OP01-001", "source_name": "yuyutei", "source_card_id": "OP01-001", "source_url": "https://yuyu-tei.jp/sell/opc/card/OP01-001"},
    {"card_code": "OP01-001", "source_name": "snkrdunk", "source_card_id": "OP01-001", "source_url": "https://snkrdunk.com/cards/OP01-001"},
    {"card_code": "OP01-013", "source_name": "yuyutei", "source_card_id": "OP01-013", "source_url": "https://yuyu-tei.jp/sell/opc/card/OP01-013"},
    {"card_code": "OP01-013", "source_name": "snkrdunk", "source_card_id": "OP01-013", "source_url": "https://snkrdunk.com/cards/OP01-013"},
]


def seed_sources(db: Session) -> None:
    """Create/update the fixed set of price sources. Idempotent, and the only
    thing `python -m app.seed` does by default."""
    for source_data in SOURCES:
        exists = db.query(Source).filter_by(name=source_data["name"]).one_or_none()
        if exists is None:
            db.add(Source(**source_data))
    db.flush()


def seed_demo_data(db: Session) -> None:
    """Seed placeholder demo cards/mappings for local development. Never run
    by default - only via `python -m app.seed --demo-data`."""
    for card_data in DEMO_CARDS:
        exists = (
            db.query(Card)
            .filter_by(
                card_code=card_data["card_code"],
                set_code=card_data["set_code"],
                rarity=card_data["rarity"],
                variant=card_data["variant"],
                language=card_data["language"],
            )
            .one_or_none()
        )
        if exists is None:
            db.add(Card(**card_data))

    db.flush()

    for mapping_data in DEMO_MAPPINGS:
        card = db.query(Card).filter_by(card_code=mapping_data["card_code"]).one_or_none()
        source = db.query(Source).filter_by(name=mapping_data["source_name"]).one_or_none()
        if card is None or source is None:
            continue

        exists = (
            db.query(SourceCardMapping)
            .filter_by(source_id=source.id, source_url=mapping_data["source_url"])
            .one_or_none()
        )
        if exists is None:
            db.add(
                SourceCardMapping(
                    card_id=card.id,
                    source_id=source.id,
                    source_card_id=mapping_data["source_card_id"],
                    source_url=mapping_data["source_url"],
                )
            )


def seed(demo_data: bool = False) -> None:
    db = SessionLocal()
    try:
        seed_sources(db)
        if demo_data:
            seed_demo_data(db)
        db.commit()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed reference data. By default only creates/updates the sources table "
        "(yuyutei, snkrdunk); real cards come from app.import_watchlist."
    )
    parser.add_argument(
        "--demo-data", action="store_true",
        help="Also seed placeholder demo cards and mappings for local development/testing. "
        "Not real catalog data.",
    )
    args = parser.parse_args()

    seed(demo_data=args.demo_data)


if __name__ == "__main__":
    main()
