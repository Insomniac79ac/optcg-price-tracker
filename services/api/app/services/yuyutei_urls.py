"""The canonical Yuyu-Tei listing URL for a mapping, and the listing identity
a candidate and its mapping are joined on.

WHAT YUYU-TEI'S IDENTITY ACTUALLY IS. One product page:

    https://yuyu-tei.jp/sell/opc/card/{set_slug}/{product_id}

and the identity is the PAIR, never the product id alone. Yuyu-Tei numbers
products WITHIN a category: ids 10152-10154 were measured on 2026-09-01 in
both `op01` and `op13`, denoting different cards. That is the same fact
`uq_yuyutei_candidates_set_slug_product` encodes on the candidate table, and
it is why `listing_identity` returns a tuple rather than a string - a
SNKRDUNK-style single numeric id would silently merge two unrelated products.

WHY THIS IS SIMPLER THAN app.services.snkrdunk_urls. SNKRDUNK publishes one
listing under a Japanese and an English path, so canonicalisation there has to
CHOOSE a path from the print's language. Yuyu-Tei publishes one path, so the
canonical URL is the URL - this module rewrites nothing. What it still does,
and what earns its existence, is refuse a URL it cannot parse rather than
letting an unparseable one through into a mapping the collector would then be
unable to fetch.

THE LEGACY FLAT FORM IS NOT A LISTING. Two approved staging mappings predate
product pages entirely:

    https://yuyu-tei.jp/sell/opc/card/OP01-001

That trailing segment is a CARD CODE, not a product id, and it names a card
rather than one of the several products sold under it. `listing_identity`
returns None for it on purpose: treating it as a listing would let an approval
match a candidate against a row that is not about that product, and the
duplicate check would then silently pass or silently fail on the wrong row.
Those rows stay readable and keep working; they are simply not listings.
"""

from __future__ import annotations

import re

from app.services.exact_print_approval import (
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
    ExactPrintApprovalError,
)

YUYUTEI_HOST = "yuyu-tei.jp"

# Anchored. The set slug is the lowercase form Yuyu-Tei uses in its own paths
# (`op01`, `eb01`, `prb01`, `promo-op10`); the product id is digits only, which
# is what excludes the legacy card-code form above. A trailing query string or
# fragment is tolerated and dropped - identity is the pair, not the spelling.
_LISTING_PATH_RE = re.compile(
    r"^https://yuyu-tei\.jp/sell/opc/card/([a-z0-9][a-z0-9-]*)/(\d+)(?:[/?#].*)?$"
)

_CANONICAL = "https://yuyu-tei.jp/sell/opc/card/{set_slug}/{product_id}"


def listing_identity(url: str | None) -> tuple[str, str] | None:
    """`(set_slug, product_id)` for a Yuyu-Tei product page, else None.

    Never raises - callers that need a refusal use `canonical_listing_url`.
    None means "this is not a product listing", which is a real answer for the
    legacy card-code rows and must not be confused with "no mapping exists".
    """
    if not url:
        return None
    match = _LISTING_PATH_RE.match(url.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def canonical_listing_url(url: str | None) -> str:
    """The URL a mapping for this listing must store.

    Fails closed. A URL shape this module does not recognise is refused rather
    than passed through, because passing it through would store a mapping the
    collector cannot fetch - approved-looking and permanently unpriceable.
    """
    identity = listing_identity(url)
    if identity is None:
        raise ExactPrintApprovalError(
            REFUSAL_SOURCE_URL_NOT_CANONICAL,
            f"{url!r} is not a recognised Yuyu-Tei product URL. Expected "
            f"https://{YUYUTEI_HOST}/sell/opc/card/<set-slug>/<product-id>, so the "
            "collector can be pointed at the right page; it is never guessed at.",
        )
    set_slug, product_id = identity
    return _CANONICAL.format(set_slug=set_slug, product_id=product_id)


__all__ = [
    "YUYUTEI_HOST",
    "canonical_listing_url",
    "listing_identity",
]
