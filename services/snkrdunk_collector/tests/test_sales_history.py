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


# --- login_required must describe the history UI, not the site chrome --------

GLOBAL_LOGIN_NAV = (
    '<header><nav><a href="/login">ログイン</a><a href="/signup">会員登録</a></nav></header>'
)


def test_global_login_nav_does_not_imply_sold_history_login_required():
    """SNKRDUNK renders a "ログイン" link in its global header on every page,
    signed in or not. A product that simply has no sales yet must report
    not_exposed_on_current_product - never login_required."""
    html = f"<html><body>{GLOBAL_LOGIN_NAV}<main><p>まだ取引がありません</p></main></body></html>"
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "not_exposed_on_current_product"
    assert result["content_login_marker"] is None


def test_global_login_nav_does_not_override_a_real_public_history():
    """Structure wins: a real history UI proves the page is not gated even
    with the global login link present."""
    fixture = _read_fixture("sales_history_page_reduced.html")
    html = fixture.replace("<body>", f"<body>{GLOBAL_LOGIN_NAV}", 1)
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "public_sold_history_available"


def test_login_marker_inside_the_content_area_is_still_reported():
    """A genuinely gated history - the login prompt is in the content, not
    the chrome, and no history UI is present."""
    html = (
        f"<html><body>{GLOBAL_LOGIN_NAV}"
        '<main><p>売買履歴を見るにはログインしてください</p></main></body></html>'
    )
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "login_required"
    assert result["content_login_marker"] is not None


def test_footer_login_link_is_treated_as_chrome_not_evidence():
    html = (
        "<html><body><main><p>まだ取引がありません</p></main>"
        '<footer><a href="/login">ログイン</a></footer></body></html>'
    )
    result = parse_sales_history_page(html, product_id="104428")
    assert result["availability_status"] == "not_exposed_on_current_product"
