"""The image filename is the only route to an EXACT asset variant, so the
rules for reading it are the ones most worth pinning down.

Every filename shape here was observed on a live SNKRDUNK listing during the
2026-08-27 survey, except the deliberately malformed ones.
"""

import pytest

from worker.matching.snkrdunk_image_variant import (
    is_timestamp_filename,
    variant_from_image_url,
)

CDN = "https://cdn.snkrdunk.com/upload_bg_removed/"
SEM = "https://cdn.snkrdunk.com/uploads/media/"


@pytest.mark.parametrize(
    "filename,card_code,expected",
    [
        # --- base ----------------------------------------------------------
        ("OPC-EN-TCG-OP01-001-of.webp", "OP01-001", "base"),
        ("TCG-OPC-ST01-001.webp", "ST01-001", "base"),
        ("OP01-001.webp", "OP01-001", "base"),
        # --- parallels -----------------------------------------------------
        ("OPC-EN-TCG-OP01-001_p1-of.webp", "OP01-001", "p1"),
        ("OPC-EN-TCG-OP01-002_p1-of.webp", "OP01-002", "p1"),
        ("OPC-EN-TCG-OP01-001_p2-of.webp", "OP01-001", "p2"),
        ("TCG-OPC-OP02-013_p3.webp", "OP02-013", "p3"),
        ("TCG-OPC-OP01-016_p12.webp", "OP01-016", "p12"),
        # --- reprints ------------------------------------------------------
        ("TCG-OPC-OP02-013_r1.webp", "OP02-013", "r1"),
        # --- case is not a difference in fact ------------------------------
        ("opc-en-tcg-op01-001_p1-of.webp", "OP01-001", "p1"),
        ("OPC-EN-TCG-OP01-001_P1-of.webp", "OP01-001", "p1"),
    ],
)
def test_semantic_filenames_yield_the_exact_variant(filename, card_code, expected):
    assert variant_from_image_url(SEM + filename, card_code) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "20220903005802-0.webp",   # the older upload-timestamp shape
        "20230927085043-0.webp",
        "20240126083229-4.webp",
        "20251111103048-0.webp",
    ],
)
def test_timestamp_filenames_yield_no_variant(filename):
    """The old uploads name nothing. 'No evidence' must not become 'base'."""
    assert variant_from_image_url(CDN + filename, "OP01-001") is None
    assert is_timestamp_filename(CDN + filename) is True


@pytest.mark.parametrize(
    "filename,card_code",
    [
        # Names a DIFFERENT card - evidence that something is wrong, not weak
        # evidence about this one.
        ("OPC-EN-TCG-OP01-002_p1-of.webp", "OP01-001"),
        ("TCG-OPC-ST01-001.webp", "OP01-001"),
        # Malformed variant tokens.
        ("TCG-OPC-OP01-001_p.webp", "OP01-001"),
        ("TCG-OPC-OP01-001_p0.webp", "OP01-001"),
        ("TCG-OPC-OP01-001_p01.webp", "OP01-001"),
        ("TCG-OPC-OP01-001_x1.webp", "OP01-001"),
        # A longer code that merely starts with ours.
        ("TCG-OPC-OP01-0011.webp", "OP01-001"),
        # Unrelated files.
        ("logo.webp", "OP01-001"),
        ("sneaker-nike-dunk-low.webp", "OP01-001"),
        ("", "OP01-001"),
    ],
)
def test_filenames_that_prove_nothing_yield_none(filename, card_code):
    assert variant_from_image_url(SEM + filename, card_code) is None


def test_a_bare_variant_token_is_not_evidence():
    """`_p1` unanchored to the card code must never be read as a variant."""
    assert variant_from_image_url(SEM + "some-image_p1.webp", "OP01-001") is None


def test_missing_inputs_return_none():
    assert variant_from_image_url(None, "OP01-001") is None
    assert variant_from_image_url(SEM + "OP01-001.webp", None) is None
    assert variant_from_image_url(None, None) is None
    assert is_timestamp_filename(None) is False


def test_query_strings_and_paths_are_ignored():
    url = SEM + "OPC-EN-TCG-OP01-001_p1-of.webp?size=l&v=2"
    assert variant_from_image_url(url, "OP01-001") == "p1"


def test_a_pokemon_style_filename_is_not_a_one_piece_variant():
    assert variant_from_image_url(SEM + "s12a-184-172.webp", "OP01-001") is None
