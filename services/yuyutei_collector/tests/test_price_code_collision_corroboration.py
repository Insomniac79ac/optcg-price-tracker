"""The card-code collision guard applies only to an UNCORROBORATED price.

WHAT THIS PROTECTS. On 2026-09-02 the first full 214-mapping scheduled run
attempted every eligible mapping and wrote 211. Two of the three failures were
the same defect: `OP13-050` is sold for 50 JPY and `EB01-030` for 30, and the
guard rejected both because the price equals a digit group in the card's own
number. Neither page was malformed. The run's own diagnostics for OP13-050
recorded a single DOM leaf candidate (`h4.fw-bold.d-inline-block`, "50 円")
and a JSON-LD offer price of 50 - two independent extractors, agreeing to the
yen - and the observation was discarded anyway. EB01-030 left no retained log
at all, because a fail-closed extraction persists neither observation nor raw
snapshot; the discovery candidate row (30 JPY, code EB01-030) is what
identified it.

WHY THE GUARD WAS RIGHT AND IS NOW TOO WIDE. It was written for a flattened
text extractor where a card code really could be misread as a price ("OP01"
-> 1 JPY). Its question - does this number also appear in the code? - is a
proxy for "did we harvest a code instead of a price". It was never a claim
that such a price cannot exist. The proxy has no way to tell 50-JPY-because-
the-page-says-50 from 50-JPY-because-we-read-"050", so it refuses both.
Independent agreement can tell them apart: a JSON-LD offer price is structured
schema.org data rather than text scraped near a code, so it cannot carry the
contamination the proxy looks for.

The exposure was not one card. Seven of the 214 approved print-linked mappings
have a code digit group that lands on the observed Yuyu price ladder, and the
three colliding values (30, 50, 80) are the three commonest prices on that
ladder - so a passing card becomes a failing one purely by being repriced.

SCOPE. Only the guard's applicability changed. Every other gate - agreement,
ambiguity, identity, treatment - is asserted unchanged below, because the
point of the fix is that agreement is now the thing being trusted, and it
would be worthless if agreement itself had been loosened.
"""

import re
import unittest

from yuyutei_collector.extractor import (
    _price_matches_code_digits,
    extract_with_agreement,
)

from test_card_code_grammar import URL, product_html


def strip_jsonld(html: str) -> str:
    """The same removal test_card_code_grammar uses for its indeterminate
    case - leaves the DOM price intact and the JSON-LD side missing."""
    return html[: html.index("<script")] + html[html.index("</script>") + 9 :]


class CorroboratedCollisionIsAccepted(unittest.TestCase):
    """A: the OP13-050 case, B: the EB01-030 case, C: the synthetic 055 one."""

    def _assert_accepted(self, code, name, price, url, expected):
        result = extract_with_agreement(
            product_html(code, name, price), url, code, expected_treatment=None
        )
        self.assertEqual(result["extraction_status"], "extracted", result["fail_reasons"])
        self.assertEqual(result["extracted"]["sell_price_jpy"], expected)
        self.assertEqual(
            [r for r in result["fail_reasons"] if "card_code_or_id_digits" in r], []
        )
        # accepted via the DOM-scoped leaf tier, agreeing with JSON-LD
        self.assertEqual(result["dom_price_tier"], "leaf_element_scoped")
        self.assertTrue(result["agreement"]["price"]["agree"])
        self.assertEqual(result["agreement"]["price"]["dom_price"], expected)
        self.assertEqual(result["agreement"]["price"]["jsonld_price"], expected)
        return result

    def test_op13_050_at_50_yen_is_accepted(self):
        """A. Mapping 351. 'OP13-050' contains the digit group 050."""
        self._assert_accepted(
            "OP13-050",
            "R ボア・サンダーソニア",
            "50",
            "https://yuyu-tei.jp/sell/opc/card/op13/10060",
            50,
        )

    def test_eb01_030_at_30_yen_is_accepted(self):
        """B. Mapping 391 - the failure that left no log to explain it."""
        self._assert_accepted(
            "EB01-030",
            "C ローグタウン",
            "30",
            "https://yuyu-tei.jp/sell/opc/card/eb01/10039",
            30,
        )

    def test_synthetic_055_collision_is_accepted(self):
        """C. The case the previous suite pinned the other way round."""
        self._assert_accepted("EB01-055", "C シャーロット・コンポート", "55", URL, 55)

    def test_collision_against_the_external_product_id_is_also_accepted(self):
        """The guard reads digit groups from the URL's product id as well as
        the card code, so corroboration has to cover that half too."""
        result = self._assert_accepted(
            "EB01-055",
            "C シャーロット・コンポート",
            "10071",
            URL,
            10071,
        )
        # 10071 is the product id in URL, i.e. a real collision source
        self.assertEqual(result["extracted"]["external_product_id"], "eb01-10071")
        self.assertTrue(_price_matches_code_digits(10071, "EB01-055", "eb01-10071"))


