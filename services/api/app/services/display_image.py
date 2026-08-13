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

A mapping only qualifies when its ``match_explanation_json`` carries a
``display_image`` object that was written by the display-image verification
tranche, asserting all four of: exact print verified, whole card preserved,
no SAMPLE watermark, no overlay obscuring the card. Quarantined mappings
(review_status != 'approved') carry no such key and can never contribute -
and the key's own ``card_print_id`` is re-checked against the mapping's
column so a sibling print's image can never cross over.

Everything read here is structured JSON already stored on the mapping row.
Nothing in this module parses raw_snapshots HTML - see
docs/display_image_verification_tranche_2026-08-13.pdf for why that
constraint exists (Yuyu-Tei's product image URLs live only in retained HTML,
which is why Yuyu-Tei contributes no display images and is absent below).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardPrint, Source, SourceCardMapping
from app.schemas import (
    DisplayImageCanvasOut,
    DisplayImageCardBoxOut,
    DisplayImageGeometryOut,
    DisplayImageOut,
)

BANDAI = "bandai"

# Marketplace sources trusted to supply a display image, best first. Yuyu-Tei
# is deliberately absent: all 20 of its exact-product images were verified on
# 2026-08-13 and every one carries a "yuyu-tei.jp" retailer overlay across the
# artwork and card-name band, so none qualified.
DISPLAY_SOURCE_PRIORITY: tuple[str, ...] = ("snkrdunk",)

_REQUIRED_TRUE = ("exact_print_verified", "full_card_preserved")
_REQUIRED_FALSE = ("sample_present", "overlay_obscures_card")


def _qualifies(payload: object, card_print_id: int) -> bool:
    """A retained display_image payload is usable only if it makes every
    display-contract assertion explicitly, and claims the print we are
    actually rendering."""
    if not isinstance(payload, dict):
        return False
    if payload.get("classification") != "VERIFIED_DISPLAY":
        return False
    if not all(payload.get(k) is True for k in _REQUIRED_TRUE):
        return False
    if not all(payload.get(k) is False for k in _REQUIRED_FALSE):
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
        best[card_print_id] = (
            rank,
            DisplayImageOut(
                url=payload["url"],
                source=source_name,
                exact_print_verified=True,
                geometry=_geometry(payload),
            ),
        )

    for print_row in prints:
        chosen = best.get(print_row.id)
        if chosen is not None:
            by_print[print_row.id] = chosen[1]
        elif print_row.image_url:
            by_print[print_row.id] = DisplayImageOut(
                url=print_row.image_url, source=BANDAI, exact_print_verified=True
            )
    return by_print


def get_display_image_for_print(db: Session, print_row: CardPrint) -> DisplayImageOut | None:
    return get_display_images_for_prints(db, [print_row]).get(print_row.id)
