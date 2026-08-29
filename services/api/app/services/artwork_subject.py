"""Which pixels of a listing photo get compared - the shared crop.

WHY THIS FILE EXISTS TWICE. `services/api` and `services/snkrdunk_collector`
are separate deployables with separate build contexts and no shared package, so
this module is kept as two byte-identical copies rather than as one import.
`test_artwork_subject_parity` in BOTH test suites compares the two files and
fails if they differ by a single byte, so "two copies" can never quietly become
"two implementations". Change one, run the generator, commit both.

WHAT IT DOES. A background-removed marketplace canvas is not guaranteed to hold
exactly one object. When it holds two, cropping to the whole alpha bounding box
spans both, the resize squashes the card, and every score computed from it is
noise rather than evidence. Staging candidate 10 produced a confident-looking
`no_match` at 112 that way when the card alone scores 24; quarantined mapping 49
produced an aspect ratio of 1.002 against a card's true 0.723 and failed its
collector gate on a picture that was never wrong.

So the crop takes the connected components of the foreground, drops compression
fringe, and keeps the component that dominates. For a canvas holding one object
that is the identical box the old alpha autocrop returned, byte for byte -
verified on all 4,182 official artworks in the catalogue and on every listing
photo Atlas holds. It only changes what happens when a canvas holds more than
one object, or none.

THE RULE IS GEOMETRIC AND GENERAL. Connected components, area and aspect. No
title, card code, product, variant or text; no OCR, no learned model, no
knowledge of any particular listing. It answers "which blob is the subject",
which is a question about pixels.

IT REFUSES RATHER THAN GUESSES. Two comparable objects, no object at all, or a
subject too small or too sliver-shaped to be a photographed card all raise
`UnusableImage`. Both callers must fail closed on that: an image we cannot read
a subject out of is absent evidence, and absent evidence must never eliminate a
printing or confirm a mapping.

WHAT IT IS NOT. It is not a threshold and it carries none. The API's accept and
margin thresholds and the collector's hash-distance and aspect thresholds live
with their own callers and are untouched by this layer.
"""

from __future__ import annotations

from typing import Any

# SUBJECT SELECTION. Not decision thresholds - these govern which pixels are
# hashed, never what a score means. ARTWORK_ACCEPT_MAX and ARTWORK_MARGIN_MIN
# are untouched by this layer.
#
# A background-removed listing canvas is not guaranteed to hold exactly one
# object. When it holds two, cropping to the whole foreground squashes the card
# and every score computed from it is noise - see `subject_bbox`.
FOREGROUND_ALPHA_MIN = 1
# Below this share of the foreground a component is compression fringe or dust,
# not an object competing to be the subject.
REGION_NOISE_SHARE = 0.005
# The subject has to actually dominate. Two comparable objects mean the image
# does not say which one is being sold, and that is a refusal, not a coin toss.
REGION_DOMINANCE_SHARE = 0.60
# Degenerate regions: a card photographed at any sane scale is neither a speck
# nor a sliver. Both bounds are deliberately loose - they exclude nonsense, not
# unusual framing.
MIN_REGION_CANVAS_SHARE = 0.01
MAX_REGION_ASPECT = 6.0


class UnusableImage(ValueError):
    """The image holds nothing that could be a photographed card.

    Deliberately NOT caught as a match of any kind by either caller: an image
    we cannot read the subject out of is absent evidence.
    """


