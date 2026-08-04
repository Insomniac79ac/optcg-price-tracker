"""Focused, offline tests for the static-IP reliability aggregation,
scoped-extraction, and incremental-persistence helpers - no network, no
Playwright, no live browser, no Yuyu-Tei request.
extract_product_from_html() takes a plain HTML string (parsed with
BeautifulSoup), not a Page, so it's directly unit-testable against local
fixture files.

Run with: python3 -m pytest test_reliability.py -v
"""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spike import (
    EGRESS_IP_DISCLAIMER,
    EXPECTED_CARD_CODE,
    PRODUCT_URL,
    _normalize_price_text,
    _price_matches_code_digits,
    append_check_result,
    extract_product_from_html,
    log_event,
    summarize_checks_by_egress_ip,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures"


def load_fixture(filename: str) -> str:
    """Read a committed fixture by name - see test_classifier.py's
    load_fixture for the same pattern/rationale. Fixtures under
    tests/fixtures/ are reduced, hand-trimmed stand-ins for genuine
    retrieved pages, never the full captured HTML (see
    tests/fixtures/product_op01_001_reduced.html's header comment for
    provenance)."""
    path = FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing committed test fixture: {path}\n"
            "Fixtures must live under tests/fixtures/ and be committed "
            "alongside test_reliability.py."
        )
    return path.read_text(encoding="utf-8")


class SummarizeChecksByEgressIpTests(unittest.TestCase):
    def test_groups_by_ip_and_counts_statuses(self):
        checks = [
            {"diagnostic_egress_ip": "1.1.1.1", "http_status": 200, "classification": "normal_product", "elapsed_s": 1.0},
            {"diagnostic_egress_ip": "1.1.1.1", "http_status": 403, "classification": "static_403", "elapsed_s": 2.0},
            {"diagnostic_egress_ip": "2.2.2.2", "http_status": 200, "classification": "normal_product", "elapsed_s": 3.0},
        ]
        summary = summarize_checks_by_egress_ip(checks)
        by_ip = {g["egress_ip"]: g for g in summary}

        self.assertEqual(by_ip["1.1.1.1"]["checks_observed"], 2)
        self.assertEqual(by_ip["1.1.1.1"]["http_200_count"], 1)
        self.assertEqual(by_ip["1.1.1.1"]["http_403_count"], 1)
        self.assertEqual(by_ip["1.1.1.1"]["average_elapsed_s"], 1.5)

        self.assertEqual(by_ip["2.2.2.2"]["checks_observed"], 1)
        self.assertEqual(by_ip["2.2.2.2"]["http_200_count"], 1)

    def test_preserves_first_seen_ip_order(self):
        checks = [
            {"diagnostic_egress_ip": "9.9.9.9", "http_status": 200, "classification": "normal_product", "elapsed_s": 1.0},
            {"diagnostic_egress_ip": "1.1.1.1", "http_status": 200, "classification": "normal_product", "elapsed_s": 1.0},
            {"diagnostic_egress_ip": "9.9.9.9", "http_status": 200, "classification": "normal_product", "elapsed_s": 1.0},
        ]
        summary = summarize_checks_by_egress_ip(checks)
        self.assertEqual([g["egress_ip"] for g in summary], ["9.9.9.9", "1.1.1.1"])

    def test_missing_ip_grouped_as_unknown(self):
        checks = [{"diagnostic_egress_ip": None, "http_status": None, "classification": "navigation_error", "elapsed_s": None}]
        summary = summarize_checks_by_egress_ip(checks)
        self.assertEqual(summary[0]["egress_ip"], "unknown")
        self.assertEqual(summary[0]["other_status_count"], 1)
        self.assertIsNone(summary[0]["average_elapsed_s"])

    def test_challenge_and_429_counted_separately_from_403(self):
        checks = [
            {"diagnostic_egress_ip": "1.1.1.1", "http_status": 429, "classification": "challenge_or_captcha", "elapsed_s": 1.0},
        ]
        summary = summarize_checks_by_egress_ip(checks)
        self.assertEqual(summary[0]["http_429_count"], 1)
        self.assertEqual(summary[0]["challenge_count"], 1)
        self.assertEqual(summary[0]["http_403_count"], 0)

    def test_empty_checks_returns_empty_summary(self):
        self.assertEqual(summarize_checks_by_egress_ip([]), [])


class NormalizePriceTextTests(unittest.TestCase):
    def test_strips_comma_and_yen_sign(self):
        self.assertEqual(_normalize_price_text("¥34,800"), 34800)

    def test_strips_yen_kanji_suffix(self):
        self.assertEqual(_normalize_price_text("34,800 円"), 34800)

    def test_no_digits_returns_none(self):
        self.assertIsNone(_normalize_price_text("在庫あり"))


