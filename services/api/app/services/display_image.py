"""Presentation-image selection for print-centric public responses.

Canonical Bandai artwork (card_print.image_url / artwork_key) stays the
authoritative *identity* evidence and is never modified here. It does,
however, carry a baked-in "SAMPLE" watermark, so it is a poor thing to show
a collector. This module picks a cleaner *display* image where one has been
independently proven to depict the exact same card_print, and falls back to
the canonical Bandai image otherwise.

Selection priority (first match wins):

1. a marketplace image on an approved, active mapping whose retained
   evidence classifies it VERIFIED_DISPLAY (see DISPLAY_SOURCE_PRIORITY)
2. the canonical Bandai image

Where a chosen marketplace image has also been mirrored into our own R2
bucket and recorded as a verified ``owned_asset``, the *URL* we serve for it
is the R2 one instead of the marketplace CDN's - same image, same evidence,
same `source`, different origin (see _owned_asset_url, and note that it is
gated to an explicit allow-list of prints). The URL is composed from
configuration at read time and no delivery hostname is ever read from the
database, and the response reports which branch supplied it in
``owned_asset_selected`` - "bandai" alone cannot say, because it names both a
verified official asset and the canonical fallback.

That substitution is only made when the ``owned_asset`` record is provably
about *this* image: its digest, byte size and pixel dimensions must match the
display evidence beside it, and its key must be the one the shared
content-addressing rule produces for that digest. This read path cannot ask
R2 whether the object exists - it makes no network call of any kind - so
local consistency with already-verified evidence is the whole of what it can
check, and anything less than all of it keeps the source URL.

A mapping only qualifies when its ``match_explanation_json`` carries a
``display_image`` object that was written by a display-image verification
tranche, asserting all four of: exact print verified, whole card preserved,
no SAMPLE watermark, no overlay *obscuring* the card. Quarantined mappings
(review_status != 'approved') carry no such key and can never contribute -
and the key's own ``card_print_id`` is re-checked against the mapping's
column so a sibling print's image can never cross over.

Three evidence versions exist and each is honoured on its own terms. v1
(SNKRDUNK, 2026-08-13) describes an image with no overlay at all. v2
(Yuyu-Tei, 2026-08-18) describes an image carrying a retailer watermark. v3
(official Card List, 2026-08-18) describes a first-party image carrying the
official SAMPLE overlay. Each later version accepts one further *kind* of
non-obscuring mark, and must record that mark explicitly - a watermark or a
SAMPLE is never implied to be absent by omission, and never accepted
implicitly. Earlier evidence is never rewritten or reinterpreted.

Everything read here is structured JSON already stored on the mapping row.
Nothing in this module parses raw_snapshots HTML: a source whose product
image URL lives only in retained HTML has that URL extracted by its
migration, which then persists structured evidence for this module to read.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardPrint, Source, SourceCardMapping
from app.schemas import (
    DisplayImageCanvasOut,
    DisplayImageCardBoxOut,
    DisplayImageGeometryOut,
    DisplayImageOut,
)
from app.services.display_image_object_key import (
    OBJECT_KEY_MEDIA_TYPES,
    object_key as build_object_key,
)
from app.services.object_storage import (
    InvalidObjectKey,
    R2ConfigurationError,
    public_url_for_key,
    validate_object_key,
)

BANDAI = "bandai"

# Prints served from our own R2 copy instead of the source marketplace CDN.
#
# Deliberately still an explicit allow-list, not "every mapping that happens
# to carry an owned_asset": a print must never switch origin merely because a
# record appeared next to it. Widened from {1} to the twenty current prints on
# 2026-08-18, once every one of their Yuyu-Tei assets had been mirrored and
# re-verified end to end (source == private == public digest, decoded size
# confirmed) and its evidence had passed the owned-asset qualification checks
# below. A twenty-first print gets added here only after the same proof.
OWNED_ASSET_PRINT_IDS: frozenset[int] = frozenset(range(1, 21))

# Only ever the provider this repository actually writes (see
# app.services.display_image_asset_persist.PROVIDER). An owned_asset naming
# anything else was not written by that module, so its object_key is not
# addressable under R2_PUBLIC_BASE_URL.
OWNED_ASSET_PROVIDER = "cloudflare_r2"

# The only verification that licenses a switch of origin: the source bytes,
# the authenticated R2 GET and the unauthenticated public GET all hashed and
# agreeing (app.services.display_image_asset_persist.VERIFICATION_METHOD). A
# record produced by anything weaker - or by a future method whose guarantees
# this reader does not know - is not usable here.
OWNED_ASSET_VERIFICATION_METHOD = "source_private_public_sha256"

# Present, a string, and non-blank. Nothing is defaulted: a record missing any
# of these was not written by the persistence module and is not trusted.
OWNED_ASSET_REQUIRED_STR = (
    "provider",
    "object_key",
    "sha256",
    "content_type",
    "cache_control",
    "verified_at",
    "verification_method",
)

# Present and a positive int. Bools are rejected - in Python they are ints,
# and a bool in any of these means malformed evidence.
OWNED_ASSET_REQUIRED_INT = ("byte_size", "width", "height")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Marketplace sources trusted to supply a display image, best first.
#
# Yuyu-Tei was excluded until 2026-08-18 because every one of its images
# carries a "yuyu-tei.jp" retailer overlay. The approved MVP display policy
# accepts that watermark - it does not materially obscure the card - and the
# image-quality audit of the same date found Yuyu-Tei materially better than
# SNKRDUNK on every measured axis (1.34x linear resolution, neutral tone, no
# crushed blacks, no colour cast), so it now ranks first.
#
# The official ONE PIECE Card List ranks first as of 2026-08-18: it is the
# first-party source, its digest equals card_prints.artwork_key on all twenty
# prints, and its SAMPLE overlay is accepted by the approved display policy.
# It is spelled "bandai" because that is the identifier this codebase has
# always used for onepiece-cardgame.com (see BANDAI above) - the audit proved
# the Card List assets are byte-identical to our canonical images, so giving
# the same source a second name would only oblige every reader to know both.
#
# Lower-priority sources are not weakened: this tuple only decides *order
# between sources that already qualify*. An official mapping whose evidence
# does not qualify contributes nothing, and Yuyu-Tei is used instead - then
# SNKRDUNK - rather than the print failing.
DISPLAY_SOURCE_PRIORITY: tuple[str, ...] = ("bandai", "yuyutei", "snkrdunk")

# Evidence written by the Yuyu-Tei migration (2026-08-18). Its contract
# differs from v1 in one way only: a retailer watermark may be present, and
# must then be recorded as present rather than omitted.
VERIFICATION_VERSION_V2 = "display-image-v2"

# Evidence written by the official Card List migration (2026-08-18). It allows
# the official SAMPLE overlay - and only that, only when the evidence names
# the policy that accepts it.
VERIFICATION_VERSION_V3 = "display-image-v3"

# The one value of `overlay_policy` that licenses `sample_present: true`. A
# payload that sets the flag without naming this policy is malformed, not
# permitted: the SAMPLE can never be accepted implicitly.
OFFICIAL_SAMPLE_ACCEPTED = "official_sample_accepted"

_REQUIRED_TRUE = ("exact_print_verified", "full_card_preserved")

# An overlay that obscures the card fails in every version of the contract.
_REQUIRED_FALSE = ("overlay_obscures_card",)

# v2 evidence must state the retailer-overlay fact explicitly, as a real
# boolean. Historical v1 evidence carries no such key and is not reinterpreted
# - see _qualifies.
_REQUIRED_BOOL_V2 = ("retailer_overlay_present",)


def _qualifies(payload: object, card_print_id: int) -> bool:
    """A retained display_image payload is usable only if it makes every
    display-contract assertion explicitly, and claims the print we are
    actually rendering.

    `overlay_obscures_card` must be false in every version of the contract.
    What each later version changed is only which *kind* of non-obscuring mark
    may be present, and each has to say so explicitly:

      v1  no overlay at all (SNKRDUNK)
      v2  a retailer watermark may be present, recorded in
          `retailer_overlay_present`
      v3  the official SAMPLE overlay may be present, recorded in
          `sample_present` and licensed by `overlay_policy`

    Outside v3, `sample_present` must still be false: a SAMPLE is never
    accepted implicitly, and evidence that omits a version's assertion fails
    closed rather than being read as "no mark".
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("classification") != "VERIFIED_DISPLAY":
        return False
    if not all(payload.get(k) is True for k in _REQUIRED_TRUE):
        return False
    if not all(payload.get(k) is False for k in _REQUIRED_FALSE):
        return False

    version = payload.get("verification_version")
    if version == VERIFICATION_VERSION_V3:
        # A true `sample_present` is only meaningful beside the policy that
        # accepts it; the flag alone is malformed evidence.
        if payload.get("overlay_policy") != OFFICIAL_SAMPLE_ACCEPTED:
            return False
        if not isinstance(payload.get("sample_present"), bool):
            return False
    elif payload.get("sample_present") is not False:
        return False

    if version == VERIFICATION_VERSION_V2:
        if not all(isinstance(payload.get(k), bool) for k in _REQUIRED_BOOL_V2):
            return False
    # Guards against a sibling print's evidence being read onto this print.
    if payload.get("card_print_id") != card_print_id:
        return False
    url = payload.get("url")
    return isinstance(url, str) and url.startswith("https://")


