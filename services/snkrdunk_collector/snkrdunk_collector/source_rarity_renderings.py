"""How SNKRDUNK writes a rarity that Bandai publishes differently.

WHY THIS EXISTS, AND WHY IT IS NOT A STRING RULE. SNKRDUNK titles some cards
with a COMPOUND rarity token - "モンキー・D・ルフィ：手配書 SR-SPC [ST01-012]".
The parser cannot read it (see identity.RARITY_UNRECOGNISED) and the collector
refuses, which cost nine mappings across two batches. Decoding it means
asserting that the storefront's "SPC" denotes Bandai's "SPカード", and that is
an equivalence between two vocabularies - exactly the kind of claim this
repository requires evidence for rather than resemblance.

THE EVIDENCE, gathered 2026-08-31 over the COMPLETE 676-candidate corpus, not
only the listings that happened to fail:

  * "SR-SPC" occurs on exactly 9 listings, covering 9 DISTINCT card codes
    (OP01-047, OP01-051, OP01-078, OP02-004, OP02-085, OP02-099, ST01-012,
    ST03-009, ST04-003), across 2 products (OP-03, OP-04) and 2 asset
    variants (p1, p2). The card codes and the products disagree on set number
    because these ARE reprints: an SP card of an OP-01 or ST-03 card, printed
    in the OP-03 or OP-04 booster. That is the whole reason the rarity is a
    property of the PRINT and not of the card.
  * Every one of the 9 resolves to a print whose `official_rarity` is
    `SPカード` and whose canonical card's rarity is `SR`. 9 of 9. No exception.
  * Independently, Bandai's own frozen catalogue
    (data/official_snapshots/bandai_jp) publishes, for each of those 9 card
    codes, EXACTLY ONE printing at rarity `SPカード` - and every other printing
    of the same code at `SR`. 46 printings in total: 9 `SPカード`, 37 `SR`.
    The product and asset variant of each `SPカード` entry is the one the
    resolver selected.
  * Zero counterexamples: no "SR-SPC" listing resolves to a print that is not
    `SPカード`.

So the token decomposes onto two facts Atlas already stores separately: the
card's base rarity (`canonical_cards.rarity` = SR) and that printing's own
published rarity (`card_prints.official_rarity` = SPカード). This module
records that decomposition; it invents nothing.

WHAT IS DELIBERATELY NOT DECLARED. The corpus also contains `SR-SP` (2
listings) and `SEC-SP` (2 listings). They are NOT listed here. Both are
different tokens, neither has an approved mapping, and therefore neither has a
verified print to check against - they are unverified, not merely unlisted.
Matching is exact whole-token equality, so they continue to fail closed, and
adding one requires the same evidence this one has.

BOTH HALVES ARE VERIFIED, WHICH MAKES THIS STRICTER THAN THE PLAIN CHECK. A
declared rendering does not simply supply a value to compare; it asserts two
things at once, and the listing is accepted only if Atlas agrees with BOTH.
A card whose canonical rarity is not `SR`, or whose print is not `SPカード`,
is refused even though its title says "SR-SPC" - which is the case a
single-value alias would have waved through.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRarityRendering:
    """One source's spelling of a rarity, and the two Atlas facts it asserts.

    `base_rarity` is checked against the CANONICAL card's rarity and
    `print_rarity` against the PRINT's own `official_rarity`. Keeping them
    apart is the point: the token is compound, and collapsing it to one value
    would discard half of what the source actually said.
    """

    source_name: str
    source_token: str
    base_rarity: str
    print_rarity: str
    observed_card_codes: tuple[str, ...]
    evidence: str


SOURCE_RARITY_RENDERINGS: tuple[SourceRarityRendering, ...] = (
    SourceRarityRendering(
        source_name="snkrdunk",
        source_token="SR-SPC",
        base_rarity="SR",
        print_rarity="SPカード",
        observed_card_codes=(
            "OP01-047", "OP01-051", "OP01-078", "OP02-004", "OP02-085",
            "OP02-099", "ST01-012", "ST03-009", "ST04-003",
        ),
        evidence=(
            "9 listings across 9 distinct card codes, 2 products (OP-03, OP-04) and 2 "
            "asset variants (p1, p2) in the 676-candidate corpus of 2026-08-31. All 9 "
            "resolve to a print with official_rarity='SPカード' and canonical rarity 'SR'. "
            "Bandai's frozen JP catalogue independently publishes exactly one 'SPカード' "
            "printing for each of those card codes and 'SR' for all 37 other printings, "
            "and the product/variant of each matches the print the resolver selected. "
            "No counterexample exists in the corpus."
        ),
    ),
)


def rendering_for_token(source_name: str, token: str | None) -> SourceRarityRendering | None:
    """Exact whole-token equality. No case folding, no separator handling, no
    prefix matching - `SR-SP` and `SEC-SP` are different tokens and must not
    resolve here."""
    if not token:
        return None
    for row in SOURCE_RARITY_RENDERINGS:
        if row.source_name == source_name and row.source_token == token:
            return row
    return None
