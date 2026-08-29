"""The crop is shared with services/api, and these tests are what keeps it shared.

`snkrdunk_collector/artwork_subject.py` and
`services/api/app/services/artwork_subject.py` are two copies of one file,
because the two services are separate deployables with separate build contexts
and no shared package. The first test below is the whole reason that is
acceptable: if anyone edits one copy, this fails.

The rest pin what the collector is and is not allowed to inherit from that
sharing - the crop, yes; the thresholds, never.
"""

import io
import pathlib

import pytest
from PIL import Image

from snkrdunk_collector import artwork_subject
from snkrdunk_collector.artwork import (
    ARTWORK_ASPECT_RATIO_TOLERANCE,
    ARTWORK_COMPARE_SIZE,
    ARTWORK_HASH_DISTANCE_THRESHOLD,
    ARTWORK_HASH_SIZE,
    compare_artwork,
)

HERE = pathlib.Path(__file__).resolve()
COLLECTOR_COPY = HERE.parents[1] / "snkrdunk_collector" / "artwork_subject.py"


def _api_copy() -> pathlib.Path | None:
    """The API's copy, if the repo root is visible (it is not inside the
    deployed collector image, where this service ships alone)."""
    for parent in HERE.parents:
        candidate = parent / "services" / "api" / "app" / "services" / "artwork_subject.py"
        if candidate.exists():
            return candidate
    return None


def test_the_two_copies_of_the_shared_crop_are_byte_identical():
    """Two copies, one implementation. If this fails, the collector and the API
    have started preprocessing the same bytes differently, and every artwork
    comparison either side makes is now answering a slightly different question
    than the other one."""
    api = _api_copy()
    if api is None:
        pytest.skip("Repo root not visible; services/api is unavailable here.")
    assert COLLECTOR_COPY.read_bytes() == api.read_bytes(), (
        "artwork_subject.py has drifted between services/api and "
        "services/snkrdunk_collector - regenerate both from one source."
    )


def test_the_shared_module_carries_no_thresholds():
    """The crop may be shared; the pricing gate may not. This module must never
    grow a distance or tolerance the collector could accidentally inherit."""
    numbers = {
        name: getattr(artwork_subject, name)
        for name in dir(artwork_subject)
        if name.isupper()
    }
    assert set(numbers) == {
        "FOREGROUND_ALPHA_MIN",
        "MAX_REGION_ASPECT",
        "MIN_REGION_CANVAS_SHARE",
        "REGION_DOMINANCE_SHARE",
        "REGION_NOISE_SHARE",
    }


def test_the_collector_gate_is_unchanged():
    """Pinned deliberately. This tranche changed which pixels reach the gate.
    It changed nothing about what the gate accepts, and a future crop change
    must not be able to smuggle a threshold move in with it."""
    assert ARTWORK_HASH_DISTANCE_THRESHOLD == 12
    assert ARTWORK_ASPECT_RATIO_TOLERANCE == 0.08
    assert ARTWORK_HASH_SIZE == 8
    assert ARTWORK_COMPARE_SIZE == (256, 256)


def test_numpy_is_declared_in_this_service_requirements():
    """artwork_subject imports numpy lazily, inside `_foreground_regions`. A
    missing lazy dependency does not stop the service starting - it makes every
    comparison fail at the first canvas with an alpha channel, which is exactly
    how the missing ImageHash declaration reached staging unnoticed."""
    requirements = (HERE.parents[1] / "requirements.txt").read_text()
    assert "numpy" in requirements

    import numpy

    assert numpy is not None


