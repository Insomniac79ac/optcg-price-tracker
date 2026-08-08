"""Tests for yuyutei_collector.extractor - the extraction logic moved out
of the live-validated spike. Uses the same committed fixture
(product_op01_001_reduced.html, a reduction of a genuine retrieved OP01-001
page) plus small synthetic HTML blocks isolating one specific disagreement
each, matching the pattern already used in
spikes/yuyutei-browser-feasibility/test_reliability.py.
"""

import unittest
from pathlib import Path

from yuyutei_collector.extractor import classify_page, extract_with_agreement

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"
EXPECTED_CARD_CODE = "OP01-001"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ClassifyPageTests(unittest.TestCase):
    def test_403_is_static_403(self):
        cls, evidence = classify_page(403, "<html>forbidden</html>", "403 Forbidden")
        self.assertEqual(cls, "static_403")
        self.assertIn("http_403", evidence)

    def test_429_is_challenge(self):
        cls, evidence = classify_page(429, "<html></html>", "")
        self.assertEqual(cls, "challenge_or_captcha")

    def test_normal_200_with_expected_markers_is_normal_product(self):
        html = load_fixture("product_op01_001_reduced.html")
        cls, evidence = classify_page(200, html, "P-L title", ["ロロノア・ゾロ", "パラレル"])
        self.assertEqual(cls, "normal_product")

    def test_weak_marker_alone_does_not_classify_as_challenge(self):
        # Cloudflare is Yuyu-Tei's own CDN - a bare mention must never alone
        # flip classification, only when expected content is also missing.
        html = "<html><body>served via cloudflare, product here</body></html>" + "x" * 500
        cls, evidence = classify_page(200, html, "normal page", ["product here"])
        self.assertEqual(cls, "normal_product")

    def test_weak_marker_with_missing_expected_content_is_challenge(self):
        html = "<html><body>cloudflare ray id 12345</body></html>" + "x" * 500
        cls, evidence = classify_page(200, html, "attention required", ["ロロノア・ゾロ"])
        self.assertEqual(cls, "challenge_or_captcha")