def _ints(value: object, count: int) -> list[int] | None:
    """A list of exactly `count` real integers, or None. Bools are rejected -
    in Python they are ints, and a bool here means malformed evidence."""
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        out.append(item)
    return out


def _geometry(payload: dict) -> DisplayImageGeometryOut | None:
    """Convert retained evidence geometry into the public contract, or None.

    The stored `card_bbox_px` is `[left, top, right, bottom]` with *inclusive*
    corners; the public contract is x/y/width/height, so the conversion adds
    one pixel to each span. Returning None is always safe: it just means the
    client presents the image with plain contain rendering, which is the
    behaviour that shipped before this geometry existed.
    """
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict):
        return None

    canvas = _ints(geometry.get("canvas_px"), 2)
    bbox = _ints(geometry.get("card_bbox_px"), 4)
    if canvas is None or bbox is None:
        return None

    canvas_w, canvas_h = canvas
    left, top, right, bottom = bbox
    width, height = right - left + 1, bottom - top + 1

    if canvas_w <= 0 or canvas_h <= 0 or width <= 0 or height <= 0:
        return None
    if left < 0 or top < 0:
        return None
    if left + width > canvas_w or top + height > canvas_h:
        return None

    # The evidence records the card's size separately; if the two disagree the
    # record is internally inconsistent and must not drive presentation.
    card_px = _ints(geometry.get("card_px"), 2)
    if card_px is not None and card_px != [width, height]:
        return None

    return DisplayImageGeometryOut(
        canvas_px=DisplayImageCanvasOut(width=canvas_w, height=canvas_h),
        card_bbox_px=DisplayImageCardBoxOut(x=left, y=top, width=width, height=height),
    )