# --- what the crop does, over real pixels ------------------------------------


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _card(seed: int, size=(374, 523)) -> Image.Image:
    """A deterministic card-shaped image, portrait like a real one."""
    from PIL import ImageDraw

    img = Image.new("RGB", size, (248, 246, 240))
    d = ImageDraw.Draw(img)
    rng = seed
    for _ in range(18):
        rng = (rng * 1103515245 + 12345) % 2147483648
        x0, y0 = rng % size[0], (rng // 7) % size[1]
        d.rectangle(
            [x0, y0, min(size[0], x0 + 40 + rng % 90), min(size[1], y0 + 40 + rng % 110)],
            fill=((rng * 37) % 256, (rng * 91) % 256, (rng * 53) % 256),
        )
    return img


def _canvas(objects, size=(856, 625)) -> Image.Image:
    """SNKRDUNK's real shape: a fixed transparent canvas with the subject
    composited somewhere inside it."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for img, pos in objects:
        opaque = Image.new("RGBA", img.size, (0, 0, 0, 255))
        opaque.paste(img.convert("RGBA"), (0, 0))
        canvas.paste(opaque, pos)
    return canvas


def _old_autocrop(image: Image.Image) -> Image.Image:
    """The crop this module used before 2026-08-29, reproduced here as the
    reference an ordinary single-object canvas must still match exactly."""
    if image.mode not in ("RGBA", "LA") and "transparency" not in image.info:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    bbox = rgba.split()[-1].getbbox()
    if bbox is None:
        return image.convert("RGB")
    cropped = rgba.crop(bbox)
    flat = Image.new("RGB", cropped.size, (255, 255, 255))
    flat.paste(cropped, mask=cropped.split()[-1])
    return flat


def test_an_ordinary_single_object_canvas_is_byte_for_byte_what_it_was():
    """The compatibility guarantee the whole change rests on. Every SNKRDUNK
    listing Atlas has ever priced is a single card on an empty canvas, and for
    those the new crop must return the identical pixels the old one did - not
    similar, identical."""
    for seed, position in ((11, (241, 51)), (12, (100, 30)), (13, (400, 80))):
        canvas = _canvas([(_card(seed), position)])
        assert (
            artwork_subject.isolate_subject(canvas).tobytes()
            == _old_autocrop(canvas).tobytes()
        ), f"seed {seed} at {position} changed"


def test_an_opaque_image_with_no_alpha_is_untouched():
    """Official Bandai artwork that carries no transparency has no background
    to remove, and must come through converted but never cropped."""
    art = _card(21)
    out = artwork_subject.isolate_subject(art)
    assert out.size == art.size
    assert out.tobytes() == art.convert("RGB").tobytes()


def test_a_mapping_49_shaped_canvas_isolates_the_card():
    """The case this tranche exists for. Mapping 49's listing carries the card
    plus a second object; the old crop spanned both, so the aspect ratio came
    out at 1.002 instead of the card's 0.723 and the gate refused a photo that
    was never wrong."""
    card = _card(31)
    canvas = _canvas([(card, (241, 51)), (_card(32, size=(150, 150)), (660, 300))])

    old = _old_autocrop(canvas)
    new = artwork_subject.isolate_subject(canvas)

    assert old.size != new.size, "the old crop should span both objects"
    assert new.size == card.size, "the new crop should be the card alone"
    assert abs(new.size[0] / new.size[1] - card.size[0] / card.size[1]) < 1e-9
    # and the isolated card is the card, not a squashed composite
    assert new.tobytes() == card.convert("RGB").tobytes()


def test_the_isolated_card_matches_its_official_art_where_the_spanning_crop_did_not():
    """End to end through the real gate, with the thresholds untouched: the
    same canvas that the old crop refused on aspect now compares as the card."""
    card = _card(41)
    official = _png(card)
    canvas = _canvas([(card, (241, 51)), (_card(42, size=(150, 150)), (660, 300))])

    old_aspect_diff = abs(
        1 - (_old_autocrop(canvas).size[0] / _old_autocrop(canvas).size[1])
        / (card.size[0] / card.size[1])
    )
    assert old_aspect_diff > ARTWORK_ASPECT_RATIO_TOLERANCE, "precondition: the old crop failed"

    result = compare_artwork(official, _png(canvas))
    assert result["match"] is True
    assert result["aspect_ok"] is True
    assert result["hash_distances"]["average_hash"] == 0


def test_two_comparable_objects_fail_closed_rather_than_guess():
    """When the canvas does not say which object is being sold, the collector
    must refuse it, not pick the larger one and price against it."""
    canvas = _canvas([(_card(51), (60, 51)), (_card(52), (460, 51))])
    result = compare_artwork(_png(_card(51)), _png(canvas))
    assert result["match"] is False
    assert result["error"].startswith("unusable_image:")
    assert "comparable objects" in result["error"]


def test_a_fully_transparent_canvas_fails_closed():
    canvas = Image.new("RGBA", (856, 625), (0, 0, 0, 0))
    result = compare_artwork(_png(_card(61)), _png(canvas))
    assert result["match"] is False
    assert result["error"].startswith("unusable_image:")


# --- the four human-confirmed hard positives ---------------------------------
#
# Blinded review of 2026-08-29, sealed key sha-256
# 2e51968aacbae4977e9c9eeb8bbaa5ad1e9143a89e63fae89f3bf11e619eb145: a human
# picked the same printing as the existing mapping and as the API's matcher on
# all four, with no hedging. The listing photos are a third party's and are not
# committed; what is pinned here is the collector's own measured distance to the
# confirmed printing under the shared crop, because that is what the gate reads.
HARD_POSITIVES = {
    42: {"card_print_id": 8, "average_hash": 13, "aspect": 0.0012, "gate": False},
    43: {"card_print_id": 9, "average_hash": 19, "aspect": 0.0012, "gate": False},
    49: {"card_print_id": 15, "average_hash": 11, "aspect": 0.0094, "gate": True},
    52: {"card_print_id": 18, "average_hash": 12, "aspect": 0.0012, "gate": True},
}


def test_the_confirmed_controls_are_gated_exactly_as_measured():
    """These four are known-correct mappings, and the gate still refuses two of
    them. That is recorded here rather than fixed: 13 and 19 are outside a band
    fitted at 2-10, and admitting 19 would more than double it on the strength
    of two examples. If a future change makes 42 or 43 pass, it moved a
    threshold, and this test is where that has to be argued."""
    for mapping_id, c in HARD_POSITIVES.items():
        hash_ok = c["average_hash"] <= ARTWORK_HASH_DISTANCE_THRESHOLD
        aspect_ok = c["aspect"] <= ARTWORK_ASPECT_RATIO_TOLERANCE
        assert (hash_ok and aspect_ok) is c["gate"], f"mapping {mapping_id}"


def test_mapping_49_only_passes_because_of_the_crop():
    """Its pre-crop measurement, kept so the reason 49 changed is legible: the
    aspect ratio, not the hash threshold, is what had refused it."""
    before = {"average_hash": 26, "aspect": 0.3993}
    assert before["aspect"] > ARTWORK_ASPECT_RATIO_TOLERANCE
    assert before["average_hash"] > ARTWORK_HASH_DISTANCE_THRESHOLD
    after = HARD_POSITIVES[49]
    assert after["aspect"] <= ARTWORK_ASPECT_RATIO_TOLERANCE
    assert after["average_hash"] <= ARTWORK_HASH_DISTANCE_THRESHOLD
