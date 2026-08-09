"""Offline reference identity data for the exact-print verification step
(section 7 of the feasibility spec). Sourced by a read-only query against the
staging database's 20 verified `card_prints` rows - this spike never
connects to Postgres itself; these are frozen, hand-copied field values used
only for offline comparison against a discovered SNKRDUNK product.

image_url is Bandai's own official public card-list artwork URL for the
print (not a SNKRDUNK asset) - used to compare art direction/treatment by
eye, not pixel-diffed.

Ordered by spec section 6 preference.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownPrint:
    card_print_id: int
    card_code: str
    name_en: str
    name_jp: str
    set_code: str
    rarity: str
    variant: str | None
    treatment: str
    language: str
    release_product_code: str | None
    artwork_key: str
    image_url: str  # official Bandai artwork


KNOWN_PRINTS: list[KnownPrint] = [
    KnownPrint(
        card_print_id=15,
        card_code="OP01-001",
        name_en="Roronoa Zoro (Parallel)",
        name_jp="ロロノア・ゾロ(パラレル)",
        set_code="OP01",
        rarity="Parallel",
        variant="Leader",
        treatment="normal",
        language="jp",
        release_product_code="OP-04",
        artwork_key="b7873d3cb2e8e46e1d126f7e3fd2ca6205e3ed44828b00a8c409417bbb2c6512",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP04-083.png?260630",
    ),
    KnownPrint(
        card_print_id=16,
        card_code="OP01-002",
        name_en="Trafalgar Law (Parallel)",
        name_jp="トラファルガー・ロー(パラレル)",
        set_code="OP01",
        rarity="Parallel",
        variant="Leader",
        treatment="normal",
        language="jp",
        release_product_code="OP-04",
        artwork_key="1f0ebe0a0dc80e60fab681e52db9a37be5185dbbabfe8b7401c73dfe04cda013",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP04-007.png?260630",
    ),
    KnownPrint(
        card_print_id=17,
        card_code="OP01-013",
        name_en="Sanji",
        name_jp="サンジ",
        set_code="OP01",
        rarity="R",
        variant=None,
        treatment="normal",
        language="jp",
        release_product_code="OP-04",
        artwork_key="681513323c03e179935b7d8ce2833d411f96031d34f2b55786042e4145e30129",
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP04-090.png?260630",
    ),
]
