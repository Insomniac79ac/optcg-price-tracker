"""Exact-artwork verification: perceptual hash + aspect ratio comparison of
a SNKRDUNK product's own primary photo against the linked card_print's
official Bandai artwork (card_prints.image_url). Moved out of
spikes/snkrdunk-browser-feasibility/spike.py's compare_artwork, which was
live-validated 2026-08-09 against the real pair for card_print.id=1
(official OP01-001_p2.png vs. SNKRDUNK apparels/104428's product photo):
average_hash distance 3/64, aspect ratio 0.716 vs. 0.7151 (0.13% apart).
Thresholds below carry margin above that observed distance while staying
well below what a genuinely different card's artwork produces.

WHICH PIXELS GET COMPARED, since 2026-08-29. The crop is no longer this
module's own alpha-bbox autocrop; it is `artwork_subject.isolate_subject`, a
byte-identical copy of the crop `services/api`'s artwork matcher uses, so the
collector, the admin artwork preview and the matcher all preprocess the same
source bytes the same way. For a canvas holding one object it returns exactly
the box the old autocrop did - verified unchanged on every SNKRDUNK image and
every official artwork Atlas holds - and for a canvas holding two it isolates
the card instead of spanning both. Quarantined mapping 49 was the case that
proved it: its listing carries a second object, so the old crop reported an
aspect ratio of 1.002 against a card's true 0.723 and refused a photo that was
never wrong.

THE THRESHOLDS AND HASHES BELOW ARE UNCHANGED and are deliberately not shared
with the API. ARTWORK_HASH_DISTANCE_THRESHOLD, ARTWORK_ASPECT_RATIO_TOLERANCE,
ARTWORK_HASH_SIZE and ARTWORK_COMPARE_SIZE are this service's own live pricing
gate, fitted against its own corpus. A better crop is allowed to change which
pixels reach them; nothing here is allowed to change what they accept.
"""

import io
from typing import Any

from snkrdunk_collector.artwork_subject import UnusableImage, isolate_subject

ARTWORK_HASH_DISTANCE_THRESHOLD = 12
ARTWORK_ASPECT_RATIO_TOLERANCE = 0.08  # relative difference, e.g. 0.08 = 8%
ARTWORK_HASH_SIZE = 8
ARTWORK_COMPARE_SIZE = (256, 256)


def compare_artwork(official_bytes: bytes, candidate_bytes: bytes) -> dict[str, Any]:
    """Compare a candidate (SNKRDUNK) product image against the known
    official Bandai artwork. Pure function over raw bytes - independently
    testable offline with small synthetic images, no network required.

    Never requires byte identity. Accounts for background removal (the
    subject is isolated from the canvas) and resolution/compression
    differences (resize to a common normalization size before hashing).
    Fails closed (match=False) on any decode error, on a canvas with no
    isolable subject, or when computed distances exceed the documented
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

    # Fails closed exactly like a decode error: a canvas we cannot pick a
    # subject out of is absent evidence, and absent evidence is never a match.
    # It is reported in its own words because the operator's next move is
    # different - look at the photo, not at the fetch.
    try:
        official_norm = isolate_subject(official_img)
        candidate_norm = isolate_subject(candidate_img)
    except UnusableImage as exc:
        result["error"] = f"unusable_image:{exc}"
        return result

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
