"""Artwork as an exact-print evidence channel.

WHAT THIS IS FOR. One card code routinely spans several printings, and the
source's card code plus product label often cannot separate them - that is the
`evidence_cannot_distinguish_print` refusal in exact_print_approval. The
listing's own product photo can, because a parallel printing is a different
artwork. This module turns that photo into structured, auditable evidence.

WHAT IT CAN AND CANNOT PROVE, STATED PRECISELY. An image identifies an
ARTWORK, never a PRINT. Bandai reprints a card by publishing the *same*
artwork file under a new print: OP04-044 base and its `r1` reprint are
byte-identical downloads (sha256 14a083e9..), as are OP01-120 base and `r1`
(4a996805..). No image method can ever separate those, and any method claiming
to would be reporting noise. So prints are first collapsed into artwork
CLASSES, and an exact print is returned only when the winning class has
exactly one surviving member. Everything else is reported as ambiguous.

WHY EXACT EQUIVALENCE, NOT A FUZZY THRESHOLD. Two prints join a class only
when their official artwork is byte-identical. Bandai's own files make this
sufficient - the reprint pairs above are identical at source - so nothing is
gained by merging "similar" official artworks, and a fuzzy merge would be
actively dangerous: it could silently fuse two genuinely different printings
and make a wrong answer unreachable rather than merely ambiguous.

Atlas ALREADY STORES THAT IDENTITY: `card_prints.artwork_key` is the SHA-256
of the official Bandai asset, and the reprint pairs above share it exactly
(OP04-044 base/r1 = 14a083e9.., OP01-120 base/r1 = 4a996805..). Callers that
have the prints in hand should pass those keys straight in - no image bytes,
no migration, and the class is exactly what the catalogue already asserts.
`official_artwork_digest` exists for offline preparation where a key is not
available, and hashes normalised pixels so a re-encode of one artwork still
collapses onto the same class.

WHAT IT NEVER DOES. It never widens a candidate set - it only removes prints
from a set some other evidence channel already allowed. It never fetches
anything: callers pass image bytes in. It has no access to the card code,
product label, variant or title, so an image score cannot be manufactured from
metadata it was not given.

WHICH PIXELS GET COMPARED. A background-removed listing canvas can hold more
than the card. Cropping to the whole foreground then squashes the card and
every score derived from it is noise rather than evidence - staging candidate
10 produced a confident-looking `no_match` at 112 that way, when the card
alone scores 24. `_subject_bbox` therefore picks the dominant connected
component of the foreground and refuses when no single object dominates. The
rule is geometric: connected components, area and aspect. No text, no OCR, no
learned model, no per-candidate knowledge.

THRESHOLDS ARE PROVISIONAL. See ARTWORK_METHOD_VERSION. They were fitted on a
control corpus of exact prints whose listing photo and official artwork are
both known, where correct matches scored <= 56 and the nearest different
artwork >= 102. They are deliberately set inside that gap and must not be
loosened to raise coverage; the feature stays disabled by default until the
control corpus is large enough to justify enabling it.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

# Bumped whenever the pipeline or thresholds change, and recorded on every
# verdict so a stored decision can always be traced to how it was reached.
ARTWORK_METHOD_VERSION = "artwork-evidence/phash16-v2"

# PROVISIONAL. Fitted on the 4F control corpus; see the module docstring.
# Enabling behaviour is a separate decision (settings.ARTWORK_EVIDENCE_ENABLED).
ARTWORK_ACCEPT_MAX = 70
ARTWORK_MARGIN_MIN = 40

NORMALIZE_SIZE = (256, 256)
PHASH_SIZE = 16

# SUBJECT SELECTION. Not decision thresholds - these govern which pixels are
# hashed, never what a score means. ARTWORK_ACCEPT_MAX and ARTWORK_MARGIN_MIN
# are untouched by this layer.
#
# A background-removed listing canvas is not guaranteed to hold exactly one
# object. When it holds two, cropping to the whole foreground squashes the card
# and every score computed from it is noise - see `_subject_bbox`.
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

    Raised by `_normalize` and deliberately NOT caught as a match of any kind:
    an image we cannot read the subject out of is absent evidence, and absent
    evidence never eliminates a printing.
    """


STATUS_EXACT = "exact"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNUSABLE = "unusable"
STATUS_NO_MATCH = "no_match"


@dataclass(frozen=True)
class ArtworkVerdict:
    """Structured evidence, never a bare print id.

    `card_print_ids_before`/`_after` are what makes this auditable: a reader
    can see exactly which prints the image removed, and a verdict that
    removed nothing is visible as such.
    """

    status: str
    method_version: str = ARTWORK_METHOD_VERSION
    card_print_id: int | None = None
    winning_class: tuple[int, ...] = ()
    best_score: int | None = None
    runner_up_score: int | None = None
    margin: int | None = None
    card_print_ids_before: tuple[int, ...] = ()
    card_print_ids_after: tuple[int, ...] = ()
    detail: str | None = None
    scores: dict[int, int] = field(default_factory=dict)

    @property
    def is_exact(self) -> bool:
        return self.status == STATUS_EXACT

    @property
    def narrowed(self) -> bool:
        return bool(self.card_print_ids_after) and len(self.card_print_ids_after) < len(
            self.card_print_ids_before
        )

    def as_evidence_note(self) -> str:
        return (
            f"listing artwork (score {self.best_score}, "
            f"margin {self.margin} to nearest different artwork)"
        )


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


def _subject_bbox(alpha, canvas_area: int) -> tuple[int, int, int, int]:
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


