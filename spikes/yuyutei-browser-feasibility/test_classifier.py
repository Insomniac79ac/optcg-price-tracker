"""Focused, offline tests for spike.classify_page - no network, no browser.

Run with: python3 -m unittest spikes/yuyutei-browser-feasibility/test_classifier.py
(or `python3 -m unittest test_classifier` from this directory).
"""

import unittest
from pathlib import Path

from spike import PRODUCT_EXPECTED_MARKERS, classify_page

# The actual 175-byte static-403 body captured earlier from this same spike
# (spikes/yuyutei-browser-feasibility/output/control_headless/02_product.html).
STATIC_403_HTML = (
    Path(__file__).resolve().parent / "output" / "control_headless" / "02_product.html"
).read_text(encoding="utf-8")
STATIC_403_TITLE = "403"

# Representative normal Yuyu-Tei 200 page: real observed title/content markers
# (from the Railway-loaded run) plus a benign Cloudflare CDN script reference -
# exactly the case that used to false-positive as challenge_or_captcha.
NORMAL_PRODUCT_TITLE = (
    "P-L ロロノア・ゾロ(パラレル) 販売 | [OP01]ROMANCE DAWN | "
    "ONE PIECEカードゲーム通販ならカードショップ -遊々亭-"
)
NORMAL_PRODUCT_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta property="og:title" content="{NORMAL_PRODUCT_TITLE}">
<meta property="og:image" content="https://yuyu-tei.jp/images/op01/10002.jpg">
<title>{NORMAL_PRODUCT_TITLE}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
</head>
<body>
<h1>P-L ロロノア・ゾロ(パラレル)</h1>
<p>OP01-001</p>
<p>販売価格：&yen;500円</p>
<p>在庫あり</p>
</body>
</html>
"""

# Synthetic Cloudflare JS-challenge interstitial ("Just a moment...") - a real
# challenge/CAPTCHA page, served with HTTP 200 (typical for this interstitial).
CHALLENGE_HTML = """<!DOCTYPE html>
<html>
<head><title>Just a moment...</title></head>
<body>
<div id="cf-challenge-running">Checking your browser before accessing yuyu-tei.jp.</div>
<form id="challenge-form" action="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1" method="POST">
<input type="hidden" name="cf_captcha_kind" value="managed">
</form>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
</body>
</html>
"""

# A page that mentions the CDN name but has none of the expected product
# content either - the one case where a bare weak marker should still count.
WEAK_MARKER_NO_CONTENT_HTML = (
    "<html><head><title>Error</title></head>"
    "<body>Something went wrong. Powered by cloudflare.</body></html>"
)


class ClassifyPageTests(unittest.TestCase):
    def test_static_403_body(self):
        cls, evidence = classify_page(403, STATIC_403_HTML, STATIC_403_TITLE)
        self.assertEqual(cls, "static_403")
        self.assertIn("http_403", evidence)

    def test_normal_200_page_with_cloudflare_reference_is_not_a_challenge(self):
        cls, evidence = classify_page(
            200, NORMAL_PRODUCT_HTML, NORMAL_PRODUCT_TITLE, PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "normal_product")
        # The weak marker is still recorded as evidence for auditability, but
        # must never by itself flip the classification.
        self.assertTrue(any(e.startswith("weak_marker:") for e in evidence))
        self.assertFalse(any("challenge" in e for e in evidence if e != "weak_marker:cloudflare"))

    def test_synthetic_challenge_page(self):
        cls, evidence = classify_page(200, CHALLENGE_HTML, "Just a moment...", PRODUCT_EXPECTED_MARKERS)
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("denial_title", evidence)
        self.assertTrue(any(e.startswith("challenge_dom_marker:") for e in evidence))

    def test_weak_marker_alone_is_insufficient(self):
        # No expected_markers supplied at all -> cannot evaluate "content
        # missing", so a bare CDN-name mention must NOT be treated as a
        # challenge (this is the exact bug being fixed).
        cls, evidence = classify_page(200, NORMAL_PRODUCT_HTML, NORMAL_PRODUCT_TITLE)
        self.assertEqual(cls, "normal_product")

    def test_weak_marker_with_missing_expected_content_is_a_challenge(self):
        cls, evidence = classify_page(
            200, WEAK_MARKER_NO_CONTENT_HTML, "Error", PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("weak_marker_with_missing_expected_content", evidence)

    def test_http_429_is_strong_evidence(self):
        cls, evidence = classify_page(429, "<html></html>", "")
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("http_429", evidence)


if __name__ == "__main__":
    unittest.main()
