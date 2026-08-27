"""The one place two published rarity tokens are known to mean one thing.

WHY THIS EXISTS. Bandai's Japanese catalogue publishes the same special-art
printing category under two tokens - `SPカード` on almost every occurrence and
`SP P` on one - while the English catalogue publishes both as `SP CARD`. Served
raw, the print catalogue's rarity facet therefore offered a collector two
options that are the same thing, one of which selected a single print, and
neither of which was a word anybody uses. Collapsing them in a component would
have fixed the dropdown and left the *filter* still splitting the population in
two, so the aliasing lives here, below both, and both the facet and the
`?rarity=` filter go through it.

WHAT AN ALIAS IS, AND WHAT IT IS NOT. An alias is a many-to-one mapping applied
at QUERY TIME only:

  * `facet_value()` folds each stored token into the value the catalogue
    offers, so `SPカード` and `SP P` collapse into one `SP CARD` option whose
    population is the sum of both.
  * `filter_tokens()` expands a requested value back into every stored token it
    covers, so filtering on that one option reaches both.

Nothing here reads or writes `card_prints.official_rarity`. No stored value is
normalised, migrated or mutated, the exact token Bandai published stays on the
row and stays on the wire in `rarity`, and the raw token remains the thing a
detail page can quote as provenance. Turning this module off would restore the
previous behaviour exactly.

FAIL-SAFE, THE SAME RULE AS EVERYWHERE ELSE. A token in no alias group is its
own facet value and its own filter token - the identity mapping. So a rarity
Bandai invents next release is offered and filtered unchanged rather than
disappearing into a bucket, and an explicit `?rarity=SPカード` still selects
exactly the prints that carry it. Only membership listed below is ever merged.

TR IS NOT AN ALIAS OF ANYTHING. Treasure Rare is a separate token in both
catalogues and is language-specific; merging it into SP Card would flatten a
distinction Bandai does make. It appears nowhere in this module for that
reason.

The collector-facing labels for these values live in the frontend's
`apps/web/src/lib/terminology.ts`, which owns the same `SP CARD` constant.
"""

from __future__ import annotations

# Bandai's own English-catalogue token for the category. Deliberately the
# published word rather than an invented slug: it is what a collector sees in
# the dropdown and what a shared/bookmarked `?rarity=` URL carries.
SP_CARD = "SP CARD"

# alias value -> the stored tokens it covers, in catalogue order.
#
# Every member here must be a token that genuinely names the SAME collector
# concept. A near-synonym, a differently-scoped token, or a token that is
# merely rarer does not belong: the point is to stop offering a distinction
# Bandai does not make, not to tidy the dropdown.
ALIAS_MEMBERS: dict[str, tuple[str, ...]] = {
    SP_CARD: ("SPカード", "SP P"),
}

_MEMBER_TO_ALIAS: dict[str, str] = {
    member: alias for alias, members in ALIAS_MEMBERS.items() for member in members
}


def facet_value(stored_rarity: str) -> str:
    """The catalogue-facing value for one stored rarity token.

    Identity for anything not explicitly aliased, so an unknown token stays
    exactly itself and stays selectable.
    """
    return _MEMBER_TO_ALIAS.get(stored_rarity, stored_rarity)


def facet_values(stored_rarities: list[str]) -> list[str]:
    """Distinct catalogue-facing values for a list of stored tokens.

    Sorted, and deduplicated after folding, so an alias contributes exactly one
    option however many stored tokens it covers.
    """
    return sorted({facet_value(value) for value in stored_rarities if value is not None})


def filter_tokens(requested: str) -> tuple[str, ...]:
    """Every stored token a requested filter value should match.

    An alias expands to its whole membership - that is what makes the SP Card
    option's population the sum of both source tokens. Anything else, including
    a raw member token requested directly, matches only itself.
    """
    return ALIAS_MEMBERS.get(requested, (requested,))
