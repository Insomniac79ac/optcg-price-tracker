"""Offline, deterministic tests for spike.compare_artwork - synthetic
generated images only (no real/copyrighted card art committed to the repo).
Thresholds themselves were empirically derived from a real comparison (see
spike.py's ARTWORK_HASH_DISTANCE_THRESHOLD docstring); these tests exercise
the pass/fail-closed logic and the background-removal autocrop handling
against synthetic images that are cheap to construct and reason about."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from spike import compare_artwork  # noqa: E402


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _checkerboard(size=(300, 420), cell=30, colors=((200, 30, 30), (230, 210, 60))) -> Image.Image:
    img = Image.new("RGB", size)
    pixels = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            pixels[x, y] = colors[((x // cell) + (y // cell)) % 2]
    return img


def test_identical_images_match():
    img = _checkerboard()
    result = compare_artwork(_png_bytes(img), _png_bytes(img))
    assert result["match"] is True
    assert result["hash_distances"]["average_hash"] == 0


def test_slightly_recompressed_resized_image_still_matches():
    img = _checkerboard()
    resized = img.resize((150, 210))  # simulate a lower-resolution retailer photo
    result = compare_artwork(_png_bytes(img), _png_bytes(resized))
    assert result["match"] is True


def test_completely_different_artwork_fails_closed():
    card_a = _checkerboard(colors=((200, 30, 30), (230, 210, 60)))
    card_b = _checkerboard(colors=((20, 90, 200), (10, 10, 10)))
    result = compare_artwork(_png_bytes(card_a), _png_bytes(card_b))
    assert result["match"] is False
    assert result["hash_ok"] is False


def test_background_removed_candidate_with_transparent_padding_still_matches():
    # Simulates SNKRDUNK's background-removed product photos: the real card
    # art sits inside a larger transparent-padded canvas with a different
    # raw aspect ratio than the source - autocrop-to-alpha-bbox must recover
    # a comparable aspect ratio and hash before comparison.
    official = _checkerboard(size=(300, 420))

    # Canvas fully contains the card (height >= 420) with transparent padding
    # added only horizontally - matches SNKRDUNK's real background-removed
    # photos, which pad around the card rather than cropping it.
    padded = Image.new("RGBA", (700, 420), (0, 0, 0, 0))
    card_rgba = official.convert("RGBA")
    padded.paste(card_rgba, (200, 0))

    result = compare_artwork(_png_bytes(official), _png_bytes(padded))
    assert result["match"] is True
    assert result["candidate_raw_size"] == (700, 420)
    assert result["candidate_normalized_size"] == official.size  # bbox-cropped back to the card


def test_undecodable_candidate_bytes_fails_closed_not_crash():
    official = _checkerboard()
    result = compare_artwork(_png_bytes(official), b"not an image")
    assert result["match"] is False
    assert "error" in result


def test_aspect_ratio_mismatch_alone_fails_closed():
    # Same hash content when stretched, but a genuinely different aspect
    # ratio (e.g. a landscape sealed-box photo instead of a portrait card)
    # must fail the aspect check even if resizing to a square makes the
    # hashes look similar.
    portrait = _checkerboard(size=(300, 420))
    landscape = portrait.resize((420, 300))  # distorts aspect from 0.714 to 1.4
    result = compare_artwork(_png_bytes(portrait), _png_bytes(landscape))
    assert result["aspect_ok"] is False
    assert result["match"] is False


@pytest.mark.parametrize("field", ["official_aspect_ratio", "candidate_aspect_ratio", "hash_distances"])
def test_result_always_reports_comparison_evidence_fields(field):
    img = _checkerboard()
    result = compare_artwork(_png_bytes(img), _png_bytes(img))
    assert field in result
