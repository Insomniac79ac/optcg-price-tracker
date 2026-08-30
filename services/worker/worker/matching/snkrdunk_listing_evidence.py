"""What a single SNKRDUNK listing page actually tells us, and nothing more.

Everything here is read off the page. Nothing is inferred, and each field has
a defined "absent" answer that callers must handle rather than paper over.

THREE DECISIONS WORTH READING BEFORE CHANGING ANYTHING.

1. `detected_variant` carries EXACT asset evidence only. A title saying "-P"
   or "Parallel" establishes the parallel FAMILY, not which parallel. The
   exact-print gate compares `detected_variant` to `official_asset_variant`
   by equality, so writing "P" there would make every parallel listing look
   like it CONTRADICTS the catalogue ("no print has variant P") when the truth
   is that the evidence is merely insufficient. Insufficient and contradicted
   are different verdicts and lead the operator to different actions, so the
   field stays empty unless the image filename names the asset outright. The
   parallel-family signal is not lost: it survives verbatim in
   `rarity_token` ("L-P", "SEC-SP") and in the raw title.

2. `detected_set_code` is the RESOLVED Atlas product code or nothing. The
   existing opcg_normalizer derives a set code from the card-code prefix
   (OP02-013 -> OP02), which is the card's ORIGINAL set - not the product this
   printing shipped in. A reprint of OP02-013 carried in PRB-01 would be
   narrowed to OP-02 and wrongly excluded, or worse, wrongly confirmed. So the
   prefix is never used as product evidence here.

3. Language is decided, not guessed. SNKRDUNK marks English printings with a
   literal "[EN]" in the title. Atlas currently holds Japanese print
   identities only, so an English listing is not an unmatched Japanese card -
   it is a different catalogue, and it is kept out of the JP candidate path
   entirely rather than persisted and left to fail matching later.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from worker.matching.snkrdunk_image_variant import (
    is_timestamp_filename,
    variant_from_image_url,
)
from worker.matching.source_product_aliases import resolve_source_product_code

# One Piece card codes as SNKRDUNK prints them, always inside square brackets:
# "Trafalgar law L-P[OP01-002] (Booster Pack ROMANCE DAWN)". Anchoring on the
# brackets is what keeps Pokemon listings ("[s12a 184/172]") out.
_CARD_CODE_RE = re.compile(r"\[([A-Z]{2,4}\d{2}-\d{3})\]")

# The trailing "(...)" group is the product label.
_PRODUCT_RE = re.compile(r"\(([^()]+)\)\s*$")

# The rarity token sits between the character name and the code: "Nami R-P
# [OP01-016]", "Shanks SEC-SP (Comic Parallel) [OP01-120]".
#
# Matched as a WHOLE word rather than by position, because position alone
# picked the tail off ordinary words - "Roronoa Zoro L Parallel [OP01-001]"
# yielded "LLEL". A published rarity is always a standalone all-caps token, so
# the parser takes the last such token before the code: that skips initials
# like the "D" in "Monkey D. Luffy" and mixed-case words like "Parallel".
_RARITY_TOKEN_RE = re.compile(r"^[A-Z]{1,4}(?:-[A-Z]{1,3})?$")

# Parallel FAMILY evidence. Deliberately not turned into a variant.
_PARALLEL_RE = re.compile(r"(?:\bP\b|-P\b|\bParallel\b)", re.IGNORECASE)

_EN_MARKER_RE = re.compile(r"\[EN\]", re.IGNORECASE)

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_META_RE = (
    r'<meta[^>]+(?:property|name)=["\']{}["\'][^>]+content=["\']([^"\']*)["\']'
)
_SUFFIX_RE = re.compile(r"\s*\|\s*SNKRDUNK\s*$", re.I)


@dataclass
class ListingEvidence:
    """Evidence parsed off one listing page. Absent fields are None, never
    filled with a default that reads as a fact."""

    source_url: str
    title: str | None = None
    card_code: str | None = None
    product_label: str | None = None
    resolved_product_code: str | None = None
    rarity_token: str | None = None
    parallel_family: bool = False
    image_url: str | None = None
    # 'base' / 'pN' / 'rN' from the image filename, or None. Exact evidence.
    asset_variant: str | None = None
    image_is_timestamp: bool = False
    language: str | None = None  # 'en' when marked, else 'jp' (SNKRDUNK's default)
    price_jpy: int | None = None
    raw_text: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_one_piece(self) -> bool:
        return self.card_code is not None

    @property
    def is_english(self) -> bool:
        return self.language == "en"


def _meta(html: str, prop: str) -> str | None:
    m = re.search(_META_RE.format(re.escape(prop)), html, re.I)
    return html_lib.unescape(m.group(1)).strip() if m else None


def _clean_title(raw: str | None) -> str | None:
    if not raw:
        return None
    text = html_lib.unescape(raw).strip()
    text = _SUFFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip() or None


def parse_listing(source_url: str, html: str) -> ListingEvidence:
    """Read one listing page into evidence.

    Never raises on odd input: an unparseable page comes back with
    `card_code=None`, which the caller treats as "not a One Piece listing".

    This function's only job is to get `title` and `image_url` OUT of the
    HTML. Every judgement made about them lives in `evidence_from_listing`
    below, so that a caller holding those two strings without the page - the
    offline reparse - reaches identical conclusions by construction rather
    than by a second implementation kept in step by hand.
    """
    if not html:
        ev = ListingEvidence(source_url=source_url)
        ev.notes.append("empty response body")
        return ev

    title = _clean_title((_TITLE_RE.search(html) or [None, None])[1] if _TITLE_RE.search(html) else None)
    return evidence_from_listing(source_url, title, _meta(html, "og:image"))


def evidence_from_listing(
    source_url: str, title: str | None, image_url: str | None
) -> ListingEvidence:
    """The single interpretation of a listing, given its title and image URL.

    Split out of `parse_listing` so the offline reparse can re-derive a stored
    candidate's fields from the evidence already persisted on the row - the
    title and the image URL are the whole of what the derivation ever reads -
    without refetching the page and without a second reading of card code,
    product label, alias, rarity token or asset variant.
    """
    ev = ListingEvidence(source_url=source_url)
    ev.title = title
    ev.raw_text = title
    ev.image_url = image_url
    if ev.image_url:
        ev.image_is_timestamp = is_timestamp_filename(ev.image_url)

    if not title:
        ev.notes.append("no <title>")
        return ev

    code = _CARD_CODE_RE.search(title.upper())
    if not code:
        ev.notes.append("no bracketed One Piece card code in title")
        return ev
    ev.card_code = code.group(1)

    # Language before anything else: an English listing is a different
    # catalogue, and the caller stops there.
    ev.language = "en" if _EN_MARKER_RE.search(title) else "jp"

    product = _PRODUCT_RE.search(title)
    if product:
        ev.product_label = product.group(1).strip()
        # Official titles first, then SNKRDUNK's own product names - see
        # worker.matching.source_product_aliases. The card code is passed
        # because a source alias is honoured only when this listing's own code
        # is a member of the product it names; a code the product does not
        # contain fails closed to None, i.e. to no product evidence at all.
        ev.resolved_product_code = resolve_source_product_code(
            "snkrdunk", ev.product_label, ev.card_code
        )
        if ev.resolved_product_code is None:
            ev.notes.append(f"product label unresolved: {ev.product_label!r}")

    before_code = title[: title.upper().index(f"[{ev.card_code}]")]
    tokens = [t.strip(".,") for t in re.split(r"[\s()]+", before_code) if t]
    published = [t for t in tokens if _RARITY_TOKEN_RE.match(t)]
    ev.rarity_token = published[-1] if published else None

    ev.parallel_family = bool(_PARALLEL_RE.search(title))

    # The only route to an exact variant. Absent for timestamp uploads, which
    # is the honest answer rather than an assumption of 'base'.
    ev.asset_variant = variant_from_image_url(ev.image_url, ev.card_code)
    if ev.asset_variant is None and ev.parallel_family:
        ev.notes.append("parallel family known, exact asset variant unknown")

    return ev
