import argparse

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)

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

# Exact print fixtures used by the demo price mappings below. These are
# explicit synthetic identities, not guesses derived from the legacy Card
# rows: each names its canonical card, product and official asset variant.
DEMO_RELEASE_PRODUCTS = [
    {
        "key": "op01",
        "source_catalogue": "bandai_jp",
        "official_code": "DEMO-OP01",
        "display_name": "ROMANCE DAWN [OP-01] (demo)",
        "first_seen_name": "ROMANCE DAWN [OP-01] (demo)",
        "source_series_id": "DEMO-OP01",
        "source_url": "https://example.invalid/demo/products/DEMO-OP01",
        "verification_status": "verified",
    }
]

DEMO_PRINTS = [
    {
        "key": "op01-001-base",
        "card_code": "OP01-001",
        "original_set_code": "OP-01",
        "card_type": "Leader",
        "product_key": "op01",
        "language": "jp",
        "treatment": "normal",
        "release_product_code": "DEMO-OP01",
        "official_asset_variant": "base",
        "artwork_key": "demo-fixture:OP01-001:base",
    },
    {
        "key": "op01-013-base",
        "card_code": "OP01-013",
        "original_set_code": "OP-01",
        "card_type": "Character",
        "product_key": "op01",
        "language": "jp",
        "treatment": "normal",
        "release_product_code": "DEMO-OP01",
        "official_asset_variant": "base",
        "artwork_key": "demo-fixture:OP01-013:base",
    },
]

# Maps demo exact prints to demo sources. card_id remains populated only as
# compatibility metadata for legacy development screens.
DEMO_MAPPINGS = [
    {
        "card_code": "OP01-001",
        "card_print_key": "op01-001-base",
        "source_name": "yuyutei",
        "source_card_id": "OP01-001",
        "source_url": "https://yuyu-tei.jp/sell/opc/card/OP01-001",
    },
    {
        "card_code": "OP01-001",
        "card_print_key": "op01-001-base",
        "source_name": "snkrdunk",
        "source_card_id": "OP01-001",
        "source_url": "https://snkrdunk.com/cards/OP01-001",
    },
    {
        "card_code": "OP01-013",
        "card_print_key": "op01-013-base",
        "source_name": "yuyutei",
        "source_card_id": "OP01-013",
        "source_url": "https://yuyu-tei.jp/sell/opc/card/OP01-013",
    },
    {
        "card_code": "OP01-013",
        "card_print_key": "op01-013-base",
        "source_name": "snkrdunk",
        "source_card_id": "OP01-013",
        "source_url": "https://snkrdunk.com/cards/OP01-013",
    },
]


def seed_sources(db: Session) -> None:
    """Create/update the fixed set of price sources. Idempotent, and the only
    thing `python -m app.seed` does by default."""
    for source_data in SOURCES:
        exists = db.query(Source).filter_by(name=source_data["name"]).one_or_none()
        if exists is None:
            db.add(Source(**source_data))
    db.flush()


def _seed_demo_prints(
    db: Session, cards_by_code: dict[str, Card]
) -> dict[str, CardPrint]:
    products: dict[str, ReleaseProduct] = {}
    for product_data in DEMO_RELEASE_PRODUCTS:
        product = (
            db.query(ReleaseProduct)
            .filter_by(
                source_catalogue=product_data["source_catalogue"],
                official_code=product_data["official_code"],
            )
            .one_or_none()
        )
        if product is None:
            product = ReleaseProduct(
                **{key: value for key, value in product_data.items() if key != "key"}
            )
            db.add(product)
            db.flush()
        products[product_data["key"]] = product

    prints: dict[str, CardPrint] = {}
    for print_data in DEMO_PRINTS:
        card = cards_by_code[print_data["card_code"]]
        canonical = (
            db.query(CanonicalCard).filter_by(card_code=print_data["card_code"]).one_or_none()
        )
        if canonical is None:
            canonical = CanonicalCard(
                card_code=print_data["card_code"],
                name_en=card.name_en,
                name_jp=card.name_jp,
                original_set_code=print_data["original_set_code"],
                rarity=card.rarity,
                card_type=print_data["card_type"],
            )
            db.add(canonical)
            db.flush()

        product = products[print_data["product_key"]]
        card_print = (
            db.query(CardPrint)
            .filter_by(
                canonical_card_id=canonical.id,
                language=print_data["language"],
                release_product_id=product.id,
                official_asset_variant=print_data["official_asset_variant"],
                verification_status="verified",
                is_active=True,
            )
            .one_or_none()
        )
        if card_print is None:
            card_print = CardPrint(
                canonical_card_id=canonical.id,
                language=print_data["language"],
                treatment=print_data["treatment"],
                release_product_code=print_data["release_product_code"],
                release_product_id=product.id,
                artwork_key=print_data["artwork_key"],
                official_asset_variant=print_data["official_asset_variant"],
                official_rarity=card.rarity,
                official_name=card.name_jp,
                verification_status="verified",
                is_active=True,
            )
            db.add(card_print)
            db.flush()
        prints[print_data["key"]] = card_print
    return prints


def seed_demo_data(db: Session) -> None:
    """Seed placeholder demo cards/mappings for local development. Never run
    by default - only via `python -m app.seed --demo-data`."""
    cards_by_code: dict[str, Card] = {}
    for card_data in DEMO_CARDS:
        card = (
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
        if card is None:
            card = Card(**card_data)
            db.add(card)
        cards_by_code[card_data["card_code"]] = card

    db.flush()
    prints = _seed_demo_prints(db, cards_by_code)

    for mapping_data in DEMO_MAPPINGS:
        card = cards_by_code.get(mapping_data["card_code"])
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
                    card_print_id=prints[mapping_data["card_print_key"]].id,
                    source_card_id=mapping_data["source_card_id"],
                    source_url=mapping_data["source_url"],
                    manual_verified=True,
                    is_active=True,
                    review_status="approved",
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
