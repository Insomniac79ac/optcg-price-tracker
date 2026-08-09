"""Offline, deterministic tests for snkrdunk_collector.sales_history, against
a reduced fixture of the real public sales-history page (see
fixtures/sales_history_page_reduced.html). These functions are used for
evidence/logging only - see writer.py, which never persists an individual
sold row."""

from pathlib import Path

from bs4 import BeautifulSoup

from snkrdunk_collector.sales_history import find_sales_history_link, parse_sales_history_page

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_finds_the_normal_ui_sales_history_link_on_the_product_page():
    soup = BeautifulSoup(_read_fixture("product_page_reduced.html"), "html.parser")
    href, diagnostics = find_sales_history_link(soup)
    assert href == "/apparels/104428/sales-histories"
    assert diagnostics["reason"] == "ok"


def test_parses_raw_conditions_with_dates_and_prices():
    result = parse_sales_history_page(_read_fixture("sales_history_page_reduced.html"), product_id="104428")
    assert result["availability_status"] == "public_sold_history_available"
    assert {s["condition"] for s in result["raw_sales"]} == {"A", "B", "C"}


def test_graded_psa_transactions_are_excluded():
    result = parse_sales_history_page(_read_fixture("sales_history_page_reduced.html"), product_id="104428")
    assert all(s["condition"] != "PSA10" for s in result["raw_sales"])
    assert 170000 not in [s["price_jpy"] for s in result["raw_sales"]]


def test_sold_history_rows_are_never_marked_with_a_stable_identifier():
    """Core dedupe-safety decision (see sales_history.py's module docstring):
    no field here may claim to uniquely identify a sale - the writer relies
    on this flag to never persist these rows as price_observations."""
    result = parse_sales_history_page(_read_fixture("sales_history_page_reduced.html"), product_id="104428")
    assert result["stable_identifier_available"] is False
    for sale in result["raw_sales"]:
        assert set(sale.keys()) == {"product_id", "condition", "price_jpy", "date"}


def test_absent_sales_history_is_represented_explicitly_not_omitted():
    result = parse_sales_history_page("<html><body>no market data</body></html>", product_id="104428")
    assert result["availability_status"] == "not_exposed_on_current_product"
    assert result["raw_sales"] == []
