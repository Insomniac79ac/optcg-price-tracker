"""Parses Bandai's official artwork variant out of a Card List image address.

WHAT THIS FIELD MEANS. `card_prints.official_artwork_variant` records *which
official artwork* a print carries within its Bandai catalogue/product
evidence, and nothing else. Bandai publishes a bare `CODE.png` and, where a
card has further official artworks, `CODE_pN.png` siblings - giving them all
identical card code, rarity, category and product, and publishing no label
that distinguishes them.

So the value here does NOT mean parallel, manga, special, alt-art, rarity, or
chronological order, and `treatment` must never be inferred from it (see
docs/snkrdunk_identity_authority.md). Two further properties matter: the
suffix numbering spans products, and it is per catalogue - the JP and
Asia-EN catalogues serve byte-identical files under swapped suffixes, so a
variant read from one catalogue is not comparable with one read from
another.

WHAT THIS IS FOR. It is identity-bearing evidence, intended for the future
exact-print dedupe key
`(canonical_card_id, language, release_product_id, official_artwork_variant)`.
This tranche only records it: the verified unique index is unchanged and
still keyed on treatment/artwork_key, and nothing reads this module at
runtime.

WHERE IT COMES FROM. The official asset address only. Never from `treatment`,
never from `artwork_key` (which stays the SHA-256 evidence anchor for the
bytes), and never from a source mapping.
"""

from urllib.parse import urlsplit

# The bare artwork - Bandai's `CODE.png` with no suffix at all.
BASE_VARIANT = "base"

# Bandai's Card List serves every card asset as .png. An unfamiliar extension
# is unrecognised evidence, not something to parse optimistically.
OFFICIAL_IMAGE_SUFFIX = ".png"

# `_p` + a positive integer, e.g. OP01-001_p2.png. No leading zero: `p01` has
# never been observed and would be a second spelling of `p1`, so it is left
# unresolved rather than silently folded.
VARIANT_SEPARATOR = "_p"


def parse_official_artwork_variant(image_url: str | None, card_code: str | None) -> str | None:
    """`'base'`, `'p<N>'`, or None when the address is not resolvable evidence.

    None is the safe state, and every caller must keep it rather than
    guessing: a NULL here means "no official artwork variant has been
    established", which is exactly true for a print with no image, with a
    non-Card-List image, or with an address that does not name its own card.

    The query string is ignored completely - Bandai appends a cache buster
    (`?260630`) that changes without the artwork changing. Only the final
    path basename is inspected.
    """
    if not image_url or not card_code:
        return None

    basename = urlsplit(image_url.strip()).path.rsplit("/", 1)[-1]
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
    # a code - but the `_p` marker must be exactly what Bandai publishes.
    # `_P1` is not an address the catalogue serves, so it is unrecognised
    # evidence rather than a variant to normalise.
    if len(stem) <= len(code) or stem[: len(code)].upper() != code.upper():
        return None

    remainder = stem[len(code) :]
    if not remainder.startswith(VARIANT_SEPARATOR):
        return None

    digits = remainder[len(VARIANT_SEPARATOR) :]
    if not digits.isdigit() or not digits.isascii():
        return None
    if digits.startswith("0"):
        return None

    return f"p{int(digits)}"
