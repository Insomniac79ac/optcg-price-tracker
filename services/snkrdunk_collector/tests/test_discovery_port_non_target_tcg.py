"""The non-target-TCG filter's standard, made executable.

The asymmetry drives every test below. Dropping a real One Piece listing is
silent and unrecoverable - it never reaches the review queue where someone
would notice - while keeping a foreign one costs a row a human glances at. So
the refusals here are few and specific, and most of the file is about what
must SURVIVE: unfamiliar products, future set codes, timestamp uploads, and
anything the module has not been shown.

The Shadowverse filenames are verbatim from the 117 contaminating candidates
of discovery run 9; the One Piece ones are the shapes documented in
worker.matching.snkrdunk_image_variant and observed on live listings.
"""

import pytest

from snkrdunk_collector.discovery_evidence.non_target_tcg import (
    identify_non_target_tcg,
    known_foreign_game_tokens,
)
from snkrdunk_collector.discovery_evidence.snkrdunk_listing_evidence import evidence_from_listing
from snkrdunk_collector.discovery_evidence.source_product_aliases import resolve_source_product_code

CDN = "https://cdn.snkrdunk.com/upload_bg_removed/"


def url(filename: str) -> str:
    return f"{CDN}{filename}?size=l"


# --- positively another game: refused ----------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "SVE-TCG-bp08-117.webp",
        "SVE-TCG-bp08-001.webp",
        "SVE-TCG-BP08-116.webp",   # the same thing upper-cased
        "sve-tcg-bp08-115.webp",   # ...and lower-cased
    ],
)
def test_a_shadowverse_asset_is_identified(filename):
    assert identify_non_target_tcg(url(filename)) == "Shadowverse Evolve"


def test_the_table_is_pinned():
    """A second game cannot be added without landing in this test, and
    therefore in front of the evidence standard in the module docstring."""
    assert known_foreign_game_tokens() == {"SVE": "Shadowverse Evolve"}


# --- One Piece: kept ----------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        # Every One Piece shape the codebase has documented. Note that three of
        # them carry a `TCG` segment too: the convention marker alone must
        # never be enough to refuse anything.
        "OPC-EN-TCG-OP01-001-of.webp",
        "OPC-EN-TCG-OP01-001_p1-of.webp",
        "OPC-EN-TCG-OP02-013_r1-of.webp",
        "TCG-OPC-ST01-001.webp",
        "20220903005802-0.webp",
        "20251111103048-0.webp",
    ],
)
def test_a_one_piece_asset_is_never_refused(filename):
    assert identify_non_target_tcg(url(filename)) is None


@pytest.mark.parametrize(
    "filename",
    [
        # Products Atlas does not hold yet. A card code absent from the
        # catalogue is exactly what a NEW Bandai product looks like, and it
        # must stay a candidate rather than be filtered away.
        "OPC-EN-TCG-OP14-001-of.webp",
        "OPC-EN-TCG-EB03-042-of.webp",
        "TCG-OPC-PRB02-001.webp",
        "OPC-EN-TCG-ST99-001_p3-of.webp",
    ],
)
def test_an_unknown_future_one_piece_product_is_kept(filename):
    assert identify_non_target_tcg(url(filename)) is None


@pytest.mark.parametrize(
    "image_url",
    [
        None,
        "",
        "https://cdn.snkrdunk.com/upload_bg_removed/",
        "not a url at all",
        url("mystery-asset-name.webp"),
        url("SVE.webp"),            # the token WITHOUT the convention segment
        url("TCG-something.webp"),  # the convention segment without a game
        url("RESERVED-TCG-001.webp"),
    ],
)
def test_anything_not_positively_identified_is_kept(image_url):
    """Every uncertain answer is None. There is no path here that guesses."""
    assert identify_non_target_tcg(image_url) is None


def test_the_token_is_matched_as_a_segment_not_a_substring():
    """A substring test for 'SVE' would fire on any filename containing those
    three letters; SVE must be a whole hyphen-separated segment."""
    assert identify_non_target_tcg(url("OPC-EN-TCG-SVEN-001-of.webp")) is None
    assert identify_non_target_tcg(url("TCG-PRESVE-001.webp")) is None
    assert identify_non_target_tcg(url("SVE-TCG-bp08-117.webp")) == "Shadowverse Evolve"
