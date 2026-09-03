"""One card-code grammar, shared by discovery and extraction.

WHAT THIS PROTECTS. The pattern was declared twice under the same name with
two different meanings - discovery's covered all five catalogue shapes,
extraction's was OP-only - and nothing linked them. On 2026-09-01 the
collector fetched four approved EB-01 product pages, all HTTP 200, all
serving the code, price and stock in exactly the same markup as an OP page,
and wrote nothing: the OP-only pattern matched no card code, so the container
gate selected nothing and the code/price/stock readers that take that
container were each starved in turn.

So the tests below are in two halves. The grammar half pins what the pattern
accepts and rejects. The extractor half drives the REAL
`extract_with_agreement` path over same-structure HTML for every family,
because a regex test alone would not have caught the original bug - the
pattern was individually correct in discovery and the failure lived in how
extraction consumed it. The last test is the drift guard: all three modules
must be the same object, not merely equal patterns.

Fixture HTML mirrors the structure captured live from Yuyu-Tei on 2026-09-01
(container `div.product-detailing`, price leaf `h4.fw-bold.d-inline-block`,
stock label `#cart_sell_zaiko_mobile`, code in a bordered `span`), which was
verified byte-identical in shape between OP01 and EB01 pages. No live request
is made here.
"""

import unittest

from yuyutei_collector import card_code, discover, extractor
from yuyutei_collector.card_code import CARD_CODE_RE
from yuyutei_collector.extractor import extract_with_agreement


def product_html(code: str, name: str, price: str, stock: str = "在庫 :   ◯") -> str:
    """One product page in the real captured shape. The price appears in the
    DOM leaf AND, independently, in the JSON-LD block - which is what the
    agreement rule requires."""
    return f"""
    <html><head><title>{name} 販売</title>
    <script type="application/ld+json">
    {{"@context":"https://schema.org","@type":"Product",
      "name":"{name}","description":"{code}",
      "image":"https://card.yuyu-tei.jp/opc/front/x/1.jpg",
      "offers":{{"@type":"Offer","price":"{price}","priceCurrency":"JPY",
                 "availability":"https://schema.org/InStock"}}}}
    </script></head>
    <body>
      <div id="power"><h3>{name}</h3></div>
      <div class="product-detailing">
        <span class="border border-dark py-1 fw-bold px-4 text-center my-2 fs-11 pote">{code}</span>
        <h4 class="fw-bold d-inline-block">{price} 円</h4>
        <label id="cart_sell_zaiko_mobile">{stock}</label>
      </div>
      <div class="recommend"><strong class="d-block text-end">9,999 円</strong></div>
    </body></html>
    """


URL = "https://yuyu-tei.jp/sell/opc/card/eb01/10071"

# One representative product per catalogue family. Prices are deliberately not
# equal to any digit-group inside their own code, so the historical
# "OP01 -> 1 JPY" guard (_price_matches_code_digits) cannot fire and mask a
# result.
FAMILIES = [
    ("OP01-005", "R ウタ", "120"),
    ("ST01-005", "R サンジ", "320"),
    ("EB01-055", "C シャーロット・コンポート", "430"),
    ("PRB01-001", "L モンキー・D・ルフィ", "780"),
    ("P-014", "P ナミ", "220"),
]


