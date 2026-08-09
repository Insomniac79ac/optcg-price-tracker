"""Offline, deterministic tests for snkrdunk_collector.artwork.compare_artwork
- synthetic generated images only (no real/copyrighted card art committed to
the repo). Thresholds were empirically derived from a real live comparison
(card_print.id=1 official art vs. https://snkrdunk.com/apparels/104428's own
photo, 2026-08-09) - see artwork.py's module docstring."""

import io

from PIL import Image

from snkrdunk_collector.artwork import compare_artwork


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


def test_completely_different_artwork_fails_closed():
    card_a = _checkerboard(colors=((200, 30, 30), (230, 210, 60)))
    card_b = _checkerboard(colors=((20, 90, 200), (10, 10, 10)))
    result = compare_artwork(_png_bytes(card_a), _png_bytes(card_b))
    assert result["match"] is False
    assert result["hash_ok"] is False


def test_background_removed_candidate_with_transparent_padding_still_matches():
    official = _checkerboard(size=(300, 420))
    padded = Image.new("RGBA", (700, 420), (0, 0, 0, 0))
    padded.paste(official.convert("RGBA"), (200, 0))
    result = compare_artwork(_png_bytes(official), _png_bytes(padded))
    assert result["match"] is True
    assert result["candidate_normalized_size"] == official.size


def test_undecodable_candidate_bytes_fails_closed_not_crash():
    result = compare_artwork(_png_bytes(_checkerboard()), b"not an image")
    assert result["match"] is False
    assert "error" in result


def test_aspect_ratio_mismatch_alone_fails_closed():
    portrait = _checkerboard(size=(300, 420))
    landscape = portrait.resize((420, 300))
    result = compare_artwork(_png_bytes(portrait), _png_bytes(landscape))
    assert result["aspect_ok"] is False
    assert result["match"] is False
