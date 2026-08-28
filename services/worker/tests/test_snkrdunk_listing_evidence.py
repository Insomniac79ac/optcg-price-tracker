"""Listing evidence: what the page says, and nothing more.

The titles below are verbatim from live SNKRDUNK listings observed on
2026-08-27, so the parser is pinned against the real corpus rather than an
idealised one - including the Pokemon listings interleaved with One Piece.
"""

import pytest

from worker.matching.release_product_aliases import (
    known_aliases,
    resolve_product_code,
)
from worker.matching.snkrdunk_listing_evidence import parse_listing

SEM = "https://cdn.snkrdunk.com/uploads/media/"
CDN = "https://cdn.snkrdunk.com/upload_bg_removed/"


def page(title: str, og_image: str | None = None) -> str:
    img = f'<meta property="og:image" content="{og_image}" />' if og_image else ""
    return f"<html><head><title>{title} | SNKRDUNK</title>{img}</head><body></body></html>"


URL = "https://snkrdunk.com/en/trading-cards/142584"


# --- card code and language --------------------------------------------------


def test_a_japanese_base_listing_parses_fully():
    ev = parse_listing(
        URL,
        page("Roronoa Zoro L [OP01-001] (Booster Pack ROMANCE DAWN)",
             SEM + "OPC-EN-TCG-OP01-001-of.webp"),
    )
    assert ev.card_code == "OP01-001"
    assert ev.language == "jp"
    assert ev.is_one_piece and not ev.is_english
    assert ev.product_label == "Booster Pack ROMANCE DAWN"
    assert ev.resolved_product_code == "OP-01"
    assert ev.rarity_token == "L"
    assert ev.parallel_family is False
    assert ev.asset_variant == "base"


def test_an_english_listing_is_marked_english():
    ev = parse_listing(
        URL, page('Roronoa Zoro L [OP01-001] [EN](Booster Pack "ROMANCE DAWN")',
                  SEM + "OPC-EN-TCG-OP01-001-of.webp")
    )
    assert ev.card_code == "OP01-001"
    assert ev.language == "en"
    assert ev.is_english is True


def test_a_pokemon_listing_is_not_a_one_piece_listing():
    ev = parse_listing(
        URL, page('Lunatone AR[s12a 184/172](High Class Pack "VSTAR Universe")')
    )
    assert ev.card_code is None
    assert ev.is_one_piece is False


def test_a_page_without_a_title_yields_nothing():
    ev = parse_listing(URL, "<html><head></head><body>hi</body></html>")
    assert ev.card_code is None
    assert "no <title>" in ev.notes


def test_an_empty_body_yields_nothing():
    ev = parse_listing(URL, "")
    assert ev.card_code is None
    assert ev.is_one_piece is False


# --- the parallel-family rule ------------------------------------------------


def test_a_parallel_listing_with_a_timestamp_image_gets_no_variant():
    """"-P" is parallel FAMILY. Writing it into detected_variant would make the
    gate report "contradicts" when the truth is "insufficient"."""
    ev = parse_listing(
        URL, page("Trafalgar law L-P[OP01-002] (Booster Pack ROMANCE DAWN)",
                  CDN + "20220903005802-0.webp")
    )
    assert ev.parallel_family is True
    assert ev.asset_variant is None
    assert ev.image_is_timestamp is True
    # The family evidence survives, descriptively.
    assert ev.rarity_token == "L-P"


def test_a_parallel_listing_with_a_semantic_image_gets_the_exact_variant():
    ev = parse_listing(
        URL, page('Roronoa Zoro L-P [OP01-001] [EN](Booster Pack "ROMANCE DAWN")',
                  SEM + "OPC-EN-TCG-OP01-001_p1-of.webp")
    )
    assert ev.parallel_family is True
    assert ev.asset_variant == "p1"


def test_the_word_parallel_also_counts_as_family_evidence():
    ev = parse_listing(
        URL, page("Roronoa Zoro L Parallel [OP01-001] (Premium Card Collection 25th Anniversary Edition)")
    )
    assert ev.parallel_family is True
    assert ev.asset_variant is None


def test_a_comic_parallel_keeps_its_published_rarity_token():
    ev = parse_listing(
        URL, page('Shanks SEC-SP (Comic Parallel) [OP01-120](Booster Pack "ROMANCE DAWN")')
    )
    assert ev.card_code == "OP01-120"
    assert ev.rarity_token == "SEC-SP"
    assert ev.parallel_family is True
    assert ev.asset_variant is None


# --- product resolution ------------------------------------------------------


def test_the_product_label_is_resolved_only_through_an_authoritative_alias():
    ev = parse_listing(URL, page('Roronoa Zoro L [OP01-001] (Booster Pack "ROMANCE DAWN")'))
    # Quoting is not a difference in fact.
    assert ev.resolved_product_code == "OP-01"


def test_an_unknown_product_label_stays_unresolved():
    """A label Bandai publishes no coded product for stays None, and is recorded
    so the alias table can grow deliberately.

    The 25th Anniversary Edition is real and unmistakable - and still refused,
    because Bandai files it inside the uncoded 限定商品収録カード bucket and
    Atlas therefore holds no ReleaseProduct to resolve it to. See
    worker.matching.release_product_aliases, "REFUSED LABELS"."""
    ev = parse_listing(
        URL,
        page("Roronoa Zoro L Parallel [OP01-001] "
             "(Premium Card Collection 25th Anniversary Edition)"),
    )
    assert ev.product_label == "Premium Card Collection 25th Anniversary Edition"
    assert ev.resolved_product_code is None
    assert any("unresolved" in n for n in ev.notes)


def test_a_label_matching_a_published_bandai_title_resolves():
    """EB-01, from the same run-1 corpus: Bandai publishes this product as
    'EXTRA BOOSTER -Memorial Collection- [EB-01]' in the Asia-EN catalogue, so
    the label is Bandai's own name for it rather than a translation of one."""
    ev = parse_listing(
        URL, page("Charlotte Compote C [EB01-055] (Extra Booster Memorial Collection)")
    )
    assert ev.product_label == "Extra Booster Memorial Collection"
    assert ev.resolved_product_code == "EB-01"
    assert not any("unresolved" in n for n in ev.notes)


def test_the_card_code_prefix_is_never_used_as_a_product_code():
    """OP02-013 carried in PRB-01 must not be narrowed to OP-02."""
    ev = parse_listing(
        URL, page("Portgas.D.Ace SR [OP02-013] (Premium Booster ONE PIECE CARD THE BEST)")
    )
    assert ev.card_code == "OP02-013"
    # No alias for this label yet, so no product evidence - and crucially the
    # parser did NOT fall back to "OP02" from the code.
    assert ev.resolved_product_code is None


@pytest.mark.parametrize("label", [None, "", "   ", "Totally Unknown Product"])
def test_unknown_labels_resolve_to_none(label):
    assert resolve_product_code(label) is None


def test_every_alias_is_documented_with_evidence():
    from worker.matching.release_product_aliases import alias_evidence

    for label in known_aliases():
        assert alias_evidence(label), f"alias {label!r} has no recorded evidence"