def _find(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union(parent: list[int], left: int, right: int) -> None:
    """Merge toward the lower index, so labelling is order-independent."""
    a, b = _find(parent, left), _find(parent, right)
    if a != b:
        parent[max(a, b)] = min(a, b)


def _foreground_regions(alpha) -> list[tuple[int, tuple[int, int, int, int]]]:
    """Every 8-connected run of opaque pixels, as (area, bbox), largest first.

    Run-length encoded rather than pixel-labelled: a card is one run per row,
    so a 625-row canvas costs a few hundred runs instead of half a million
    pixel visits, and a pathologically speckled alpha channel still stays
    linear because adjacent rows are merged with a two-pointer sweep.

    bbox is (left, top, right, bottom) with right/bottom exclusive - PIL's
    crop convention, and the same convention `Image.getbbox` returns, so a
    single-region image comes out of here byte-identical to the old autocrop.
    """
    import numpy as np

    mask = np.asarray(alpha) >= FOREGROUND_ALPHA_MIN
    height, width = mask.shape
    runs: list[tuple[int, int, int]] = []
    parent: list[int] = []
    previous: list[int] = []

    for row_index in range(height):
        edges = np.diff(np.concatenate(([0], mask[row_index].view(np.int8), [0])))
        starts = np.flatnonzero(edges == 1).tolist()
        stops = np.flatnonzero(edges == -1).tolist()
        current = []
        for start, stop in zip(starts, stops):
            current.append(len(runs))
            runs.append((row_index, start, stop))
            parent.append(len(parent))
        # Both lists are sorted and their runs are disjoint, so one sweep finds
        # every overlap. `<=` rather than `<` is the 8-connectivity: two runs
        # meeting only at a diagonal corner are still one object.
        i = j = 0
        while i < len(current) and j < len(previous):
            _, start, stop = runs[current[i]]
            _, other_start, other_stop = runs[previous[j]]
            if start <= other_stop and other_start <= stop:
                _union(parent, current[i], previous[j])
            if other_stop < stop:
                j += 1
            else:
                i += 1
        previous = current

    areas: dict[int, int] = {}
    boxes: dict[int, tuple[int, int, int, int]] = {}
    for index, (row_index, start, stop) in enumerate(runs):
        root = _find(parent, index)
        areas[root] = areas.get(root, 0) + (stop - start)
        left, top, right, bottom = boxes.get(root, (width, height, 0, 0))
        boxes[root] = (
            min(left, start),
            min(top, row_index),
            max(right, stop),
            max(bottom, row_index + 1),
        )
    # Ties broken on the box itself so the choice never depends on dict order.
    return sorted(
        ((areas[root], boxes[root]) for root in areas), key=lambda r: (-r[0], r[1])
    )


def subject_bbox(alpha, canvas_area: int) -> tuple[int, int, int, int]:
    """The one object in this canvas that the photo is of.

    WHY THIS EXISTS. The old pipeline cropped to `alpha.getbbox()`, the box
    around ALL opaque pixels. That is correct exactly when the canvas holds one
    object, and silently wrong when it holds two: staging candidate 10's
    listing carries the card plus a second item, so the crop spanned both, the
    resize squashed the card, and the closest artwork scored 112 against an
    accept ceiling of 70 - a `no_match` that said nothing about artwork. With
    the card alone the same comparison scores 24 at margin 48.

    THE RULE IS GEOMETRIC AND GENERAL. Take the connected components of the
    foreground, drop fringe, and keep the one that dominates. It reads no
    title, card code, product, variant or text, runs no OCR and no learned
    model, and has no knowledge of any particular candidate - it only answers
    "which blob is the subject", which is a question about pixels.

    IT REFUSES RATHER THAN GUESSES. Two comparable objects, no object at all,
    or a subject too small or too sliver-shaped to be a photographed card all
    raise `UnusableImage`. That is the safe direction: an unusable listing
    yields an `unusable` verdict, and an unusable official leaves its print in
    the surviving set. Neither can eliminate a printing.
    """
    regions = _foreground_regions(alpha)
    if not regions:
        raise UnusableImage("the image is fully transparent")

    foreground = sum(area for area, _ in regions)
    objects = [r for r in regions if r[0] >= foreground * REGION_NOISE_SHARE]
    area, bbox = objects[0]

    if len(objects) > 1:
        kept = sum(a for a, _ in objects)
        if area < kept * REGION_DOMINANCE_SHARE:
            raise UnusableImage(
                f"{len(objects)} comparable objects share this canvas and the largest "
                f"holds only {area / kept:.0%} of it, so the image does not say which "
                "one is being sold"
            )

    if area < canvas_area * MIN_REGION_CANVAS_SHARE:
        raise UnusableImage(
            f"the largest object covers {area / canvas_area:.2%} of the canvas, "
            "too little to be a photographed card"
        )
    left, top, right, bottom = bbox
    aspect = (right - left) / (bottom - top)
    if not 1 / MAX_REGION_ASPECT <= aspect <= MAX_REGION_ASPECT:
        raise UnusableImage(
            f"the largest object has aspect ratio {aspect:.2f}, which is a sliver, "
            "not a card"
        )
    return bbox


def isolate_subject(image: Any) -> Any:
    """The subject of `image`, flattened onto white, as RGB.

    An image with no alpha channel has no background to remove and is returned
    converted, not cropped - the official Bandai assets that carry no
    transparency must come through this function completely unchanged.
    """
    from PIL import Image

    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        rgba = rgba.crop(subject_bbox(rgba.split()[-1], width * height))
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return image.convert("RGB")
