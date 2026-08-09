"""Integration-level offline tests for spike.extract_product_page - the
final assembled identity/raw_market/sold_history/evidence structure, against
the reduced real-shape product-page fixture. No network, no browser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import extract_product_page  # noqa: E402
from known_prints import KNOWN_PRINTS  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
PRODUCT_URL = "https://snkrdunk.com/apparels/104428"

ZORO_PARALLEL = KNOWN_PRINTS[0]  # OP01-001, rarity L, treatment parallel

MATCHING_ARTWORK = {"match": True, "hash_distances": {"average_hash": 3}, "aspect_ratio_relative_diff": 0.0013}
MISMATCHED_ARTWORK = {"match": False, "hash_distances": {"average_hash": 40}, "aspect_ratio_relative_diff": 0.4}


def _load_html() -> str:
    return (FIXTURES_DIR / "product_page_reduced.html").read_text(encoding="utf-8")


def test_full_extraction_with_matching_identity_and_artwork_is_exact_print_match():
    result = extract_product_page(
        _load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MATCHING_ARTWORK
    )
    identity = result["identity"]
    assert identity["card_code"] == "OP01-001"
    assert identity["rarity"] == "L"
    assert identity["treatment"] == "parallel"
    assert identity["exact_print_match"] is True
    assert identity["identity_mismatch_reasons"] == []
    assert identity["product_id"] == "104428"


def test_raw_market_extracted_correctly_within_full_assembly():
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MATCHING_ARTWORK)
    raw_market = result["raw_market"]
    assert raw_market["raw_floor_jpy"] == 24500
    assert set(raw_market["conditions"].keys()) == {"A", "B", "C", "D"}


def test_artwork_mismatch_fails_closed_even_with_matching_title():
    result = extract_product_page(
        _load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MISMATCHED_ARTWORK
    )
    assert result["identity"]["exact_print_match"] is False
    assert "artwork_not_confirmed_match" in result["identity"]["identity_mismatch_reasons"]


def test_ambiguous_identity_card_code_mismatch_fails_closed():
    law = KNOWN_PRINTS[1]  # OP01-002 - does not match this fixture's OP01-001 title
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=law, artwork_comparison=MATCHING_ARTWORK)
    assert result["identity"]["exact_print_match"] is False
    assert "card_code_mismatch" in result["identity"]["identity_mismatch_reasons"]


def test_ambiguous_identity_treatment_mismatch_fails_closed():
    # A hypothetical non-parallel OP01-001 known print - the fixture's title
    # is the parallel (L-P) listing, so treatment must mismatch and fail
    # closed rather than silently accept a different print of the same card.
    from dataclasses import replace

    non_parallel_zoro = replace(ZORO_PARALLEL, treatment="normal")
    result = extract_product_page(
        _load_html(), PRODUCT_URL, known_print=non_parallel_zoro, artwork_comparison=MATCHING_ARTWORK
    )
    assert result["identity"]["exact_print_match"] is False
    assert "treatment_mismatch" in result["identity"]["identity_mismatch_reasons"]


def test_no_known_print_supplied_never_claims_a_match():
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=None)
    assert result["identity"]["exact_print_match"] is False
    assert result["identity"]["identity_mismatch_reasons"] == []


def test_evidence_records_selectors_and_parser_version():
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MATCHING_ARTWORK)
    evidence = result["evidence"]
    assert evidence["parser_version"] == "snkrdunk-spike-extractor-v2"
    assert evidence["condition_container"]["reason"] == "ok"
    assert evidence["main_image"]["reason"] == "ok"
    assert evidence["ld_json_product_node_present"] is False  # real page has no Product LD node


def test_main_image_is_the_product_photo_not_a_generic_ogp_fallback():
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MATCHING_ARTWORK)
    assert result["identity"]["image_url"] == "https://cdn.snkrdunk.com/upload_bg_removed/20221121015111-0.webp?size=l"


def test_sold_history_defaults_to_inconclusive_when_not_supplied():
    result = extract_product_page(_load_html(), PRODUCT_URL, known_print=ZORO_PARALLEL, artwork_comparison=MATCHING_ARTWORK)
    assert result["sold_history"]["availability_status"] == "inconclusive"


def test_sold_history_passthrough_when_supplied():
    sold_history = {
        "availability_status": "public_sold_history_available",
        "raw_sales": [{"product_id": "104428", "condition": "A", "price_jpy": 30000, "date": "2026/08/03"}],
        "stable_identifier_available": False,
    }
    result = extract_product_page(
        _load_html(),
        PRODUCT_URL,
        known_print=ZORO_PARALLEL,
        artwork_comparison=MATCHING_ARTWORK,
        sold_history=sold_history,
    )
    assert result["sold_history"] == sold_history
