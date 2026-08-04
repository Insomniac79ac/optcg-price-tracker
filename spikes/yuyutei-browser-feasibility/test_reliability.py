"""Focused, offline tests for the new static-IP reliability aggregation and
scoped-extraction helpers - no network, no browser, no Playwright Page.

Run with: python3 -m pytest test_reliability.py -v
"""

import unittest

from spike import EGRESS_IP_DISCLAIMER, _extract_fields_from_text, summarize_checks_by_egress_ip


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


class ExtractFieldsFromTextTests(unittest.TestCase):
    def test_extracts_all_fields_from_well_formed_text(self):
        text = "P-L ロロノア・ゾロ(パラレル)\nOP01-001\n販売価格：￥500円\n在庫あり"
        fields = _extract_fields_from_text(text)
        self.assertEqual(fields["card_code"], "OP01-001")
        self.assertEqual(fields["treatment"], "parallel")
        self.assertEqual(fields["sell_price_jpy"], 500)
        self.assertEqual(fields["stock_status"], "in_stock")

    def test_missing_price_is_none_not_zero(self):
        fields = _extract_fields_from_text("OP01-001 パラレル 在庫あり")
        self.assertIsNone(fields["sell_price_jpy"])

    def test_out_of_stock_marker(self):
        fields = _extract_fields_from_text("販売価格：￥500円\n在庫切れ")
        self.assertEqual(fields["stock_status"], "out_of_stock")

    def test_unrelated_text_yields_all_none(self):
        fields = _extract_fields_from_text("this page has nothing to do with any card")
        self.assertIsNone(fields["card_code"])
        self.assertIsNone(fields["treatment"])
        self.assertIsNone(fields["sell_price_jpy"])
        self.assertIsNone(fields["stock_status"])


class EgressIpDisclaimerTests(unittest.TestCase):
    def test_disclaimer_does_not_overclaim_certainty(self):
        # The disclaimer text is load-bearing for step-3's "do not claim
        # certainty" rule - guard against it being edited away silently.
        self.assertIn("NOT technically proven", EGRESS_IP_DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
