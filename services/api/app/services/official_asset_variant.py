"""Parses Bandai's official asset variant out of a Card List image address.

WHAT THIS FIELD MEANS. `card_prints.official_asset_variant` records *which
official Bandai asset* a print carries within its catalogue/product evidence,
and nothing else. Bandai publishes a bare `CODE.png` and, where a card has
further official assets, `CODE_pN.png` and `CODE_rN.png` siblings - giving them
all the same card code and publishing no label that distinguishes them.

WHY "ASSET" AND NOT "ARTWORK". The field was originally named
`official_artwork_variant`, which promised more than the evidence supports: the
suffix identifies the official asset/occurrence, not a guarantee of different
artwork. The complete 2026-08-22 JP corpus contains **152 rN assets whose bytes
are byte-for-byte identical to a base asset**. Calling those "a different
artwork" would have been false, so the name was corrected to match what the
suffix actually discriminates.

THE CONTRACT.

  * The asset variant is **identity-bearing source evidence** - it is the
    artwork component of the exact-print key
    `(canonical_card_id, language, release_product_id, official_asset_variant)`.
  * It says **nothing** about parallel, manga, special, alt-art or rarity, and
    `treatment` must never be inferred from it (see
    docs/snkrdunk_identity_authority.md). The corpus bears this out: the
    p-family spans every rarity Bandai publishes, and every one of the 459
    rN assets with a base sibling carries the *same* rarity as that sibling.
  * **Identical image bytes may still be distinct print identities.** When the
    product or the asset variant differs, the printings are different even
    though `artwork_key` - the SHA-256 of the bytes - is equal. `artwork_key`
    stays evidence; it is not identity, and it never was.

Two further properties matter: the suffix numbering spans products, and it is
per catalogue - the JP and Asia-EN catalogues serve byte-identical files under
swapped suffixes, so a variant read from one catalogue is not comparable with
one read from another.

WHERE IT COMES FROM. The official asset address only. Never from `treatment`,
never from `artwork_key`, and never from a source mapping.

THE GRAMMAR. Established by measuring the whole published JP catalogue on
2026-08-22 (4,962 occurrences): `base` 2,821, `p1`-`p10` 1,680, `r1`-`r3` 461,
and nothing else - no other family, and no unparseable official basename.
"""

from urllib.parse import urlsplit

# The bare asset - Bandai's `CODE.png` with no suffix at all.
BASE_VARIANT = "base"

# Bandai's Card List serves every card asset as .png. An unfamiliar extension
# is unrecognised evidence, not something to parse optimistically.
OFFICIAL_IMAGE_SUFFIX = ".png"

# The suffix letters the catalogue actually publishes. Deliberately a closed
# set rather than "any letter": an unknown family is unrecognised evidence a
# human must look at, exactly as `_rN` was before it was measured and admitted
# here. Extending this set is a decision, not a parse.
VARIANT_LETTERS = ("p", "r")

VARIANT_SEPARATOR = "_"


def parse_official_asset_variant(image_url: str | None, card_code: str | None) -> str | None:
    """`'base'`, `'p<N>'`, `'r<N>'`, or None when the address is not resolvable.

    None is the safe state, and every caller must keep it rather than
    guessing: a NULL here means "no official asset variant has been
    established", which is exactly true for a print with no image, with a
    non-Card-List image, or with an address that does not name its own card.

    The query string and fragment are ignored completely - Bandai appends a
    cache buster (`?260821`) that changes without the asset changing. Only the
    final path basename is inspected.
    """
    if not image_url or not card_code:
        return None

    split = urlsplit(image_url.strip())
    basename = split.path.rsplit("/", 1)[-1]
    if not basename.lower().endswith(OFFICIAL_IMAGE_SUFFIX):
        return None

    stem = basename[: -len(OFFICIAL_IMAGE_SUFFIX)]
    code = card_code.strip()
    if not code:
        return None

    # The basename must name *this* print's card. A mismatch is a wrong asset,
    # not a variant - the single most important thing this parser refuses to
    # paper over.
    if stem.upper() == code.upper():
        return BASE_VARIANT

    # The card code is compared case-insensitively - case is not identity for
    # a code - but the suffix marker must be exactly what Bandai publishes.
    # `_P1` is not an address the catalogue serves, so it is unrecognised
    # evidence rather than a variant to normalise.
    if len(stem) <= len(code) or stem[: len(code)].upper() != code.upper():
        return None

    remainder = stem[len(code) :]
    if not remainder.startswith(VARIANT_SEPARATOR):
        return None

    marker = remainder[len(VARIANT_SEPARATOR) :]
    if not marker:
        return None

    letter, digits = marker[0], marker[1:]
    if letter not in VARIANT_LETTERS:
        return None
    if not digits.isdigit() or not digits.isascii():
        return None
    # No leading zero: `p01` has never been observed and would be a second
    # spelling of `p1`, so it is left unresolved rather than silently folded.
    # `p0` is not a positive index and is refused for the same reason.
    if digits.startswith("0"):
        return None

    return f"{letter}{int(digits)}"
