"""Offline, deterministic tests for spike.classify_page. No network, no
browser - synthetic HTML/title/status fixtures only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import classify_page  # noqa: E402


def test_normal_product_page_classifies_normal():
    html = """
    <html><head><title>ロロノア・ゾロ(パラレル) | SNKRDUNK</title></head>
    <body><div class="product-detail"><h1>ロロノア・ゾロ(パラレル)</h1>
    <div class="price">¥1,200</div></div></body></html>
    """
    classification, evidence = classify_page(200, "ロロノア・ゾロ(パラレル) | SNKRDUNK", html)
    assert classification == "normal_page"
    assert evidence == []


def test_static_403_by_status_code():
    html = "<html><head><title>Error</title></head><body>plain body</body></html>"
    classification, evidence = classify_page(403, "Error", html)
    assert classification == "static_403"
    assert "http_status:403" in evidence


def test_static_429_by_status_code():
    html = "<html><head><title>Too Many Requests</title></head><body>slow down</body></html>"
    classification, evidence = classify_page(429, "Too Many Requests", html)
    assert classification == "static_429"
    assert "http_status:429" in evidence


def test_cloudflare_challenge_by_title():
    html = "<html><head><title>Just a moment...</title></head><body></body></html>"
    classification, evidence = classify_page(200, "Just a moment...", html)
    assert classification == "challenge_or_captcha"
    assert any(e.startswith("title:") for e in evidence)


def test_cloudflare_challenge_by_dom_marker():
    html = (
        "<html><head><title>SNKRDUNK</title></head>"
        '<body><div id="challenge-stage">verifying</div></body></html>'
    )
    classification, evidence = classify_page(200, "SNKRDUNK", html)
    assert classification == "challenge_or_captcha"
    assert any(e.startswith("dom_marker:") for e in evidence)


def test_challenge_by_body_phrase_beats_normal_status():
    html = (
        "<html><head><title>SNKRDUNK</title></head>"
        "<body>Please verify you are human before continuing.</body></html>"
    )
    classification, evidence = classify_page(200, "SNKRDUNK", html)
    assert classification == "challenge_or_captcha"
    assert any(e.startswith("body_phrase:") for e in evidence)


def test_bare_cloudflare_mention_on_normal_length_page_is_not_denial():
    # Cloudflare as a CDN name can appear in a normal footer; a bare mention
    # must never alone flip classification when the body is a real page.
    html = "<html><head><title>SNKRDUNK</title></head><body>" + ("x" * 3000) + " served via cloudflare</body></html>"
    classification, evidence = classify_page(200, "SNKRDUNK", html)
    assert classification == "normal_page"


def test_short_body_with_weak_marker_is_flagged_not_normal():
    html = "<html><head><title>SNKRDUNK</title></head><body>captcha</body></html>"
    classification, evidence = classify_page(200, "SNKRDUNK", html)
    assert classification == "error"
    assert any(e.startswith("weak_marker:") for e in evidence)


def test_server_error_status_classifies_error():
    html = "<html><head><title>Server Error</title></head><body>500</body></html>"
    classification, evidence = classify_page(500, "Server Error", html)
    assert classification == "error"
    assert "http_status:500" in evidence
