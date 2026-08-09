"""Offline, deterministic tests for spike.find_condition_chip_container and
extract_raw_conditions, against a reduced fixture of the real product-page
condition-chip DOM structure (see fixtures/product_page_reduced.html)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from spike import extract_raw_conditions, find_condition_chip_container  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_fixture_soup(name: str) -> BeautifulSoup:
    html = (FIXTURES_DIR / name).read_text(encoding="utf-8")
    return BeautifulSoup(html, "html.parser")


def test_finds_the_single_condition_container():
    soup = _load_fixture_soup("product_page_reduced.html")
    container, diagnostics = find_condition_chip_container(soup)
    assert container is not None
    assert diagnostics["reason"] == "ok"
    assert diagnostics["chip_button_count"] == 16  # 4 raw + 12 graded, real count


def test_extracts_all_four_raw_conditions_with_correct_prices_and_nulls():
    soup = _load_fixture_soup("product_page_reduced.html")
    result = extract_raw_conditions(soup)
    conditions = result["conditions"]
    assert set(conditions.keys()) == {"A", "B", "C", "D"}
    assert conditions["A"]["price_jpy"] == 29000
    assert conditions["B"]["price_jpy"] == 24500
    assert conditions["C"]["price_jpy"] is None
    assert conditions["C"]["raw_text"] == "出品待ち"
    assert conditions["D"]["price_jpy"] is None


def test_raw_floor_is_minimum_of_available_raw_prices():
    soup = _load_fixture_soup("product_page_reduced.html")
    result = extract_raw_conditions(soup)
    # A=29000, B=24500, C/D unavailable -> floor is 24500, not the graded
    # PSA10 (50000) or ARS10+ (198000) prices in the same picker.
    assert result["raw_floor_jpy"] == 24500


def test_graded_conditions_never_appear_in_raw_conditions():
    soup = _load_fixture_soup("product_page_reduced.html")
    result = extract_raw_conditions(soup)
    graded_labels = {"PSA10", "PSA9", "PSA8以下", "BGS10 BL", "ARS10+", "他鑑定品"}
    assert graded_labels.isdisjoint(result["conditions"].keys())


def test_recommendation_carousel_price_never_leaks_into_raw_conditions():
    soup = _load_fixture_soup("product_page_reduced.html")
    result = extract_raw_conditions(soup)
    all_prices = [c["price_jpy"] for c in result["conditions"].values() if c["price_jpy"] is not None]
    assert 3450 not in all_prices  # the reco-carousel card's price


def test_missing_raw_listings_returns_null_floor_not_a_graded_price():
    html = """
    <div class="c__container">
      <button class="c__chip c__disabled"><p class="c__variant">A</p><p class="c__awaiting">出品待ち</p></button>
      <button class="c__chip c__disabled"><p class="c__variant">B</p><p class="c__awaiting">出品待ち</p></button>
      <button class="c__chip"><p class="c__variant">PSA10</p><p class="c__price">¥50,000</p></button>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    result = extract_raw_conditions(soup)
    assert result["raw_floor_jpy"] is None
    assert result["conditions"]["A"]["price_jpy"] is None


def test_no_chip_buttons_on_page_fails_closed():
    soup = BeautifulSoup("<html><body><p>no picker here</p></body></html>", "html.parser")
    container, diagnostics = find_condition_chip_container(soup)
    assert container is None
    assert diagnostics["reason"] == "no_chip_buttons_found"


def test_ambiguous_chip_groups_on_page_fail_closed():
    # Two separate chip pickers with different parents (e.g. an unrelated
    # widget elsewhere also using "__chip") - must not guess which is the
    # product's own.
    html = """
    <div class="a__container">
      <button class="a__chip"><p class="a__variant">A</p><p class="a__price">¥1,000</p></button>
    </div>
    <div class="b__container">
      <button class="b__chip"><p class="b__variant">A</p><p class="b__price">¥2,000</p></button>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    container, diagnostics = find_condition_chip_container(soup)
    assert container is None
    assert diagnostics["reason"] == "chip_buttons_do_not_share_single_parent"
