"""Focused, offline tests for spike.classify_page - no network, no browser.

All fixtures are small, synthetic/reduced HTML files committed under
tests/fixtures/ (resolved relative to this file, not the working directory).
No generated artifact (output/, screenshots, traces, browser profiles, live
captures) is read. A missing fixture fails the specific test that needs it,
with a clear message - it does not crash test collection.

Run with: python3 -m pytest test_classifier.py -v
(or `python3 -m unittest test_classifier` from this directory).
"""

import unittest
from pathlib import Path

from spike import PRODUCT_EXPECTED_MARKERS, classify_page

FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures"


def load_fixture(filename: str) -> str:
    """Read a committed fixture by name. Raises with a clear, actionable
    message (rather than a bare FileNotFoundError) if it's missing, and only
    when a test actually needs it - never at module import."""
    path = FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing committed test fixture: {path}\n"
            "Fixtures must live under tests/fixtures/ and be committed "
            "alongside test_classifier.py - see spikes/yuyutei-browser-"
            "feasibility/tests/fixtures/."
        )
    return path.read_text(encoding="utf-8")


# Small, hand-written synthetic HTML for isolating a single evidence signal
# at a time. Deliberately not fixture files: each is a few lines that exist
# only to exercise one branch of classify_page(), not to represent a page.

# A known denial *title* (from DENIAL_TITLES) with an otherwise unremarkable
# body - no DOM challenge markers, no body denial phrases - isolating the
# title-evidence path on its own.
DENIAL_TITLE_ONLY_HTML = (
    "<html><head><title>Just a moment...</title></head>"
    "<body>Please wait a moment while we verify your request.</body></html>"
)

# A real challenge DOM marker (from CHALLENGE_DOM_MARKERS) with a neutral
# title that matches no DENIAL_TITLES entry - isolating the DOM-marker
# evidence path on its own.
DOM_MARKER_ONLY_HTML = (
    '<html><head><title>Verification</title></head>'
    '<body><div id="challenge-stage">loading...</div></body></html>'
)

# A page that mentions the CDN name but has none of the expected product
# content either - the one case where a bare weak marker should still count
# (only because expected content was requested and is absent).
WEAK_MARKER_NO_CONTENT_HTML = (
    "<html><head><title>Error</title></head>"
    "<body>Something went wrong. Powered by cloudflare.</body></html>"
)


class ClassifyPageTests(unittest.TestCase):
    def test_http_403_always_returns_static_403(self):
        html = load_fixture("static_403.html")
        cls, evidence = classify_page(403, html, "403 Forbidden")
        self.assertEqual(cls, "static_403")
        self.assertIn("http_403", evidence)

    def test_http_429_returns_challenge_or_captcha(self):
        cls, evidence = classify_page(429, "<html></html>", "")
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("http_429", evidence)

    def test_known_denial_title_alone_returns_challenge_or_captcha(self):
        cls, evidence = classify_page(
            200, DENIAL_TITLE_ONLY_HTML, "Just a moment...", PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("denial_title", evidence)
        self.assertFalse(any(e.startswith("challenge_dom_marker:") for e in evidence))

    def test_challenge_dom_marker_alone_returns_challenge_or_captcha(self):
        cls, evidence = classify_page(
            200, DOM_MARKER_ONLY_HTML, "Verification", PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertTrue(any(e.startswith("challenge_dom_marker:") for e in evidence))
        self.assertNotIn("denial_title", evidence)

    def test_cloudflare_word_alone_does_not_trigger_challenge(self):
        # No expected_markers supplied at all -> cannot evaluate "content
        # missing", so a bare CDN-name mention must NOT be treated as a
        # challenge (this is the exact false-positive bug being guarded
        # against).
        html = load_fixture("normal_product_200.html")
        cls, evidence = classify_page(200, html, "irrelevant title")
        self.assertEqual(cls, "normal_product")

    def test_normal_200_product_page_with_expected_markers_is_normal_product(self):
        html = load_fixture("normal_product_200.html")
        title = (
            "P-L ロロノア・ゾロ(パラレル) 販売 | [OP01]ROMANCE DAWN"
        )
        cls, evidence = classify_page(200, html, title, PRODUCT_EXPECTED_MARKERS)
        self.assertEqual(cls, "normal_product")
        # The incidental Cloudflare CDN reference is still recorded as
        # evidence for auditability, but must never by itself flip the
        # classification when expected content is present.
        self.assertTrue(any(e.startswith("weak_marker:") for e in evidence))
        self.assertFalse(any(e.startswith("challenge_dom_marker:") for e in evidence))
        self.assertNotIn("denial_title", evidence)

    def test_weak_marker_with_missing_expected_content_fails_closed(self):
        cls, evidence = classify_page(
            200, WEAK_MARKER_NO_CONTENT_HTML, "Error", PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("weak_marker_with_missing_expected_content", evidence)

    def test_200_page_missing_expected_content_with_strong_denial_evidence_fails_closed(self):
        html = load_fixture("challenge_captcha_200.html")
        cls, evidence = classify_page(
            200, html, "Just a moment...", PRODUCT_EXPECTED_MARKERS
        )
        self.assertEqual(cls, "challenge_or_captcha")
        self.assertIn("denial_title", evidence)
        self.assertTrue(any(e.startswith("challenge_dom_marker:") for e in evidence))
        self.assertIn("expected_content_present=False", evidence)


if __name__ == "__main__":
    unittest.main()