class PriceMatchesCodeDigitsTests(unittest.TestCase):
    """Direct regression coverage for the exact shape of the old bug: the
    v2 regex matched "販売" in a breadcrumb, then captured "01" out of
    "[OP01]" as the price, and int("01") == 1. This guard exists so that
    even if some future extraction tier ever produced "1" as a candidate
    price, it would still be rejected because 1 == int("01") is a digit
    group of the card code itself."""

    def test_op01_prefix_digit_group_matches_price_1(self):
        self.assertTrue(_price_matches_code_digits(1, "OP01-001", None))

    def test_external_id_digit_group_matches(self):
        self.assertTrue(_price_matches_code_digits(10002, None, "op01-10002"))

    def test_genuine_price_does_not_match(self):
        self.assertFalse(_price_matches_code_digits(34800, "OP01-001", "op01-10002"))

    def test_no_codes_never_matches(self):
        self.assertFalse(_price_matches_code_digits(1, None, None))


class JsonldExtractionTests(unittest.TestCase):
    """Uses the reduced fixture reproducing the genuine retrieved OP01-001
    page's real JSON-LD Product block."""

    def setUp(self):
        self.html = load_fixture("product_op01_001_reduced.html")

    def test_main_product_price_selected_from_structured_data(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["extraction_path"], "jsonld_structured_data")
        self.assertEqual(result["extracted"]["sell_price_jpy"], 34800)
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 1)

    def test_card_code_and_treatment_checks_still_work(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["card_code"], "OP01-001")
        self.assertEqual(result["extracted"]["treatment"], "parallel")
        self.assertTrue(result["validation"]["card_code_matches_expected"])
        self.assertTrue(result["validation"]["treatment_matches_expected"])

    def test_stock_out_of_stock_from_structured_availability(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["stock_status"], "out_of_stock")

    def test_recommendation_price_ignored(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        # The fixture's one recommendation tile is priced 12,800円 - it must
        # never be the accepted price.
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 12800)

    def test_op01_never_parsed_as_1_jpy(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 1)


