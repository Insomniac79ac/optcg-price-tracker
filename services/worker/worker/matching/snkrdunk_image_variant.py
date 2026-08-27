"""Exact `official_asset_variant` evidence, read off a SNKRDUNK image filename.

WHY THIS IS WORTH HAVING. A card code routinely spans several printings, and
a SNKRDUNK title says at most "-P" / "Parallel" - parallel FAMILY, never which
parallel. On staging, 940 of 2,710 card codes cover more than one active
verified print. Without something that names the exact asset, most listings
can only ever reach "ambiguous".

Some SNKRDUNK CDN filenames name it outright. The 2026-08-27 audit observed
both shapes on live listings:

    OPC-EN-TCG-OP01-001-of.webp      -> base
    OPC-EN-TCG-OP01-001_p1-of.webp   -> p1
    TCG-OPC-ST01-001.webp            -> base
    20220903005802-0.webp            -> nothing (upload timestamp)

The first family encodes the Bandai asset address; the second is an upload
timestamp and says nothing at all.

WHAT THIS IS NOT. There is no perceptual matching here, no hashing, no
approximate comparison and no guessing. A filename either matches a documented
pattern anchored on the card code, or it yields None. `None` is the honest
answer for every filename this module has not been shown to understand, and it
is what the older timestamp uploads return.

THE CARD CODE IS PART OF THE EVIDENCE. The variant is only accepted when the
filename also carries the card code the listing claims. A filename that names
a different card is not weak evidence about this one - it is evidence that
something is wrong, so it returns None rather than a variant.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# The card code as it appears inside a SNKRDUNK filename. What FOLLOWS the
# code decides the variant, and that decision is made in code below rather
# than in one clever pattern - the cases are genuinely different and a single
# regex kept quietly turning malformed tokens into 'base'.
#
# `(?!\d)(?!-\d)` stops "OP01-0011" being read as "OP01-001" while still
# allowing the "-of" suffix the EN uploads carry.
_CODE_RE = re.compile(r"(?P<code>[A-Z]{2,4}\d{2}-\d{3})(?!\d)(?!-\d)", re.IGNORECASE)

# A well-formed Bandai asset suffix: p/r then a positive integer with no
# leading zero, exactly as ck_card_prints_official_asset_variant_format
# requires of the column it will be compared against.
_VARIANT_RE = re.compile(r"^[pr][1-9]\d*$", re.IGNORECASE)

# Filenames that are nothing but an upload timestamp plus an index. Recognised
# explicitly so the "no evidence" answer is a decision rather than a fallthrough.
_TIMESTAMP_RE = re.compile(r"^\d{8,}-\d+$")


def _basename(image_url: str) -> str | None:
    """The filename, with query string and extension removed."""
    if not image_url:
        return None
    path = urlparse(image_url).path
    if not path:
        return None
    name = path.rsplit("/", 1)[-1]
    if not name:
        return None
    # Strip a single extension; SNKRDUNK serves .webp/.png/.jpg.
    return name.rsplit(".", 1)[0] if "." in name else name


def is_timestamp_filename(image_url: str | None) -> bool:
    """True for the older `20220903005802-0` uploads, which carry no evidence."""
    if not image_url:
        return False
    base = _basename(image_url)
    return bool(base and _TIMESTAMP_RE.match(base))


def variant_from_image_url(image_url: str | None, card_code: str | None) -> str | None:
    """The exact `official_asset_variant` this filename names, or None.

    Returns 'base', 'p<N>' or 'r<N>' only when the filename carries the card
    code the listing claims. Every other input - a timestamp upload, a missing
    URL, a filename naming a different card, a malformed variant token -
    returns None, which the caller must treat as "no variant evidence" rather
    than as base.
    """
    if not image_url or not card_code:
        return None
    base = _basename(image_url)
    if not base or _TIMESTAMP_RE.match(base):
        return None

    wanted = card_code.strip().upper()
    for match in _CODE_RE.finditer(base):
        if match.group("code").upper() != wanted:
            # Names a different card: not evidence about this listing.
            continue
        rest = base[match.end():]
        if not rest.startswith("_"):
            # Nothing qualifies the code, so it is the base asset. The "-of"
            # suffix the EN uploads carry falls here.
            return "base"
        # An underscore says the filename MEANT to qualify the asset. If what
        # follows is not a well-formed suffix, the honest answer is "unknown",
        # never "base" - a malformed token is a reason to trust the filename
        # less, not to fall back to the most common value.
        token = rest[1:].split("-", 1)[0].split("_", 1)[0]
        if _VARIANT_RE.match(token):
            return token.lower()
        return None
    return None