def _normalize(image_bytes: bytes):
    """Decode -> isolate the subject -> flatten -> fixed size RGB.

    Isolating the subject is the important step: SNKRDUNK's background-removed
    photos pad the card inside a canvas of a different shape, so without it the
    comparison is dominated by transparent margin rather than by the card. For
    a canvas holding one object this is exactly the old alpha autocrop, byte
    for byte; `_subject_bbox` only changes what happens when it holds more than
    one, or none. snkrdunk_collector.artwork still carries the single-object
    version of this crop - it is a separate deployable with its own live
    thresholds and is deliberately not touched here.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        rgba = rgba.crop(_subject_bbox(rgba.split()[-1], width * height))
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        image = flat
    else:
        image = image.convert("RGB")
    return image.resize(NORMALIZE_SIZE, Image.LANCZOS)


def official_artwork_digest(image_bytes: bytes) -> str:
    """The artwork class key: SHA-256 of the normalised pixel bytes.

    Exact by construction - two prints share a class only when their official
    artwork normalises to identical pixels. See the module docstring for why
    this is not a similarity threshold.
    """
    return hashlib.sha256(_normalize(image_bytes).tobytes()).hexdigest()


def _phash(image):
    import imagehash

    return imagehash.phash(image, PHASH_SIZE)


def compare(listing_bytes: bytes, official_bytes: bytes) -> int:
    """Perceptual distance between a listing photo and official artwork.
    Lower is closer. Pure pixels: no metadata of any kind is consulted."""
    return int(_phash(_normalize(listing_bytes)) - _phash(_normalize(official_bytes)))


def evaluate_artwork(
    listing_bytes: bytes | None,
    official_by_print: dict[int, bytes],
    *,
    artwork_keys: dict[int, str] | None = None,
    accept_max: int = ARTWORK_ACCEPT_MAX,
    margin_min: int = ARTWORK_MARGIN_MIN,
) -> ArtworkVerdict:
    """Rank the allowed prints' artwork classes against one listing photo.

    `official_by_print` must already be restricted to the prints some other
    evidence channel permits - this function cannot widen that set, and does
    not know why a print is in or out.

    `artwork_keys` is `card_prints.artwork_key` per print where the caller has
    it: the catalogue's own SHA-256 of the official asset, which is what
    defines the artwork class. Where a key is missing the class falls back to
    hashing the normalised official pixels, so a print with no key still gets
    a class rather than silently merging with another.
    """
    before = tuple(sorted(official_by_print))

    if not listing_bytes:
        return ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=before,
            card_print_ids_after=before,
            detail="no listing image available",
        )
    if not official_by_print:
        return ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=before,
            card_print_ids_after=before,
            detail="no official artwork for the allowed prints",
        )

    try:
        listing = _normalize(listing_bytes)
        listing_hash = _phash(listing)
    except UnusableImage as exc:
        # A readable image we cannot pick a subject out of. Reported in its own
        # words rather than as a decode failure, because the operator's next
        # move is different: look at the photo, not at the fetch.
        return ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=before,
            card_print_ids_after=before,
            detail=f"no card could be isolated in the listing image: {exc}",
        )
    except Exception as exc:  # decode failures are evidence of nothing
        return ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=before,
            card_print_ids_after=before,
            detail=f"listing image could not be decoded: {type(exc).__name__}",
        )

    scores: dict[int, int] = {}
    classes: dict[str, list[int]] = {}
    for print_id, official in sorted(official_by_print.items()):
        try:
            normalized = _normalize(official)
        except Exception:
            # A print whose official artwork cannot be read is left in the
            # surviving set: absent evidence must never eliminate anything.
            continue
        scores[print_id] = int(listing_hash - _phash(normalized))
        key = (artwork_keys or {}).get(print_id)
        digest = key or hashlib.sha256(normalized.tobytes()).hexdigest()
        classes.setdefault(digest, []).append(print_id)

    if not scores:
        return ArtworkVerdict(
            status=STATUS_UNUSABLE,
            card_print_ids_before=before,
            card_print_ids_after=before,
            detail="no official artwork could be decoded",
        )

    unreadable = [p for p in before if p not in scores]
    class_best = {
        digest: min(scores[p] for p in members) for digest, members in classes.items()
    }
    ranked = sorted(class_best.items(), key=lambda kv: (kv[1], kv[0]))
    best_digest, best = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else None
    margin = None if runner is None else runner - best
    winners = tuple(sorted(classes[best_digest]))

    common = dict(
        method_version=ARTWORK_METHOD_VERSION,
        best_score=best,
        runner_up_score=runner,
        margin=margin,
        winning_class=winners,
        card_print_ids_before=before,
        scores=scores,
    )

    if best > accept_max:
        return ArtworkVerdict(
            status=STATUS_NO_MATCH,
            card_print_ids_after=before,
            detail=(
                f"closest artwork scores {best}, above the accept threshold "
                f"{accept_max}: this photo does not depict any allowed printing"
            ),
            **common,
        )
    if margin is not None and margin < margin_min:
        return ArtworkVerdict(
            status=STATUS_AMBIGUOUS,
            card_print_ids_after=before,
            detail=f"margin {margin} below {margin_min}: artworks are too close to separate",
            **common,
        )
    # The set the image supports: the winning class, plus anything unreadable,
    # since absent evidence cannot eliminate a print.
    after = tuple(sorted(set(winners) | set(unreadable)))
    if len(after) > 1:
        return ArtworkVerdict(
            status=STATUS_AMBIGUOUS,
            card_print_ids_after=after,
            detail=(
                f"prints {list(after)} share one artwork (or could not be read), "
                "so the image selects the artwork but not the printing"
            ),
            **common,
        )
    return ArtworkVerdict(
        status=STATUS_EXACT, card_print_id=after[0], card_print_ids_after=after, **common
    )