def _positive_int(value: object) -> int | None:
    """A real positive int, or None. Bools are not ints for this purpose."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _owned_asset_url(payload: dict, card_print_id: int) -> str | None:
    """The public URL of our own mirrored copy, or None to keep the source URL.

    Derived at read time and never stored: the record on the mapping holds a
    provider and an object_key and deliberately no hostname (see
    app.services.display_image_asset_persist), so the delivery origin comes
    from R2_PUBLIC_BASE_URL - one source of truth, changeable per environment
    and replaceable by a custom domain without rewriting any evidence.

    Pure configuration + string work. No client is constructed, nothing is
    read from the database beyond the payload already in hand, and R2 is
    never contacted - a display URL must never cost a network round trip.
    That is also why every check below is a *local consistency* check: this
    function cannot ask R2 whether the object is really there, so what it can
    do instead is refuse to trust a record that disagrees with the verified
    display evidence sitting next to it in the same payload.

    The question being answered is not "does this record look well-formed"
    but "does this record describe *the very image this print was verified
    to show*". So the digest, the byte size and the pixel dimensions must all
    match the display evidence, and the key must be the one the shared
    content-addressing rule produces for that digest. A record that fails any
    of them is describing some other object - which is precisely when
    swapping the URL would put the wrong picture, or no picture, on a
    collector's screen.

    Every failure returns None, which leaves the caller serving the verified
    source URL exactly as before. A missing setting, a malformed base URL, a
    record from another provider, an inconsistent record or a key that fails
    validation are all reasons to keep a working image, never to emit a
    broken one.
    """
    if card_print_id not in OWNED_ASSET_PRINT_IDS:
        return None

    owned = payload.get("owned_asset")
    if not isinstance(owned, dict):
        return None

    # --- shape: every field present, with the right type --------------------
    for name in OWNED_ASSET_REQUIRED_STR:
        value = owned.get(name)
        if not isinstance(value, str) or not value.strip():
            return None
    for name in OWNED_ASSET_REQUIRED_INT:
        if _positive_int(owned.get(name)) is None:
            return None

    if owned["provider"] != OWNED_ASSET_PROVIDER:
        return None
    if owned["verification_method"] != OWNED_ASSET_VERIFICATION_METHOD:
        return None

    digest = owned["sha256"]
    if not _SHA256_RE.match(digest):
        return None

    # --- identity: the same bytes the display evidence was verified against -
    # display_image.fetch.sha256 is the digest of the image this print's
    # display contract was signed off on. If the mirrored object's digest is
    # not that digest, we mirrored something else.
    fetch = payload.get("fetch")
    if not isinstance(fetch, dict):
        return None
    if fetch.get("sha256") != digest:
        return None
    if owned["byte_size"] != _positive_int(fetch.get("bytes")):
        return None

    # --- identity: the same picture the geometry describes ------------------
    # The client is told where the card sits inside canvas_px; serving an
    # object of any other size would make that box point at the wrong pixels.
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if _ints(geometry.get("canvas_px"), 2) != [owned["width"], owned["height"]]:
        return None

    # --- the key: what the shared rule produces for this digest -------------
    key = owned["object_key"]
    try:
        validate_object_key(key)
    except InvalidObjectKey:
        return None
    extension = key.rsplit("/", 1)[-1].rpartition(".")[2]
    if extension not in OBJECT_KEY_MEDIA_TYPES:
        return None
    # Re-derived with the same function the mirror writes with, never by
    # re-stating the prefix/fan-out/naming rules here - a reader and a writer
    # that disagree about the key point at an object that does not exist.
    if key != build_object_key(digest, extension):
        return None
    # Parameters stripped: "image/webp; charset=binary" is still image/webp.
    if owned["content_type"].split(";", 1)[0].strip().lower() != OBJECT_KEY_MEDIA_TYPES[extension]:
        return None

    try:
        return public_url_for_key(key)
    except (R2ConfigurationError, InvalidObjectKey):
        return None


def get_display_images_for_prints(
    db: Session, prints: list[CardPrint]
) -> dict[int, DisplayImageOut]:
    """Resolve one display image per print, in a single mapping query.

    Always returns an entry for every print passed in - falling back to the
    canonical Bandai image - so callers never have to model "no display
    image". Prints whose canonical image_url is itself null are omitted.
    """
    by_print: dict[int, DisplayImageOut] = {}
    print_ids = [p.id for p in prints]
    if not print_ids:
        return by_print

    rows = db.execute(
        select(SourceCardMapping.card_print_id, Source.name, SourceCardMapping.id)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .where(
            SourceCardMapping.card_print_id.in_(print_ids),
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.review_status == "approved",
            Source.name.in_(DISPLAY_SOURCE_PRIORITY),
        )
        .add_columns(SourceCardMapping.match_explanation_json)
        .order_by(SourceCardMapping.id.asc())
    ).all()

    best: dict[int, tuple[int, DisplayImageOut]] = {}
    for card_print_id, source_name, _mapping_id, explanation in rows:
        payload = (explanation or {}).get("display_image")
        if not _qualifies(payload, card_print_id):
            continue
        rank = DISPLAY_SOURCE_PRIORITY.index(source_name)
        if card_print_id in best and best[card_print_id][0] <= rank:
            continue
        # Our own copy when we have one, else the verified source image. Only
        # the URL can change here: source, geometry and exact_print_verified
        # all still describe the same verified asset, because the mirrored
        # bytes are that asset. Which of the two branches supplied the URL is
        # reported as owned_asset_selected - the read path knows it, so no
        # client has to infer it from a hostname.
        owned_url = _owned_asset_url(payload, card_print_id)
        best[card_print_id] = (
            rank,
            DisplayImageOut(
                url=owned_url or payload["url"],
                source=source_name,
                exact_print_verified=True,
                owned_asset_selected=owned_url is not None,
                geometry=_geometry(payload),
            ),
        )

    for print_row in prints:
        chosen = best.get(print_row.id)
        if chosen is not None:
            by_print[print_row.id] = chosen[1]
        elif print_row.image_url:
            # The canonical fallback: the print's own image_url, hotlinked.
            # Same `source` string as a selected official asset, which is why
            # owned_asset_selected has to be explicit here.
            by_print[print_row.id] = DisplayImageOut(
                url=print_row.image_url,
                source=BANDAI,
                exact_print_verified=True,
                owned_asset_selected=False,
            )
    return by_print


def get_display_image_for_print(db: Session, print_row: CardPrint) -> DisplayImageOut | None:
    return get_display_images_for_prints(db, [print_row]).get(print_row.id)
