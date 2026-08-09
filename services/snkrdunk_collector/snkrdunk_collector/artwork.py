"""Exact-artwork verification: perceptual hash + aspect ratio comparison of
a SNKRDUNK product's own primary photo against the linked card_print's
official Bandai artwork (card_prints.image_url). Moved out of
spikes/snkrdunk-browser-feasibility/spike.py's compare_artwork, which was
live-validated 2026-08-09 against the real pair for card_print.id=1
(official OP01-001_p2.png vs. SNKRDUNK apparels/104428's product photo):
average_hash distance 3/64, aspect ratio 0.716 vs. 0.7151 (0.13% apart).
Thresholds below carry margin above that observed distance while staying
well below what a genuinely different card's artwork produces.
"""

import io
from typing import Any

ARTWORK_HASH_DISTANCE_THRESHOLD = 12
ARTWORK_ASPECT_RATIO_TOLERANCE = 0.08  # relative difference, e.g. 0.08 = 8%
ARTWORK_HASH_SIZE = 8
ARTWORK_COMPARE_SIZE = (256, 256)


def _autocrop_transparent_padding(image: Any) -> Any:
    """If the image carries an alpha channel, crop to the bounding box of
    its non-transparent pixels. SNKRDUNK's background-removed product
    photos are otherwise padded with transparent space inside a canvas of a
    different aspect ratio than the actual card artwork, which would make
    an aspect-ratio/perceptual-hash comparison against the un-padded
    official artwork meaningless."""
    from PIL import Image

    if image.mode not in ("RGBA", "LA") and "transparency" not in image.info:
        return image
    rgba = image.convert("RGBA")
    alpha = rgba.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return image
    cropped = rgba.crop(bbox)
    background = Image.new("RGB", cropped.size, (255, 255, 255))
    background.paste(cropped, mask=cropped.split()[-1])
    return background


def compare_artwork(official_bytes: bytes, candidate_bytes: bytes) -> dict[str, Any]:
    """Compare a candidate (SNKRDUNK) product image against the known
    official Bandai artwork. Pure function over raw bytes - independently
    testable offline with small synthetic images, no network required.

    Never requires byte identity. Accounts for background removal (autocrop
    to alpha bbox) and resolution/compression differences (resize to a
    common normalization size before hashing). Fails closed (match=False) on
    any decode error or when computed distances exceed the documented
    thresholds.
    """
    import imagehash
    from PIL import Image, UnidentifiedImageError

    result: dict[str, Any] = {
        "match": False,
        "thresholds": {
            "hash_distance_max": ARTWORK_HASH_DISTANCE_THRESHOLD,
            "aspect_ratio_tolerance": ARTWORK_ASPECT_RATIO_TOLERANCE,
        },
    }
    try:
        official_img = Image.open(io.BytesIO(official_bytes))
        candidate_img = Image.open(io.BytesIO(candidate_bytes))
    except UnidentifiedImageError as exc:
        result["error"] = f"decode_error:{exc}"
        return result

    official_raw_size = official_img.size
    candidate_raw_size = candidate_img.size

    official_norm = _autocrop_transparent_padding(official_img).convert("RGB")
    candidate_norm = _autocrop_transparent_padding(candidate_img).convert("RGB")

    official_aspect = official_norm.size[0] / official_norm.size[1]
    candidate_aspect = candidate_norm.size[0] / candidate_norm.size[1]
    aspect_diff = abs(official_aspect - candidate_aspect) / official_aspect

    official_resized = official_norm.resize(ARTWORK_COMPARE_SIZE)
    candidate_resized = candidate_norm.resize(ARTWORK_COMPARE_SIZE)

    distances = {}
    for name, fn in (
        ("average_hash", imagehash.average_hash),
        ("dhash", imagehash.dhash),
        ("phash", imagehash.phash),
    ):
        h_official = fn(official_resized, hash_size=ARTWORK_HASH_SIZE)
        h_candidate = fn(candidate_resized, hash_size=ARTWORK_HASH_SIZE)
        distances[name] = int(h_official - h_candidate)

    result.update(
        {
            "official_raw_size": official_raw_size,
            "candidate_raw_size": candidate_raw_size,
            "official_normalized_size": official_norm.size,
            "candidate_normalized_size": candidate_norm.size,
            "official_aspect_ratio": round(official_aspect, 4),
            "candidate_aspect_ratio": round(candidate_aspect, 4),
            "aspect_ratio_relative_diff": round(aspect_diff, 4),
            "hash_distances": distances,
        }
    )

    hash_ok = bool(distances["average_hash"] <= ARTWORK_HASH_DISTANCE_THRESHOLD)
    aspect_ok = bool(aspect_diff <= ARTWORK_ASPECT_RATIO_TOLERANCE)
    result["match"] = bool(hash_ok and aspect_ok)
    result["hash_ok"] = hash_ok
    result["aspect_ok"] = aspect_ok
    return result
