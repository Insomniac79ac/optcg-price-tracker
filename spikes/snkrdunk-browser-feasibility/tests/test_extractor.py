"""Offline, deterministic tests for spike.find_best_match and
spike.extract_product_page. No network, no browser - synthetic HTML/link
fixtures only, matched against the real KNOWN_PRINTS reference data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import extract_product_page, find_best_match, scored_links_for_print  # noqa: E402
from known_prints import KNOWN_PRINTS  # noqa: E402


def test_unambiguous_match_finds_op01_001_zoro_parallel():
    links = [
        {"href": "/items/999", "text": "サンジ フィギュア"},
        {"href": "/products/op01-001-parallel", "text": "ロロノア・ゾロ(パラレル) OP01-001"},
        {"href": "/brands/onepiece/categories/34", "text": "ワンピース スリーブ"},
    ]
    matched_print, matched_link, diagnostics = find_best_match(links)
    assert matched_print is not None
    assert matched_print.card_code == "OP01-001"
    assert matched_link["href"] == "/products/op01-001-parallel"
    assert diagnostics["attempts"][0]["candidate_count"] == 1


def test_ambiguous_links_fail_closed_for_that_print():
    # Two links both score >=2 for OP01-001 - not unambiguous, must not pick
    # either one. No other print matches either, so overall result is None.
    links = [
        {"href": "/products/a", "text": "ロロノア・ゾロ(パラレル) OP01-001 A"},
        {"href": "/products/b", "text": "ロロノア・ゾロ(パラレル) OP01-001 B"},
    ]
    matched_print, matched_link, diagnostics = find_best_match(links)
    assert matched_print is None
    assert matched_link is None
    assert diagnostics["attempts"][0]["candidate_count"] == 2


def test_no_matching_links_returns_none():
    links = [{"href": "/products/unrelated", "text": "totally unrelated sneaker"}]
    matched_print, matched_link, diagnostics = find_best_match(links)
    assert matched_print is None
    assert matched_link is None
    assert all(a["candidate_count"] == 0 for a in diagnostics["attempts"])


def test_falls_back_to_second_preference_when_first_is_ambiguous():
    links = [
        {"href": "/products/a", "text": "ロロノア・ゾロ(パラレル) OP01-001 A"},
        {"href": "/products/b", "text": "ロロノア・ゾロ(パラレル) OP01-001 B"},
        {"href": "/products/law", "text": "トラファルガー・ロー(パラレル) OP01-002"},
    ]
    matched_print, matched_link, diagnostics = find_best_match(links)
    assert matched_print is not None
    assert matched_print.card_code == "OP01-002"


def test_multiple_used_listings_of_same_card_are_not_ambiguous():
    # Same apparel id, three different /used/ listings (different conditions
    # and prices) plus the bare product page - all one card, must collapse
    # to a single candidate, not three.
    zoro = KNOWN_PRINTS[0]
    links = [
        {"href": "/apparels/12345", "text": "ロロノア・ゾロ(パラレル) OP01-001"},
        {"href": "/apparels/12345/used/1", "text": "A ロロノア・ゾロ(パラレル) OP01-001 ¥1,000"},
        {"href": "/apparels/12345/used/2", "text": "S ロロノア・ゾロ(パラレル) OP01-001 ¥1,500"},
    ]
    scored = scored_links_for_print(links, zoro)
    assert len(scored) == 1
    assert scored[0]["link"]["href"] == "/apparels/12345"  # prefers the bare product page


def test_two_distinct_cards_both_matching_stay_ambiguous():
    zoro = KNOWN_PRINTS[0]
    links = [
        {"href": "/apparels/111", "text": "ロロノア・ゾロ(パラレル) OP01-001"},
        {"href": "/apparels/222", "text": "ロロノア・ゾロ(パラレル) OP01-001"},
    ]
    scored = scored_links_for_print(links, zoro)
    assert len(scored) == 2


def test_extract_normal_raw_product_page():
    html = """
    <html><head><title>ロロノア・ゾロ(パラレル) OP01-001 | SNKRDUNK</title>
    <meta property="og:image" content="https://img.snkrdunk.example/op01-001.jpg">
    <script type="application/ld+json">{"@type": "Product", "name": "test"}</script>
    </head>
    <body><h1>ロロノア・ゾロ(パラレル)</h1>
    <div class="price">¥1,200</div>
    <a href="/products/op01-001/trades">取引履歴</a>
    </body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/op01-001-parallel")
    assert result["identity"]["title"].startswith("ロロノア・ゾロ")
    assert result["floor"]["price_mentions_jpy"] == [1200]
    assert result["flags"]["is_graded"] is False
    assert result["flags"]["is_sealed"] is False
    assert result["sales"]["sold_history_publicly_visible"] is True
    assert result["sales"]["sold_history_candidate_links"][0]["href"] == "/products/op01-001/trades"
    assert result["evidence"]["ld_json_block_types"] == ["Product"]


def test_graded_slab_is_flagged_not_raw():
    html = """
    <html><head><title>PSA10 ロロノア・ゾロ(パラレル)</title></head>
    <body><div class="price">¥15,000</div> PSA10 鑑定済み</body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/graded")
    assert result["flags"]["is_graded"] is True


def test_sealed_product_is_flagged_not_raw():
    html = """
    <html><head><title>ワンピースカード 未開封BOX</title></head>
    <body><div class="price">¥6,000</div> 未開封 シュリンク付き</body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/box")
    assert result["flags"]["is_sealed"] is True


def test_no_sold_history_case():
    html = """
    <html><head><title>ロロノア・ゾロ(パラレル)</title></head>
    <body><div class="price">¥1,200</div></body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/no-history")
    assert result["sales"]["sold_history_publicly_visible"] is False
    assert result["sales"]["sold_history_candidate_links"] == []


def test_missing_market_data_fails_closed_never_invents_a_floor():
    html = "<html><head><title>ロロノア・ゾロ(パラレル)</title></head><body>no price shown</body></html>"
    result = extract_product_page(html, "https://snkrdunk.com/products/no-price")
    assert result["floor"]["raw_floor_jpy"] is None
    assert result["floor"]["price_mentions_jpy"] == []


def test_login_required_markers_detected():
    html = """
    <html><head><title>取引履歴</title></head>
    <body>ログインして取引履歴を見る <a href="/login">ログイン</a></body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/gated")
    assert result["flags"]["login_required_markers_present"] is True


def test_duplicate_sale_fingerprint_inputs_captured_from_history_link():
    html = """
    <html><head><title>ロロノア・ゾロ(パラレル)</title></head>
    <body><a href="/products/op01-001/trades/998877">取引履歴</a></body></html>
    """
    result = extract_product_page(html, "https://snkrdunk.com/products/op01-001-parallel")
    links = result["sales"]["sold_history_candidate_links"]
    assert len(links) == 1
    assert "998877" in links[0]["href"]
