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

from worker.jobs.discover_snkrdunk_sitemap import DiscoverySummary, _consume
from worker.matching.non_target_tcg import (
    identify_non_target_tcg,
    known_foreign_game_tokens,
)
from worker.matching.snkrdunk_listing_evidence import evidence_from_listing
from worker.matching.source_product_aliases import resolve_source_product_code

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


# --- the discovery filter, end to end ----------------------------------------


class _Page:
    def __init__(self, url_, title, image):
        self.url = url_
        self.http_status = 200
        self.body = (
            f"<html><head><title>{title}</title>"
            f'<meta property="og:image" content="{image}">'
            "</head></html>"
        )


class _Outcome:
    urls_inspected = 1
    pages_fetched = 1
    blocked_responses = 0
    stop_reason = "done"
    cursor = None


SHADOWVERSE = _Page(
    "https://snkrdunk.com/en/trading-cards/170998",
    'happy pig BR [BP08-117](Booster Pack Vol.8 &quot;Chaotic Dimensions&quot;)',
    url("SVE-TCG-bp08-117.webp"),
)
ONE_PIECE = _Page(
    "https://snkrdunk.com/en/trading-cards/1",
    "Roronoa Zoro L [OP01-001] (Booster Pack ROMANCE DAWN)",
    url("20220903005802-0.webp"),
)
FUTURE_ONE_PIECE = _Page(
    "https://snkrdunk.com/en/trading-cards/2",
    "Some Future Card L [OP14-001] (Booster Pack The Next Thing)",
    url("OPC-EN-TCG-OP14-001-of.webp"),
)


class _FakeDb:
    """Records what discovery tried to persist, without a database."""

    def __init__(self):
        self.added = []

    def query(self, *a, **k):
        return self

    def filter_by(self, **k):
        return self

    def one_or_none(self):
        return None

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass


def _run(pages):
    db = _FakeDb()
    summary = _consume(db, [(p, _Outcome()) for p in pages], DiscoverySummary(), None)
    return db, summary


def test_a_shadowverse_listing_never_becomes_a_candidate():
    db, summary = _run([SHADOWVERSE])
    assert db.added == []
    assert summary.candidates_inserted == 0
    assert summary.non_target_tcg == 1
    assert summary.non_target_tcg_games == {"Shadowverse Evolve": 1}
    # Reported as its own fact, not folded into the "no card code" statistic.
    assert summary.not_one_piece == 0


def test_a_one_piece_listing_is_still_inserted():
    db, summary = _run([ONE_PIECE])
    assert len(db.added) == 1
    assert db.added[0].detected_card_code == "OP01-001"
    assert summary.candidates_inserted == 1
    assert summary.non_target_tcg == 0


def test_a_future_one_piece_product_is_still_inserted():
    """The card code is in no Atlas catalogue and the product is unknown. It
    must reach the review queue anyway - this is the false-positive case the
    filter exists to avoid causing."""
    db, summary = _run([FUTURE_ONE_PIECE])
    assert len(db.added) == 1
    assert db.added[0].detected_card_code == "OP14-001"
    assert summary.non_target_tcg == 0


def test_a_mixed_batch_splits_correctly():
    db, summary = _run([SHADOWVERSE, ONE_PIECE, FUTURE_ONE_PIECE])
    assert summary.non_target_tcg == 1
    assert summary.candidates_inserted == 2
    assert [r.detected_card_code for r in db.added] == ["OP01-001", "OP14-001"]


def test_the_summary_serialises_the_new_counters():
    _, summary = _run([SHADOWVERSE])
    data = summary.as_dict()
    assert data["non_target_tcg"] == 1
    assert data["non_target_tcg_games"] == {"Shadowverse Evolve": 1}
    assert data["non_target_examples"][0].startswith("Shadowverse Evolve: BP08-117 ")


# --- nothing downstream moved -------------------------------------------------


def test_source_product_aliases_are_unaffected():
    """This tranche adds a discovery filter and nothing else. The three source
    aliases and their fail-closed membership guard answer exactly as before."""
    assert resolve_source_product_code("snkrdunk", "Booster Pack Final Battle", "OP02-001") == "OP-02"
    assert resolve_source_product_code("snkrdunk", "Booster Pack Formidable Enemy", "OP03-001") == "OP-03"
    assert resolve_source_product_code("snkrdunk", "Booster Pack The Kingdom Of Conspiracy", "OP04-001") == "OP-04"
    # Still fails closed on a code the product does not contain.
    assert resolve_source_product_code("snkrdunk", "Booster Pack Final Battle", "OP03-001") is None
    # And the Shadowverse product label resolves to nothing, as it always did.
    assert resolve_source_product_code("snkrdunk", 'Booster Pack Vol.8 "Chaotic Dimensions"', "BP08-117") is None


def test_listing_evidence_derivation_is_unchanged():
    """The filter runs in discovery, not in the derivation the offline reparse
    shares. A Shadowverse page still parses exactly as it did - it simply
    never gets offered to the candidate table."""
    ev = evidence_from_listing(
        "https://snkrdunk.com/en/trading-cards/170998",
        'happy pig BR [BP08-117](Booster Pack Vol.8 "Chaotic Dimensions")',
        url("SVE-TCG-bp08-117.webp"),
    )
    assert ev.card_code == "BP08-117"
    assert ev.resolved_product_code is None
    assert ev.is_one_piece is True
