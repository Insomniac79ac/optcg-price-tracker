"""Offline, deterministic tests for spike.find_best_match and
scored_links_for_print. No network, no browser - synthetic link fixtures
only, matched against the real (corrected) KNOWN_PRINTS reference data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import find_best_match, scored_links_for_print  # noqa: E402
from known_prints import KNOWN_PRINTS  # noqa: E402


def test_unambiguous_match_finds_op01_001_zoro_parallel():
    links = [
        {"href": "/items/999", "text": "サンジ フィギュア"},
        {"href": "/products/op01-001-parallel", "text": "ロロノア・ゾロ L-P OP01-001"},
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
        {"href": "/products/a", "text": "ロロノア・ゾロ L-P OP01-001 A"},
        {"href": "/products/b", "text": "ロロノア・ゾロ L-P OP01-001 B"},
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
        {"href": "/products/a", "text": "ロロノア・ゾロ L-P OP01-001 A"},
        {"href": "/products/b", "text": "ロロノア・ゾロ L-P OP01-001 B"},
        {"href": "/products/law", "text": "トラファルガー・ロー L-P OP01-002"},
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
        {"href": "/apparels/12345", "text": "ロロノア・ゾロ L-P OP01-001"},
        {"href": "/apparels/12345/used/1", "text": "A ロロノア・ゾロ L-P OP01-001 ¥1,000"},
        {"href": "/apparels/12345/used/2", "text": "S ロロノア・ゾロ L-P OP01-001 ¥1,500"},
    ]
    scored = scored_links_for_print(links, zoro)
    assert len(scored) == 1
    assert scored[0]["link"]["href"] == "/apparels/12345"  # prefers the bare product page


def test_two_distinct_cards_both_matching_stay_ambiguous():
    zoro = KNOWN_PRINTS[0]
    links = [
        {"href": "/apparels/111", "text": "ロロノア・ゾロ L-P OP01-001"},
        {"href": "/apparels/222", "text": "ロロノア・ゾロ L-P OP01-001"},
    ]
    scored = scored_links_for_print(links, zoro)
    assert len(scored) == 2