class ExtractWithAgreementSuccessTests(unittest.TestCase):
    def setUp(self):
        self.html = load_fixture("product_op01_001_reduced.html")

    def test_agreeing_jsonld_and_dom_extracts_successfully(self):
        result = extract_with_agreement(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["fail_reasons"], [])

    def test_price_agreement_holds_and_is_accepted(self):
        result = extract_with_agreement(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertTrue(result["agreement"]["price"]["agree"])
        self.assertEqual(
            result["agreement"]["price"]["jsonld_price"],
            result["agreement"]["price"]["dom_price"],
        )
        self.assertEqual(result["extracted"]["sell_price_jpy"], result["agreement"]["price"]["jsonld_price"])

    def test_stock_agreement_holds_and_resolves_out_of_stock(self):
        result = extract_with_agreement(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertTrue(result["agreement"]["stock"]["agree"])
        self.assertEqual(result["extracted"]["stock_status"], "out_of_stock")

    def test_card_code_and_treatment_match(self):
        result = extract_with_agreement(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["card_code"], "OP01-001")
        self.assertEqual(result["extracted"]["treatment"], "parallel")

    def test_whole_page_diagnostic_price_is_never_the_accepted_value(self):
        # The fixture's recommendation tile contains an unrelated 12,800円
        # price; a naive whole-page scan could grab any 円-suffixed price
        # on the page. The accepted value must be the agreed 34800, not a
        # diagnostic-only whole-page match.
        result = extract_with_agreement(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["sell_price_jpy"], 34800)


def _html_with(price_dom: str, price_jsonld: str, avail_jsonld: str, stock_dom: str) -> str:
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        '"name":"P-L ロロノア・ゾロ(パラレル)",'
        '"description":"OP01-001",'
        f'"offers":{{"@type":"Offer","price":"{price_jsonld}","priceCurrency":"JPY","availability":"{avail_jsonld}"}}}}'
        "</script></head><body>"
        '<div class="power" id="power"><h3>P-L ロロノア・ゾロ(パラレル)</h3></div>'
        '<section id="product-detail">'
        '<span class="pote">OP01-001</span>'
        f"<h4> {price_dom} 円</h4>"
        f"<label> 在庫 :   {stock_dom}   </label>"
        "</section></body></html>"
    )


class ExtractWithAgreementFailClosedTests(unittest.TestCase):
    def test_price_disagreement_fails_closed(self):
        html = _html_with("39,800", "34800", "InStock", "○")
        result = extract_with_agreement(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertFalse(result["agreement"]["price"]["agree"])
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertTrue(any(r.startswith("price_disagreement:") for r in result["fail_reasons"]))

    def test_stock_disagreement_fails_closed(self):
        html = _html_with("34,800", "34800", "InStock", "×")
        result = extract_with_agreement(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertFalse(result["agreement"]["stock"]["agree"])
        self.assertIsNone(result["extracted"]["stock_status"])
        # JSON-LD must never override a conflicting visible DOM value.
        self.assertNotEqual(result["extracted"]["stock_status"], "in_stock")

    def test_card_code_mismatch_fails_closed(self):
        html = load_fixture("product_op01_001_reduced.html")
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002")
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(any(r.startswith("card_code_conflict:") for r in result["fail_reasons"]))

    def test_treatment_mismatch_fails_closed(self):
        html = (
            "<html><head>"
            '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
            '"name":"P-N ロロノア・ゾロ(ノーマル)",'
            '"description":"OP01-001",'
            '"offers":{"@type":"Offer","price":"500","priceCurrency":"JPY","availability":"InStock"}}'
            "</script></head><body>"
            '<div class="power" id="power"><h3>P-N ロロノア・ゾロ(ノーマル)</h3></div>'
            '<section id="product-detail">'
            '<span class="pote">OP01-001</span>'
            "<h4> 500 円</h4>"
            "<label> 在庫 :   ○   </label>"
            "</section></body></html>"
        )
        result = extract_with_agreement(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(any(r.startswith("treatment_conflict:") for r in result["fail_reasons"]))

    def test_missing_jsonld_and_ambiguous_dom_fails_closed(self):
        html = "<html><body>" + "x" * 600 + "</body></html>"
        result = extract_with_agreement(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])


def _base_treatment_html(card_code: str = "OP01-002", price: str = "500") -> str:
    """A title with neither パラレル nor ノーマル - the base/default printing,
    exactly as Yuyu-Tei renders an unmarked (non-parallel) product title."""
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        '"name":"トラファルガー・ロー",'
        f'"description":"{card_code}",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"JPY","availability":"InStock"}}}}'
        "</script></head><body>"
        '<div class="power" id="power"><h3>トラファルガー・ロー</h3></div>'
        '<section id="product-detail">'
        f'<span class="pote">{card_code}</span>'
        f"<h4> {price} 円</h4>"
        "<label> 在庫 :   ○   </label>"
        "</section></body></html>"
    )


def _quantity_stock_html(qty: int, price: str = "12800", card_code: str = "OP01-002") -> str:
    """Yuyu-Tei's alternate stock display: an explicit remaining-quantity
    count ("在庫 : N 点") instead of a presence/absence symbol - seen live on
    OP01-002's parallel product page."""
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        '"name":"P-L トラファルガー・ロー(パラレル)",'
        f'"description":"{card_code}",'
        f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"JPY","availability":"InStock"}}}}'
        "</script></head><body>"
        '<div class="power" id="power"><h3>P-L トラファルガー・ロー(パラレル)</h3></div>'
        '<section id="product-detail">'
        f'<span class="pote">{card_code}</span>'
        f"<h4> {price} 円</h4>"
        f'<label id="cart_sell_zaiko_mobile"> 在庫 :   {qty} 点   </label>'
        "</section></body></html>"
    )


