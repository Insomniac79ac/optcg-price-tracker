"""Which published SNKRDUNK URLs name the same listing.

SNKRDUNK serves one listing under two paths - `/apparels/{id}` (Japanese) and
`/en/trading-cards/{id}` (English mirror) - and the numeric id is the shared
identity. Since 4F-9 the api canonicalises a mapping's `source_url` to the
path matching its print's language, while the candidate keeps whatever
discovery saw. So `candidate.source_url == mapping.source_url` is no longer
true and must not be assumed.

DELIBERATELY MIRRORED, NOT SHARED, from app.services.snkrdunk_urls: the api
and worker are separate deployables with no common package (the same reason
worker.models mirrors app.models). This half is intentionally smaller - the
worker never *chooses* a canonical URL, it only needs to recognise that two
URLs are the same listing.

The returned set is exact strings derived from the id, never a LIKE or a
regex against stored data: matching stays exact, and an unrecognised URL
yields nothing so the caller fails closed rather than matching loosely.
"""

from __future__ import annotations

import re

_LISTING_PATH_RES = (
    re.compile(r"^https://snkrdunk\.com/apparels/(\d+)(?:[/?#].*)?$"),
    re.compile(r"^https://snkrdunk\.com/en/trading-cards/(\d+)(?:[/?#].*)?$"),
)

_LISTING_URL_TEMPLATES = (
    "https://snkrdunk.com/apparels/{listing_id}",
    "https://snkrdunk.com/en/trading-cards/{listing_id}",
)


def listing_id(url: str | None) -> str | None:
    """The numeric listing id shared by both paths, or None."""
    if not url:
        return None
    for pattern in _LISTING_PATH_RES:
        match = pattern.match(url.strip())
        if match:
            return match.group(1)
    return None


def equivalent_listing_urls(url: str | None) -> tuple[str, ...]:
    """Every published URL for this listing.

    Falls back to the URL itself when it is not a recognised listing URL, so
    a legacy mapping stored under some other shape can still be found by its
    own exact URL - widening this to nothing would silently stop pricing rows
    that work today.
    """
    parsed_id = listing_id(url)
    if parsed_id is None:
        return (url,) if url else ()
    return tuple(t.format(listing_id=parsed_id) for t in _LISTING_URL_TEMPLATES)