class GrammarTests(unittest.TestCase):
    def test_every_catalogue_family_is_accepted(self):
        for code, _, _ in FAMILIES:
            with self.subTest(code=code):
                self.assertIsNotNone(CARD_CODE_RE.fullmatch(code))

    def test_representative_malformed_and_near_miss_values_are_rejected(self):
        for bad in (
            "OP1-005",       # one-digit set number
            "OP001-005",     # three-digit set number
            "OP01-05",       # two-digit card number
            "OP01-0055",     # four-digit card number
            "XX01-005",      # unknown family
            "P-0140",        # promo with four digits
            "P-14",          # promo with two digits
            "PRB1-001",      # PRB with one-digit set number
            "OP01_005",      # wrong separator
            "OP01005",       # no separator
            "",              # empty
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(CARD_CODE_RE.fullmatch(bad))

    def test_prb_is_never_read_as_a_promo(self):
        """PRB is tried before the P branch; "PRB01-001" must match whole."""
        self.assertEqual(CARD_CODE_RE.search("PRB01-001").group(0), "PRB01-001")

    def test_a_code_embedded_in_a_longer_token_is_not_matched(self):
        """Word-bounded at both ends, so an image path or slug containing the
        digits is not mistaken for a displayed card code."""
        self.assertIsNone(CARD_CODE_RE.search("XOP01-005X"))
        self.assertIsNone(CARD_CODE_RE.search("EB01-0551"))

    def test_a_code_is_found_inside_ordinary_page_text(self):
        m = CARD_CODE_RE.search("C シャーロット・コンポート ZOOM EB01-055 30 円 在庫 : ◯")
        self.assertEqual(m.group(0), "EB01-055")


class ExtractorFamilyTests(unittest.TestCase):
    """The real agreement path, once per family - A through E."""

    def _extract(self, code, name, price):
        return extract_with_agreement(
            product_html(code, name, price), URL, code, expected_treatment=None
        )

    def test_every_family_extracts_through_the_real_agreement_path(self):
        for code, name, price in FAMILIES:
            with self.subTest(code=code):
                result = self._extract(code, name, price)
                self.assertEqual(result["extraction_status"], "extracted", result["fail_reasons"])
                self.assertEqual(result["fail_reasons"], [])
                self.assertEqual(result["extracted"]["card_code"], code)
                self.assertEqual(result["extracted"]["sell_price_jpy"], int(price))
                self.assertEqual(result["extracted"]["stock_status"], "in_stock")

    def test_op_behaviour_is_unchanged(self):
        """A - the family that already worked still works, by the same route:
        container found, leaf-level price tier, both sides agreeing."""
        result = self._extract("OP01-005", "R ウタ", "120")
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["dom_price_tier"], "leaf_element_scoped")
        self.assertEqual(result["accepted_selectors"]["main_container"], "div.product-detailing")
        self.assertEqual(
            result["accepted_selectors"]["price_selector"], "h4.fw-bold.d-inline-block"
        )
        self.assertEqual(
            result["accepted_selectors"]["stock_selector"], "label#cart_sell_zaiko_mobile"
        )
        self.assertTrue(result["agreement"]["price"]["agree"])

    def test_eb01_same_structure_html_now_extracts(self):
        """B - the exact failure from the canary, on the exact page shape the
        live probe captured. Every one of the four symptoms is now absent."""
        result = self._extract("EB01-055", "C シャーロット・コンポート", "430")
        self.assertEqual(result["extraction_status"], "extracted", result["fail_reasons"])
        self.assertEqual(result["normalized"]["dom"]["card_code"], "EB01-055")
        self.assertEqual(result["normalized"]["jsonld"]["card_code"], "EB01-055")
        self.assertIsNotNone(result["raw"]["dom"]["container"])
        self.assertNotEqual(result["raw"]["dom"]["price_candidates"], [])
        self.assertIsNotNone(result["raw"]["dom"]["stock_element"])

    def test_st_code_is_no_longer_rejected(self):
        result = self._extract("ST01-005", "R サンジ", "320")
        self.assertEqual(result["extracted"]["card_code"], "ST01-005")
        self.assertNotIn(
            "card_code_conflict:displayed=None,expected=ST01-005", result["fail_reasons"]
        )

    def test_prb_code_is_no_longer_rejected(self):
        result = self._extract("PRB01-001", "L モンキー・D・ルフィ", "780")
        self.assertEqual(result["extracted"]["card_code"], "PRB01-001")

    def test_promo_code_is_no_longer_rejected(self):
        result = self._extract("P-014", "P ナミ", "220")
        self.assertEqual(result["extracted"]["card_code"], "P-014")