class UncorroboratedCollisionIsStillRejected(unittest.TestCase):
    """D and E: everything the guard was protecting is still refused."""

    def test_collision_price_without_jsonld_is_rejected(self):
        """D. DOM says 55 and nothing corroborates it. The page is refused and
        no price is written - which is the outcome the guard exists to force."""
        html = strip_jsonld(product_html("EB01-055", "C シャーロット・コンポート", "55"))
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertIn(
            "price_agreement_indeterminate:missing_jsonld_or_dom_value",
            result["fail_reasons"],
        )

    def test_the_collision_predicate_itself_is_unchanged(self):
        """D, continued. Narrowing changed WHEN the guard is consulted, not
        what it detects - so the predicate keeps its teeth for any future path
        that accepts a price without a second source. This is the assertion
        that would fail if a later edit deleted the rule outright."""
        self.assertTrue(_price_matches_code_digits(1, "OP01-001", None))
        self.assertTrue(_price_matches_code_digits(50, "OP13-050", None))
        self.assertTrue(_price_matches_code_digits(30, "EB01-030", None))
        self.assertTrue(_price_matches_code_digits(10071, None, "eb01-10071"))
        self.assertFalse(_price_matches_code_digits(80, "OP01-027", "op01-10035"))

    def test_disagreement_where_one_side_matches_code_digits_is_rejected(self):
        """E. DOM 55 (a collision) against JSON-LD 430. Disagreement decides
        it, and no price is written."""
        html = product_html("EB01-055", "C シャーロット・コンポート", "430").replace(
            '<h4 class="fw-bold d-inline-block">430 円</h4>',
            '<h4 class="fw-bold d-inline-block">55 円</h4>',
        )
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertIn("price_disagreement:jsonld=430,dom=55", result["fail_reasons"])

    def test_jsonld_absent_is_unchanged(self):
        """F. Non-colliding price, JSON-LD removed - the pre-existing
        fail-closed result, asserted here so the narrowing cannot be blamed
        for a change in it."""
        html = strip_jsonld(product_html("EB01-055", "C シャーロット・コンポート", "430"))
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertIn(
            "price_agreement_indeterminate:missing_jsonld_or_dom_value",
            result["fail_reasons"],
        )


class DomScopingStillExcludesCodeDigits(unittest.TestCase):
    """G. The 円卓 case - why the guard is no longer load-bearing here.

    'OP01-027 円卓' is the shape that makes a flattened scan dangerous: the
    name begins with 円, so `<digits> 円` matches across the code and the
    name and yields 27. That adjacency is real in discovery's flattened
    listing text. It is not reachable from the collector, because a price
    candidate must be a LEAF whose entire text is a price, and the leaf-level
    price sits in the product container while the name does not.
    """

    def _page_with_listing_shaped_summary(self):
        html = product_html("OP01-027", "円卓", "80")
        # A breadcrumb/summary carrying the listing-page adjacency verbatim,
        # deliberately OUTSIDE div.product-detailing.
        return html.replace(
            '<div id="power">', '<div class="summary">OP01-027 円卓 80 円</div><div id="power">'
        )

    def test_the_flattened_adjacency_really_is_present(self):
        """Without this the next test proves nothing: it confirms a naive
        whole-text scan does find 27 on this page."""
        text = re.sub(r"<[^>]+>", " ", self._page_with_listing_shaped_summary())
        m = re.search(r"([\d,]+)\s*円", text)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1).replace(",", "")), 27)

    def test_the_extractor_takes_80_not_27(self):
        result = extract_with_agreement(
            self._page_with_listing_shaped_summary(),
            "https://yuyu-tei.jp/sell/opc/card/op01/10035",
            "OP01-027",
            expected_treatment=None,
        )
        self.assertEqual(result["extraction_status"], "extracted", result["fail_reasons"])
        self.assertEqual(result["extracted"]["sell_price_jpy"], 80)
        self.assertEqual(result["dom_price_tier"], "leaf_element_scoped")
        self.assertNotIn(27, [c["normalized_price"] for c in result["raw"]["dom"]["price_candidates"]])


class OtherGatesUnchanged(unittest.TestCase):
    """The narrowing trusts agreement, so the gates around it must still bite."""

    def test_ambiguous_dom_candidates_still_fail(self):
        html = product_html("EB01-055", "C シャーロット・コンポート", "430").replace(
            '<label id="cart_sell_zaiko_mobile">',
            '<h4 class="fw-bold d-inline-block">999 円</h4><label id="cart_sell_zaiko_mobile">',
        )
        result = extract_with_agreement(html, URL, "EB01-055", expected_treatment=None)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])

    def test_card_code_conflict_still_fails(self):
        result = extract_with_agreement(
            product_html("EB01-055", "C シャーロット・コンポート", "430"),
            URL,
            "EB01-054",
            expected_treatment=None,
        )
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(
            any(r.startswith("card_code_conflict") for r in result["fail_reasons"])
        )

    def test_treatment_conflict_still_fails(self):
        result = extract_with_agreement(
            product_html("EB01-055", "C シャーロット・コンポート", "430"),
            URL,
            "EB01-055",
            expected_treatment="parallel",
        )
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertTrue(
            any(r.startswith("treatment_conflict") for r in result["fail_reasons"])
        )

    def test_promotion_state_is_untouched_by_the_narrowing(self):
        """promotion_state is descriptive and never a gate; a corroborated
        collision price must still carry its ordinary verdict."""
        result = extract_with_agreement(
            product_html("OP13-050", "R ボア・サンダーソニア", "50"),
            "https://yuyu-tei.jp/sell/opc/card/op13/10060",
            "OP13-050",
            expected_treatment=None,
        )
        self.assertEqual(result["extracted"]["sell_price_jpy"], 50)
        self.assertEqual(result["extracted"]["promotion_state"], "none")


if __name__ == "__main__":
    unittest.main()
