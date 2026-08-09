"""Offline, deterministic tests for spike.find_sales_history_link and
parse_sales_history_page, against reduced fixtures of the real product page
and its own public sales-history page (see fixtures/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from spike import find_sales_history_link, parse_sales_history_page  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_finds_the_normal_ui_sales_history_link_on_the_product_page():
    soup = BeautifulSoup(_read_fixture("product_page_reduced.html"), "html.parser")
    href, diagnostics = find_sales_history_link(soup)
    assert href == "/apparels/104428/sales-histories"
    assert diagnostics["reason"] == "ok"


def test_no_link_found_is_explicit_not_a_guess():
    soup = BeautifulSoup("<html><body>no history link here</body></html>", "html.parser")
    href, diagnostics = find_sales_history_link(soup)
    assert href is None
    assert diagnostics["reason"] == "no_sales_history_link_found"


def test_parses_raw_conditions_a_through_c_with_dates_and_prices():
    html = _read_fixture("sales_history_page_reduced.html")
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "public_sold_history_available"
    conditions_in_sales = {s["condition"] for s in result["raw_sales"]}
    assert conditions_in_sales == {"A", "B", "C"}


def test_graded_psa_transactions_are_excluded():
    html = _read_fixture("sales_history_page_reduced.html")
    result = parse_sales_history_page(html, product_id="104428")
    assert all(s["condition"] != "PSA10" for s in result["raw_sales"])
    assert 170000 not in [s["price_jpy"] for s in result["raw_sales"]]


def test_sales_sorted_most_recent_first_and_capped_at_ten():
    html = _read_fixture("sales_history_page_reduced.html")
    result = parse_sales_history_page(html, product_id="104428")
    dates = [s["date"] for s in result["raw_sales"]]
    assert dates == sorted(dates, reverse=True)
    assert len(result["raw_sales"]) <= 10


def test_no_stable_sale_id_is_invented():
    html = _read_fixture("sales_history_page_reduced.html")
    result = parse_sales_history_page(html, product_id="104428")
    assert result["stable_identifier_available"] is False
    for sale in result["raw_sales"]:
        assert "id" not in sale
        assert set(sale.keys()) == {"product_id", "condition", "price_jpy", "date"}


def test_empty_condition_section_yields_no_sales_for_that_condition():
    html = _read_fixture("sales_history_page_reduced.html")
    result = parse_sales_history_page(html, product_id="104428")
    assert all(s["condition"] != "D" for s in result["raw_sales"])


def test_absent_sales_history_is_represented_explicitly_not_omitted():
    html = "<html><body><p>no market data on this page</p></body></html>"
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "not_exposed_on_current_product"
    assert result["raw_sales"] == []


def test_login_required_markers_without_any_visible_sales_is_flagged():
    html = """
    <html><body>
    ログインして売買履歴を見る
    </body></html>
    """
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "login_required"
    assert result["raw_sales"] == []
