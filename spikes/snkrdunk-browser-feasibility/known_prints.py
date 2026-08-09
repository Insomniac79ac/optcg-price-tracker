"""Offline reference identity data for the exact-print verification step
(section 3 of the current feasibility spec, formerly section 7). Sourced by a
read-only query against the staging database's verified `card_prints` rows -
this spike never connects to Postgres itself; these are frozen, hand-copied
field values used only for offline comparison against a discovered SNKRDUNK
product.

image_url is Bandai's own official public card-list artwork URL for the
print (not a SNKRDUNK asset) - used for perceptual-hash/aspect-ratio
comparison (see spike.compare_artwork), not pixel-diffed.

Corrected 2026-08-09: the previous revision of this file (card_print_id
15/16/17) held IDs and artwork_key/image_url values that did not match their
stated card_code in the live database - id=15's artwork_key/image_url
actually belonged to an unrelated OP04 Sabo SR print, not OP01-001 Zoro
parallel. Re-verified directly against the 3 relevant rows:

    SELECT cp.id, cp.treatment, cp.release_product_code, cp.artwork_key,
           cp.image_url, cc.card_code, cc.rarity, cc.name_jp
    FROM card_prints cp JOIN canonical_cards cc ON cc.id = cp.canonical_card_id
    WHERE cp.id IN (1, 2, 4);

card_print.id=1 (OP01-001, rarity L, treatment parallel) is the print
required by the current spec for product https://snkrdunk.com/apparels/104428.

Ordered by spec preference: primary target first, then next-best fallbacks.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownPrint:
    card_print_id: int
    card_code: str
    name_en: str
    name_jp: str
    set_code: str
    release_name: str  # human-readable booster/release name (not stored in DB)
    rarity: str  # canonical_cards.rarity, e.g. "L", "R"
    treatment: str  # card_prints.treatment, e.g. "parallel", "normal"
    language: str
    release_product_code: str | None
    artwork_key: str
    image_url: str  # official Bandai artwork


KNOWN_PRINTS: list[KnownPrint] = [
    KnownPrint(
        card_print_id=1,
        card_code="OP01-001",
        name_en="Roronoa Zoro",
        name_jp="ロロノア・ゾロ",
        set_code="OP01",
        release_name="ROMANCE DAWN",
        rarity="L",
        treatment="parallel",
        language="jp",
        release_product_code="OP-01",
        artwork_key="4b2462f2b042a02070f134b319c73ddbf09f340c3b903fc8242b63ab7791ec79",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png?260630",
    ),
    KnownPrint(
        card_print_id=2,
        card_code="OP01-002",
        name_en="Trafalgar Law",
        name_jp="トラファルガー・ロー",
        set_code="OP01",
        release_name="ROMANCE DAWN",
        rarity="L",
        treatment="parallel",
        language="jp",
        release_product_code="OP-01",
        artwork_key="94004dbdb4e9786a15c0fd8abb4ea1ae12d5c2c498e357e0addd22060646122c",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-002_p1.png?260630",
    ),
    KnownPrint(
        card_print_id=4,
        card_code="OP01-013",
        name_en="Sanji",
        name_jp="サンジ",
        set_code="OP01",
        release_name="ROMANCE DAWN",
        rarity="R",
        treatment="normal",
        language="jp",
        release_product_code="OP-01",
        artwork_key="ef20a8a51391e53f4a3fe71251d20a9dfe3d59dc65a4217a6c9b2eefaff2db2b",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013.png?260630",
    ),
]
