"""The canonical SNKRDUNK listing URL for a mapping, derived from the numeric
listing id alone.

THE PROBLEM THIS SOLVES. SNKRDUNK publishes one listing under two paths:

    https://snkrdunk.com/apparels/{id}            lang="ja"   (Japanese)
    https://snkrdunk.com/en/trading-cards/{id}    lang="en"   (English mirror)

They are the same underlying product - verified live on 2026-08-28 for ids
171994 and 142587, where both paths returned the same card code, rarity and
release product, with the JP title being the Japanese rendering of the English
one. The numeric id is the shared identity.

Discovery walks the English sitemap, so a candidate's `source_url` is the
`/en/trading-cards/{id}` form. The collector, however, validates the fetched
page's `<html lang>` against the print's own language
(snkrdunk_collector/writer.py: `language_mismatch` when they disagree), so a
jp-language print can only ever be priced from the Japanese page. Approving a
jp print against the English mirror therefore produces a mapping that is
correct about *identity* and unusable for *pricing* - exactly what happened to
staging mappings 75 and 76.

WHAT THIS MODULE DOES, AND DELIBERATELY DOES NOT DO. It rewrites the path and
nothing else, using only the id already present in the URL. There is no
network lookup, no fuzzy matching, and no inference about which listing is
meant: `/en/trading-cards/171994` and `/apparels/171994` are the same listing
by construction, and a URL this module cannot parse is REFUSED rather than
guessed at. Language selection comes from the resolved CardPrint, not from the
URL, because the print is what the observation will be attached to.

WHY NOT REWRITE THE CANDIDATE INSTEAD. The candidate records what discovery
actually saw, and that provenance is worth keeping intact. Only the mapping -
the thing the collector fetches - is canonicalised, which is why callers that
join a candidate to its mapping must do so on the listing id (see
`listing_id`), never on URL equality.
"""

from __future__ import annotations

import re

from app.services.exact_print_approval import (
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
    ExactPrintApprovalError,
)

SNKRDUNK_HOST = "snkrdunk.com"

# The two published paths for one listing. Anchored, and the id is digits
# only: a trailing query string or fragment is ignored (discovery URLs carry
# `?slide=right&query_id=...`), but nothing else is accepted.
_LISTING_PATH_RES = (
    re.compile(r"^https://snkrdunk\.com/apparels/(\d+)(?:[/?#].*)?$"),
    re.compile(r"^https://snkrdunk\.com/en/trading-cards/(\d+)(?:[/?#].*)?$"),
)

# card_print.language -> the path that serves that language. Mirrors
# snkrdunk_collector/writer.py's CARD_PRINT_LANGUAGE_TO_HTML_LANG, which is
# what actually enforces the pairing at collection time; if the two ever
# disagree, the collector wins and this module is wrong.
_LANGUAGE_PATHS = {
    "jp": "https://snkrdunk.com/apparels/{listing_id}",
    "en": "https://snkrdunk.com/en/trading-cards/{listing_id}",
}


def listing_id(url: str | None) -> str | None:
    """The numeric listing id shared by both paths, or None if this is not a
    recognised SNKRDUNK listing URL. Never raises - callers that need a
    refusal use `canonical_listing_url`."""
    if not url:
        return None
    for pattern in _LISTING_PATH_RES:
        match = pattern.match(url.strip())
        if match:
            return match.group(1)
    return None


def canonical_listing_url(url: str | None, *, card_print_language: str | None) -> str:
    """The URL a mapping for this print must store, so the collector fetches a
    page in the language the print's own identity check demands.

    Fails closed, and that is the whole point: a URL shape this module does
    not recognise, or a print language it has no path for, is refused rather
    than passed through unchanged. Passing it through would recreate the
    silent failure this exists to prevent - a mapping that looks approved and
    can never be priced.
    """
    parsed_id = listing_id(url)
    if parsed_id is None:
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_URL_NOT_CANONICAL,
            f"{url!r} is not a recognised SNKRDUNK listing URL. Expected "
            f"https://{SNKRDUNK_HOST}/apparels/<id> or "
            f"https://{SNKRDUNK_HOST}/en/trading-cards/<id>, so the collector can be "
            "pointed at the right page; it is never guessed at.",
        )

    template = _LANGUAGE_PATHS.get((card_print_language or "").strip().lower())
    if template is None:
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_URL_NOT_CANONICAL,
            f"No SNKRDUNK page is known to serve card_print language "
            f"{card_print_language!r}. Approving would store a URL the collector "
            "cannot validate against the print's own language.",
        )
    return template.format(listing_id=parsed_id)


def equivalent_listing_urls(url: str | None) -> tuple[str, ...]:
    """Every published URL for the same listing, for callers matching a
    candidate to its mapping across the canonicalisation boundary.

    Exact strings, never a LIKE or a regex: the set is small, closed, and
    derived from the id, so this stays exact matching rather than fuzzy
    matching. Empty when the URL is unrecognised, which makes an unmatchable
    candidate fail closed at the caller.
    """
    parsed_id = listing_id(url)
    if parsed_id is None:
        return ()
    return tuple(t.format(listing_id=parsed_id) for t in _LANGUAGE_PATHS.values())