class QuantityStockNormalizationTests(unittest.TestCase):
    """Source-wide generalization: some Yuyu-Tei product pages show an
    explicit remaining-quantity count rather than an x/o presence symbol."""

    def test_positive_quantity_resolves_in_stock_and_agrees_with_jsonld(self):
        html = _quantity_stock_html(qty=3)
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002", expected_treatment="parallel")
        self.assertEqual(result["extracted"]["stock_status"], "in_stock")
        self.assertTrue(result["agreement"]["stock"]["agree"])
        self.assertEqual(result["extraction_status"], "extracted")

    def test_zero_quantity_resolves_out_of_stock_and_disagrees_with_jsonld_in_stock(self):
        html = _quantity_stock_html(qty=0)
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002", expected_treatment="parallel")
        self.assertEqual(result["agreement"]["stock"]["dom_stock"], "out_of_stock")
        self.assertFalse(result["agreement"]["stock"]["agree"])
        self.assertEqual(result["extraction_status"], "fail_closed")


def _discounted_price_html(list_price: str = "220", sale_price: str = "120", card_code: str = "OP01-013") -> str:
    """A struck-through former/list price alongside the current highlighted
    sale price - seen live on OP01-013's base product page."""
    return (
        "<html><head>"
        '<script type="application/ld+json">{"@context":"http://schema.org","@type":"Product",'
        '"name":"サンジ",'
        f'"description":"{card_code}",'
        f'"offers":{{"@type":"Offer","price":"{sale_price}","priceCurrency":"JPY","availability":"InStock"}}}}'
        "</script></head><body>"
        '<div class="power" id="power"><h3>サンジ</h3></div>'
        '<section id="product-detail">'
        f'<span class="pote">{card_code}</span>'
        f"<del> {list_price} 円</del>"
        f'<h4 class="text-danger"> {sale_price} 円</h4>'
        "<label> 在庫 :   ○   </label>"
        "</section></body></html>"
    )


class StrikethroughPriceExclusionTests(unittest.TestCase):
    """Source-wide generalization: a struck-through former/list price must
    never compete with the current sale price as a DOM candidate."""

    def test_struck_through_list_price_is_excluded_from_candidates(self):
        html = _discounted_price_html()
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-013", expected_treatment="normal")
        self.assertEqual(result["normalized"]["dom"]["price"], 120)
        self.assertEqual(result["extracted"]["sell_price_jpy"], 120)
        self.assertEqual(result["extraction_status"], "extracted")

    def test_only_the_sale_price_appears_in_dom_candidates(self):
        html = _discounted_price_html()
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-013", expected_treatment="normal")
        candidates = result["raw"]["dom"]["price_candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["normalized_price"], 120)


class ExpectedTreatmentParameterTests(unittest.TestCase):
    """extract_with_agreement must validate against whichever treatment the
    caller passes (its mapping/print's own treatment) - not a module-wide
    hardcoded expectation. Generalizes the collector beyond the single
    parallel-only vertical slice it started from."""

    def test_unmarked_title_resolves_to_normal_treatment(self):
        html = _base_treatment_html()
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002", expected_treatment="normal")
        self.assertEqual(result["extracted"]["treatment"], "normal")
        self.assertEqual(result["extraction_status"], "extracted")

    def test_base_product_does_not_fail_closed_when_normal_is_expected(self):
        html = _base_treatment_html()
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002", expected_treatment="normal")
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertFalse(any(r.startswith("treatment_conflict") for r in result["fail_reasons"]))

    def test_base_product_fails_closed_when_parallel_is_expected(self):
        html = _base_treatment_html()
        result = extract_with_agreement(html, PRODUCT_URL, "OP01-002", expected_treatment="parallel")
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(any(r.startswith("treatment_conflict:displayed=normal,expected=parallel") for r in result["fail_reasons"]))

    def test_default_expected_treatment_remains_parallel_for_existing_callers(self):
        html = load_fixture("product_op01_001_reduced.html")
        # No expected_treatment argument passed - must behave exactly as
        # before this generalization for any caller that doesn't pass one.
        result = extract_with_agreement(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "extracted")


if __name__ == "__main__":
    unittest.main()