class DomScopedExtractionTests(unittest.TestCase):
    """Same real DOM, but JSON-LD absent - forces the priority-2 DOM-scoped
    element-selector path (see product_op01_001_no_jsonld.html)."""

    def setUp(self):
        self.html = load_fixture("product_op01_001_no_jsonld.html")

    def test_main_product_price_selected_via_dom(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "extracted")
        self.assertEqual(result["extraction_path"], "dom_selector_scoped")
        self.assertEqual(result["extracted"]["sell_price_jpy"], 34800)

    def test_price_evidence_identifies_selector_and_container(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertIn("h4", result["validation"]["accepted_selector"])
        self.assertIn("34,800", result["validation"]["raw_price_text"])
        self.assertEqual(result["selector_diagnostics"]["main_container"], "div.product-detailing")

    def test_recommendation_prices_ignored_even_with_two_tiles(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        # Fixture has two recommendation tiles (12,800円 and 80円) outside
        # the product-detailing container - neither may win.
        self.assertNotIn(result["extracted"]["sell_price_jpy"], (12800, 80))

    def test_stock_comes_from_product_container_not_whole_page(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["stock_status"], "out_of_stock")

    def test_card_code_and_treatment_checks_still_work(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extracted"]["card_code"], "OP01-001")
        self.assertEqual(result["extracted"]["treatment"], "parallel")

    def test_op01_never_parsed_as_1_jpy(self):
        result = extract_product_from_html(self.html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 1)


class BreadcrumbOnlyRegressionTests(unittest.TestCase):
    """Reproduces the exact text shape that caused the original bug (販売
    immediately followed by [OP01] in a breadcrumb) with no JSON-LD and no
    recognizable product container at all - i.e. the worst case, where only
    the diagnostic whole-page scan has anything to look at."""

    BREADCRUMB_ONLY_HTML = (
        "<html><body>"
        '<h1 class="position-absolute">P-L ロロノア・ゾロ(パラレル) | 販売 | '
        "[OP01]ROMANCE DAWN | ONE PIECEカードゲーム</h1>"
        "</body></html>"
    )

    def test_fails_closed_not_extracted(self):
        result = extract_product_from_html(self.BREADCRUMB_ONLY_HTML, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")

    def test_price_is_never_1_jpy(self):
        result = extract_product_from_html(self.BREADCRUMB_ONLY_HTML, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 1)

    def test_extraction_path_is_diagnostic_only(self):
        result = extract_product_from_html(self.BREADCRUMB_ONLY_HTML, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_path"], "whole_page_diagnostic_only_not_accepted")


class WholePageFallbackNeverAcceptedTests(unittest.TestCase):
    """A page with no JSON-LD and no recognizable product container, but
    where a bare 円-suffixed number does appear somewhere in the page text -
    proves the whole-page diagnostic scan can find something and still not
    have it accepted as the extracted price."""

    HTML = (
        "<html><body>"
        "<div>unrelated promo banner text mentioning  9,999 円  off site-wide</div>"
        "<span>OP01-001</span>"
        "</body></html>"
    )

    def test_diagnostic_candidate_is_rejected_not_accepted(self):
        result = extract_product_from_html(self.HTML, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertNotEqual(result["extracted"]["sell_price_jpy"], 9999)
        self.assertTrue(
            any("whole_page_diagnostic_only_candidate_rejected" in r for r in result["fail_reasons"])
        )


class AmbiguousAndMissingPriceTests(unittest.TestCase):
    def test_ambiguous_main_product_price_fails_closed_with_all_candidates(self):
        html = (
            "<html><body>"
            '<section id="product-detail">'
            '<span class="pote">OP01-001</span>'
            "<h4> 100 円</h4>"
            "<h5> 200 円</h5>"
            "</section>"
            "</body></html>"
        )
        result = extract_product_from_html(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertTrue(any("ambiguous_price" in r for r in result["fail_reasons"]))
        rejected = result["validation"]["rejected_candidates"]
        self.assertEqual(len(rejected), 1)
        candidates = rejected[0]["candidates"]
        self.assertEqual({c["normalized_price"] for c in candidates}, {100, 200})

    def test_missing_price_fails_closed(self):
        html = (
            "<html><body>"
            '<section id="product-detail">'
            '<span class="pote">OP01-001</span>'
            "<p>no price listed here</p>"
            "</section>"
            "</body></html>"
        )
        result = extract_product_from_html(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])

    def test_price_matching_card_code_digits_is_rejected(self):
        # A leaf price element inside a real product container that happens
        # to read "1円" must still be rejected - this is the defense-in-depth
        # digit-collision guard, independent of which tier found the price.
        html = (
            "<html><body>"
            '<section id="product-detail">'
            '<span class="pote">OP01-001</span>'
            "<h4>1円</h4>"
            "</section>"
            "</body></html>"
        )
        result = extract_product_from_html(html, PRODUCT_URL, EXPECTED_CARD_CODE)
        self.assertEqual(result["extraction_status"], "fail_closed")
        self.assertIsNone(result["extracted"]["sell_price_jpy"])
        self.assertTrue(any("price_matches_card_code_or_id_digits" in r for r in result["fail_reasons"]))


class IncrementalResultPersistenceTests(unittest.TestCase):
    def test_append_check_result_writes_one_ndjson_line_per_call(self):
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": tmp}):
                append_check_result("run_a", {"check_number": 1, "http_status": 200})
                append_check_result("run_a", {"check_number": 2, "http_status": 403})

            path = Path(tmp) / "reliability_runs" / "run_a.ndjson"
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["check_number"], 1)
            self.assertEqual(json.loads(lines[1])["http_status"], 403)

    def test_a_partial_run_preserves_every_completed_check(self):
        # Simulates a crash after the 2nd of 3 checks - the 3rd call never
        # happens, but the first two must already be durably on disk.
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": tmp}):
                append_check_result("run_b", {"check_number": 1})
                append_check_result("run_b", {"check_number": 2})
                # (check 3 never runs - simulated crash)

            path = Path(tmp) / "reliability_runs" / "run_b.ndjson"
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(l)["check_number"] for l in lines], [1, 2])

    def test_no_volume_attached_is_a_safe_noop(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAILWAY_VOLUME_MOUNT_PATH", None)
            result = append_check_result("run_c", {"check_number": 1})
        self.assertIsNone(result)


class LogEventTests(unittest.TestCase):
    def test_emits_exactly_one_minified_json_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_event("check_complete", check_number=1, http_status=200)
        output = buf.getvalue()
        lines = output.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn("\n", lines[0])
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["event"], "check_complete")
        self.assertEqual(parsed["check_number"], 1)

    def test_is_not_pretty_printed(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_event("x", a=1, b=2)
        # A pretty-printed (indent=2) dump would contain "  " and newlines
        # between fields - the whole point of this format is that it can't.
        self.assertNotIn("\n", buf.getvalue().rstrip("\n"))


class EgressIpDisclaimerTests(unittest.TestCase):
    def test_disclaimer_does_not_overclaim_certainty(self):
        # The disclaimer text is load-bearing for step-3's "do not claim
        # certainty" rule - guard against it being edited away silently.
        self.assertIn("NOT technically proven", EGRESS_IP_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