class FailClosedUnchangedTests(unittest.TestCase):
    """F, G, H - widening the grammar must not widen what is accepted."""

    def test_mismatched_expected_and_displayed_code_still_fails_closed(self):
        result = extract_with_agreement(
            product_html("EB01-055", "C シャーロット・コンポート", "430"),
            URL,
            "EB01-002",  # a different, equally valid code
            expected_treatment=None,
        )
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIn(
            "card_code_conflict:displayed=EB01-055,expected=EB01-002", result["fail_reasons"]
        )

    def test_dom_and_jsonld_price_disagreement_still_fails_closed(self):
        html = product_html("EB01-055", "C シャーロット・コンポート", "430").replace(
            '<h4 class="fw-bold d-inline-block">430 円</h4>',
            '<h4 class="fw-bold d-inline-block">999 円</h4>',
        )
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIn("price_disagreement:jsonld=430,dom=999", result["fail_reasons"])
        self.assertIsNone(result["extracted"]["sell_price_jpy"])

    def test_missing_jsonld_still_fails_closed(self):
        html = product_html("EB01-055", "C シャーロット・コンポート", "430")
        html = html[: html.index("<script")] + html[html.index("</script>") + 9 :]
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIn(
            "price_agreement_indeterminate:missing_jsonld_or_dom_value", result["fail_reasons"]
        )
        self.assertIsNone(result["extracted"]["sell_price_jpy"])

    def test_missing_dom_price_still_fails_closed(self):
        """The container survives (it still holds a code and the JSON-LD's own
        text is not in it), but no DOM price means no agreement."""
        html = product_html("EB01-055", "C シャーロット・コンポート", "430").replace(
            '<h4 class="fw-bold d-inline-block">430 円</h4>', ""
        )
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])

    def test_a_corroborated_price_equal_to_a_code_digit_group_is_accepted(self):
        """Was `..._is_still_refused`, asserting that an agreed 55 for EB01-055
        must fail closed. That premise is gone: the code-digit rule is a proxy
        for "we harvested a code instead of a price", and two independent
        extractors agreeing answers that question directly and better. This
        page states 55 in the DOM leaf and in the JSON-LD offer, so 55 is the
        price. The guard itself is unchanged for the uncorroborated case -
        see test_price_code_collision_corroboration.py."""
        result = extract_with_agreement(
            product_html("EB01-055", "C シャーロット・コンポート", "55"),
            URL,
            "EB01-055",
            expected_treatment=None,
        )
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["extracted"]["sell_price_jpy"], 55)
        self.assertEqual(
            [r for r in result["fail_reasons"] if "card_code_or_id_digits" in r], []
        )

    def test_treatment_conflict_still_fails_closed(self):
        result = extract_with_agreement(
            product_html("EB01-055", "C シャーロット・コンポート", "430"),
            URL,
            "EB01-055",
            expected_treatment="parallel",
        )
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIn(
            "treatment_conflict:displayed=normal,expected=parallel", result["fail_reasons"]
        )


class DriftGuardTests(unittest.TestCase):
    def test_discovery_and_extraction_share_one_object(self):
        """Identity, not equality: two modules can hold equal patterns and
        still drift the moment one is edited. This is what was missing."""
        self.assertIs(extractor.CARD_CODE_RE, card_code.CARD_CODE_RE)
        self.assertIs(discover.CARD_CODE_RE, card_code.CARD_CODE_RE)

    def test_the_downstream_discovery_importers_share_it_too(self):
        from yuyutei_collector import discovery_listing, discovery_probe

        self.assertIs(discovery_listing.CARD_CODE_RE, card_code.CARD_CODE_RE)
        self.assertIs(discovery_probe.CARD_CODE_RE, card_code.CARD_CODE_RE)

    def test_the_grammar_is_declared_exactly_once(self):
        """A second `CARD_CODE_RE = re.compile(...)` anywhere in the package
        is the drift itself, so it is banned structurally rather than by
        convention."""
        import pathlib

        pkg = pathlib.Path(card_code.__file__).parent
        definers = [
            path.name
            for path in sorted(pkg.glob("*.py"))
            if "CARD_CODE_RE = re.compile(" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(definers, ["card_code.py"])

    def test_the_shared_module_pulls_in_no_heavy_dependency(self):
        """card_code must stay importable without Playwright - that is why the
        grammar does not simply live in discover.py, which imports it."""
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(card_code.__file__).read_text(encoding="utf-8"))
        imported = {
            (alias.name.split(".")[0])
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertEqual(imported - {"__future__", "annotations"}, {"re"})


if __name__ == "__main__":
    unittest.main()
