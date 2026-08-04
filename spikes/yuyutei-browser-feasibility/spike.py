"""Standalone feasibility spike: can a real Playwright browser session load
and read Yuyu-Tei One Piece card pages that return HTTP 403 to curl/WebFetch,
and if so, is the 403 explained by browser engine, channel, or context
configuration?

Isolated from the application - no imports from services/*, no database
writes, no deployment. Deterministic extraction only (regex/DOM selectors),
no AI model calls.

Rules honored: no proxy rotation, no CAPTCHA-solving service, no fingerprint
spoofing beyond supported Playwright context options, no attempt to bypass a
rendered challenge/denial page (only records what rendered), no manually set
Sec-Fetch/browser-controlled headers, one normal navigation attempt per URL
per mode.
"""

import argparse
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

HOMEPAGE_URL = "https://yuyu-tei.jp/"
CATEGORY_URL = "https://yuyu-tei.jp/sell/opc/s/op01"
PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"  # P-L Roronoa Zoro (parallel), OP01-001

# A coherent, internally-consistent desktop Chrome UA. Kept in sync with the
# branded Chrome channel version actually installed in this environment
# (`google-chrome --version`) so the UA string is not a lie about itself.
DESKTOP_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
DESKTOP_ACCEPT_LANGUAGE = "ja-JP,ja;q=0.9,en;q=0.8"
DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}
DESKTOP_SCREEN = {"width": 1920, "height": 1080}

# Strong evidence: a known denial/challenge *title*. Titles are short and
# purpose-built by the challenge page itself, so a match here is reliable on
# its own (unlike a body substring, which can appear incidentally in normal
# markup/asset URLs).
DENIAL_TITLES = [
    "403",
    "403 forbidden",
    "access denied",
    "just a moment...",
    "just a moment",
    "attention required! | cloudflare",
    "please wait...",
    "please stand by",
]

# Strong evidence: specific challenge-page body phrasing (not a single
# vendor-name word) or a real CAPTCHA/challenge widget in the DOM.
DENIAL_BODY_PHRASES = [
    "checking your browser before accessing",
    "please stand by, while we are checking your browser",
    "verify you are human",
    "enable javascript and cookies to continue",
    "を拒否されました",  # "access was denied" (ja)
    "アクセスが拒否",
]

CHALLENGE_DOM_MARKERS = [
    "cf-challenge-running",
    "cf_challenge",
    "challenges.cloudflare.com",
    "g-recaptcha",
    "cf-turnstile",
    'id="challenge-form"',
    'id="challenge-stage"',
]

# Weak evidence only - a bare mention of the CDN/vendor name, error-code
# string, etc. These are common in normal pages (Cloudflare is Yuyu-Tei's
# CDN) and must NEVER classify a page as challenge_or_captcha by themselves.
# They only count when the expected product content is also missing.
WEAK_MARKERS = [
    "cloudflare",
    "captcha",
    "cf-error",
    "ray id",
]

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"
PROFILE_ROOT = Path(__file__).resolve().parent / ".chrome-profile"  # gitignored

# A single public, no-auth, no-credential IP/geo lookup - not an application
# secret, not a proxy. Used only to record which network the test ran from.
EGRESS_IP_LOOKUP_URL = "https://ipinfo.io/json"

# Optional single fixed/sticky outbound proxy endpoint. No rotation - the
# same endpoint (if any) is used for every request in a run. Unset by
# default: no provider is selected or purchased by this spike, and no
# request goes through a proxy unless these are explicitly set. Values come
# from the environment only - never hardcoded, never committed, never
# printed (only whether a proxy is configured is logged).
YUYUTEI_PROXY_SERVER = "YUYUTEI_PROXY_SERVER"
YUYUTEI_PROXY_USERNAME = "YUYUTEI_PROXY_USERNAME"
YUYUTEI_PROXY_PASSWORD = "YUYUTEI_PROXY_PASSWORD"


def get_proxy_config() -> dict | None:
    """Playwright `proxy` dict built from env vars, or None if unset. A
    fixed/sticky single endpoint only - no rotation, no default provider."""
    server = os.environ.get(YUYUTEI_PROXY_SERVER)
    if not server:
        return None
    proxy: dict = {"server": server}
    username = os.environ.get(YUYUTEI_PROXY_USERNAME)
    password = os.environ.get(YUYUTEI_PROXY_PASSWORD)
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy


def capture_egress_ip() -> dict:
    """Best-effort outbound public IP/country lookup via a public service (no
    credentials involved). Failures are recorded, not raised - this is
    diagnostic context for the test, not something the test depends on."""
    try:
        req = urllib.request.Request(
            EGRESS_IP_LOOKUP_URL, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "source": EGRESS_IP_LOOKUP_URL,
            "ip": data.get("ip"),
            "country": data.get("country"),
            "region": data.get("region"),
            "city": data.get("city"),
            "org": data.get("org"),
            "error": None,
        }
    except Exception as exc:
        return {
            "source": EGRESS_IP_LOOKUP_URL,
            "ip": None,
            "country": None,
            "region": None,
            "city": None,
            "org": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def classify_page(
    status: int | None,
    html: str,
    title: str,
    expected_markers: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Evidence-based classification. A bare mention of "cloudflare" (or any
    other weak marker) is never sufficient on its own - Cloudflare is
    Yuyu-Tei's CDN, so that string legitimately appears on normal 200 pages.
    Returns (classification, evidence) where evidence lists exactly what was
    found, so a human can audit the call.
    """
    evidence: list[str] = []
    html_bytes = len(html.encode("utf-8"))
    title_lower = title.lower()
    haystack = f"{title}\n{html}".lower()

    if status == 403:
        evidence.append("http_403")
        return "static_403", evidence
    if status == 429:
        evidence.append("http_429")
        return "challenge_or_captcha", evidence

    denial_title_hit = any(t in title_lower for t in DENIAL_TITLES)
    if denial_title_hit:
        evidence.append("denial_title")

    body_phrase_hits = [p for p in DENIAL_BODY_PHRASES if p in haystack]
    if body_phrase_hits:
        evidence.append("denial_body_phrase:" + ",".join(body_phrase_hits))

    dom_marker_hits = [m for m in CHALLENGE_DOM_MARKERS if m in haystack]
    if dom_marker_hits:
        evidence.append("challenge_dom_marker:" + ",".join(dom_marker_hits))

    weak_marker_hits = [m for m in WEAK_MARKERS if m in haystack]
    if weak_marker_hits:
        evidence.append("weak_marker:" + ",".join(weak_marker_hits))

    expected_present = None
    if expected_markers:
        expected_present = any(m.lower() in haystack for m in expected_markers)
        evidence.append(f"expected_content_present={expected_present}")

    strong_evidence = denial_title_hit or bool(body_phrase_hits) or bool(dom_marker_hits)
    weak_evidence_with_missing_content = (
        bool(weak_marker_hits) and expected_present is False
    )

    if strong_evidence or weak_evidence_with_missing_content:
        if weak_evidence_with_missing_content and not strong_evidence:
            evidence.append("weak_marker_with_missing_expected_content")
        return "challenge_or_captcha", evidence

    if status == 200 and html_bytes > 500:
        return "normal_product", evidence
    if status is None:
        return "navigation_error", evidence
    return f"other_status_{status}", evidence


SELECTOR_VERSION = "v3"  # v3: structured JSON-LD Product data first, then
# product-scoped DOM element selectors confined to the real main-product
# container, then a text parser still confined to that same container -
# whole-page regex is kept only as a diagnostic that can never be accepted
# as the extracted price. See PRICE_EXTRACTION_NOTE.
EXPECTED_CARD_CODE = "OP01-001"
PRODUCT_EXPECTED_MARKERS = ["ロロノア・ゾロ", "パラレル"]
CATEGORY_EXPECTED_MARKERS = ["ROMANCE DAWN"]
HOMEPAGE_EXPECTED_MARKERS = ["遊々亭"]

# What a per-check diagnostic_egress_ip field does and does not prove -
# reused verbatim in reliability-run output so it travels with the data.
EGRESS_IP_DISCLAIMER = (
    "diagnostic_egress_ip is the IP observed by a separate outbound HTTPS "
    "lookup (ipinfo.io) made from the same process around the same time as "
    "the page request. It is NOT technically proven to be the exact IP that "
    "served the Yuyu-Tei request for this check."
)

# v2 anchored price extraction on the literal word 販売 ("for sale") appearing
# near the price. On a real captured OP01-001 page, that word appears exactly
# once - inside a decorative, position-absolute SEO breadcrumb heading
# ("...(パラレル) | 販売 | [OP01]ROMANCE DAWN...") that has nothing to do with
# the price element. The v2 regex, run over the whole page, matched 販売 in
# that breadcrumb and then captured the first digits within 20 characters of
# it: "OP01" -> "01" -> int("01") == 1. The real price ("34,800円") sits in a
# plain, unlabelled element inside the actual product-detail container, which
# contains no occurrence of 販売 at all. v3 never anchors on that word.
PRICE_EXTRACTION_NOTE = (
    "v3 does not anchor price extraction on the word 販売 - see the OP01 -> "
    "1 JPY bug this replaced."
)


def _meta_content(page: Page, prop: str) -> str | None:
    el = page.query_selector(f'meta[property="{prop}"]') or page.query_selector(f'meta[name="{prop}"]')
    return el.get_attribute("content") if el else None


def _external_product_id(url: str) -> str | None:
    """Derived from the stable product URL path (.../card/<series>/<id>), not
    the displayed card code - this is Yuyu-Tei's own internal product id, a
    separate identifier from the printed card number."""
    m = re.search(r"/card/([a-z0-9]+)/(\d+)", url, re.IGNORECASE)
    return f"{m.group(1)}-{m.group(2)}".lower() if m else None


CARD_CODE_RE = re.compile(r"\bOP\d{2}-\d{3}\b")
PRICE_LEAF_RE = re.compile(r"^[¥￥]?\s*([\d,]+)\s*円$")
PRICE_ANYWHERE_RE = re.compile(r"[¥￥]?[\d,]+\s*円")
MAIN_CONTAINER_KEYWORD_RE = re.compile(r"product|detail|item|goods", re.IGNORECASE)


def _normalize_price_text(raw: str) -> int | None:
    """'34,800 円' / '¥34,800' -> 34800. None if no digits are present."""
    m = re.search(r"[\d,]+", raw)
    if not m:
        return None
    digits = m.group(0).replace(",", "")
    return int(digits) if digits else None


def _price_matches_code_digits(price: int, *codes: str | None) -> bool:
    """True if `price` numerically equals a digit-group found inside a card
    code or external product id, e.g. "OP01-001" contains digit-groups
    {1 (from "01"), 1 (from "001")}. This is exactly the shape of the OP01 ->
    1 JPY bug, kept as a standing guard regardless of which extraction tier
    produced the price."""
    for code in codes:
        if not code:
            continue
        for group in re.findall(r"\d+", code):
            if int(group) == price:
                return True
    return False


def _describe_element(el) -> str:
    tag = el.name
    el_id = el.get("id")
    classes = el.get("class") or []
    if el_id:
        return f"{tag}#{el_id}"
    if classes:
        return f"{tag}.{'.'.join(classes)}"
    return tag


def _find_jsonld_product(soup: BeautifulSoup) -> dict | None:
    """First schema.org Product block found in a
    <script type="application/ld+json"> tag, if any - page-author-supplied
    structured data, priority 1 for extraction."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return None


def _fields_from_jsonld(product: dict) -> dict | None:
    """Returns a complete fields dict only when name/price/currency/card_code
    are all present and self-consistent; otherwise None so extraction falls
    through to DOM selectors rather than accepting a partial record."""
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    offers = offers or {}

    name = product.get("name")
    price = _normalize_price_text(str(offers.get("price", "")))
    currency = offers.get("priceCurrency")
    availability = str(offers.get("availability") or "")
    description = str(product.get("description") or "")

    card_code_match = CARD_CODE_RE.search(description) or CARD_CODE_RE.search(name or "")
    card_code = card_code_match.group(0) if card_code_match else None

    if not (name and price is not None and currency == "JPY" and card_code):
        return None

    availability_lower = availability.lower()
    if "outofstock" in availability_lower:
        stock_status = "out_of_stock"
    elif "instock" in availability_lower:
        stock_status = "in_stock"
    elif availability:
        stock_status = "unknown_present_marker"
    else:
        stock_status = None

    if "パラレル" in name:
        treatment = "parallel"
    elif "ノーマル" in name:
        treatment = "normal"
    else:
        treatment = None

    return {
        "product_title": name,
        "card_code": card_code,
        "treatment": treatment,
        "sell_price_jpy": price,
        "stock_status": stock_status,
        "product_image_url": product.get("image") or None,
        "price_evidence": {
            "accepted_selector": "script[type=application/ld+json] Product.offers.price",
            "raw_price_text": str(offers.get("price")),
            "normalized_price": price,
            "surrounding_label_text": f"priceCurrency={currency}",
            "extraction_method": "jsonld_structured_data",
            "rejected_candidates": [],
        },
    }


def _find_main_detail_container(soup: BeautifulSoup):
    """Smallest element that both (a) has an id/class hinting
    product/detail/item/goods AND (b) actually contains a card-code-shaped
    string and a 円-suffixed price - not just any element with a matching
    class name. On a real captured OP01-001 page this resolves to
    <div class="product-detailing"> inside <section id="product-detail">,
    correctly excluding the surrounding image column and the recommendation
    grid further down the page (neither is inside this container at all)."""
    best = None
    best_len = None
    for el in soup.find_all(True):
        idclass = f"{el.get('id') or ''} {' '.join(el.get('class') or [])}"
        if not MAIN_CONTAINER_KEYWORD_RE.search(idclass):
            continue
        text = el.get_text(" ", strip=True)
        if not (CARD_CODE_RE.search(text) and PRICE_ANYWHERE_RE.search(text)):
            continue
        if best is None or len(text) < best_len:
            best = el
            best_len = len(text)
    return best


def _find_title_container(soup: BeautifulSoup):
    """The single on-page product-title heading (`#power h3` on a real
    captured page) - deliberately NOT the decorative, position-absolute
    breadcrumb h1 elsewhere on the page (mixes in unrelated breadcrumb
    segments, e.g. "... | 販売 | [OP01]...", and isn't scoped to this
    product), and not a recommendation tile's <p> title."""
    power = soup.find(id="power") or soup.find(class_="power")
    if power:
        heading = power.find(["h2", "h3"])
        if heading and heading.get_text(strip=True):
            return heading
    return None


def _leaf_price_candidates(container) -> list[dict]:
    """Every leaf (no element children) descendant of `container` whose own
    text is *only* a 円-suffixed price - not the container's full flattened
    text. Recommendation-tile and breadcrumb prices are excluded structurally
    (they simply aren't inside `container`), not by keyword guessing."""
    candidates = []
    for el in container.find_all(True):
        if el.find(True) is not None:
            continue  # has element children - not a leaf
        text = el.get_text(strip=True)
        m = PRICE_LEAF_RE.match(text)
        if not m:
            continue
        normalized = _normalize_price_text(m.group(1))
        if normalized is None:
            continue
        candidates.append({
            "selector": _describe_element(el),
            "raw_text": text,
            "normalized_price": normalized,
        })
    return candidates


def _find_card_code_element(container) -> dict | None:
    for el in container.find_all(True):
        if el.find(True) is not None:
            continue
        text = el.get_text(strip=True)
        if CARD_CODE_RE.fullmatch(text):
            return {"selector": _describe_element(el), "text": text}
    return None


def _find_stock_element(container) -> dict | None:
    for el in container.find_all(True):
        if el.find(True) is not None:
            continue
        text = el.get_text(strip=True)
        if "在庫" not in text:
            continue
        if "在庫あり" in text:
            status = "in_stock"
        elif "在庫切れ" in text or "品切れ" in text:
            status = "out_of_stock"
        elif "×" in text:
            status = "out_of_stock"
        elif "○" in text or "◯" in text:
            status = "in_stock"
        else:
            status = "unknown_present_marker"
        return {"selector": _describe_element(el), "text": text, "stock_status": status}
    return None


def _dom_scoped_fields(soup: BeautifulSoup) -> tuple[dict | None, dict]:
    """Priority 2/3: product-scoped DOM element selectors, then (only if
    that finds no leaf-level price element) a text-regex scan still confined
    to the same container. Never looks outside the main detail container.
    Returns (fields_or_None, diagnostics) - diagnostics always records what
    was tried, including rejection reasons, for audit."""
    diagnostics: dict = {"main_container": None, "price_candidates": [], "rejected": []}

    container = _find_main_detail_container(soup)
    if container is None:
        diagnostics["rejected"].append({"reason": "no_product_container_found"})
        return None, diagnostics

    diagnostics["main_container"] = _describe_element(container)

    title_el = _find_title_container(soup)
    product_title = title_el.get_text(strip=True) if title_el else None

    card_code_el = _find_card_code_element(container)
    card_code = card_code_el["text"] if card_code_el else None

    stock_el = _find_stock_element(container)
    stock_status = stock_el["stock_status"] if stock_el else None

    title_text_for_treatment = product_title or ""
    if "パラレル" in title_text_for_treatment:
        treatment = "parallel"
    elif "ノーマル" in title_text_for_treatment:
        treatment = "normal"
    else:
        treatment = None

    price_candidates = _leaf_price_candidates(container)
    extraction_method = "dom_selector_scoped"

    if not price_candidates:
        # Priority 3: tightly scoped text parser - still confined to this
        # same container, still requires the 円 marker, but doesn't need a
        # single leaf element to hold only the price. Never looks outside
        # `container`, so it still can't see the breadcrumb or recommendations.
        container_text = container.get_text(" ", strip=True)
        m = PRICE_ANYWHERE_RE.search(container_text)
        if m:
            normalized = _normalize_price_text(m.group(0))
            if normalized is not None:
                price_candidates = [{
                    "selector": f"{_describe_element(container)} (container text scan)",
                    "raw_text": m.group(0),
                    "normalized_price": normalized,
                }]
                extraction_method = "container_text_scoped_fallback"

    diagnostics["price_candidates"] = price_candidates

    if not price_candidates:
        diagnostics["rejected"].append({"reason": "price_missing_in_container"})
        return None, diagnostics

    distinct_prices = {c["normalized_price"] for c in price_candidates}
    if len(distinct_prices) > 1:
        diagnostics["rejected"].append({
            "reason": "ambiguous_price_multiple_candidates",
            "candidates": price_candidates,
        })
        return None, diagnostics

    accepted = price_candidates[0]
    diagnostics["accepted_price_candidate"] = accepted

    fields = {
        "product_title": product_title,
        "card_code": card_code,
        "treatment": treatment,
        "sell_price_jpy": accepted["normalized_price"],
        "stock_status": stock_status,
        "product_image_url": None,
        "price_evidence": {
            "accepted_selector": accepted["selector"],
            "raw_price_text": accepted["raw_text"],
            "normalized_price": accepted["normalized_price"],
            "surrounding_label_text": (stock_el or {}).get("text"),
            "extraction_method": extraction_method,
            "rejected_candidates": [c for c in price_candidates if c is not accepted],
        },
    }
    return fields, diagnostics


def _whole_page_diagnostic_price(html: str) -> dict | None:
    """Priority 4: diagnostic-only whole-page scan, kept only so a run still
    logs *something* when neither JSON-LD nor a product container can be
    found. Structurally cannot become the accepted price - see
    extract_product_from_html, which never promotes this result. Not
    anchored on 販売 (see PRICE_EXTRACTION_NOTE)."""
    m = PRICE_ANYWHERE_RE.search(html)
    if not m:
        return None
    return {"raw_text": m.group(0), "normalized_price": _normalize_price_text(m.group(0))}


def extract_product_from_html(html: str, source_url: str, requested_card_code: str = EXPECTED_CARD_CODE) -> dict:
    """Pure, offline-testable extraction core - no Page, no I/O, no network.
    Priority: 1) structured JSON-LD Product data, 2) product-scoped DOM
    element selectors, 3) a text parser confined to that same container,
    4) a whole-page regex kept diagnostic-only and never eligible to be
    accepted as the extracted price."""
    soup = BeautifulSoup(html, "html.parser")

    jsonld_product = _find_jsonld_product(soup)
    jsonld_fields = _fields_from_jsonld(jsonld_product) if jsonld_product else None

    dom_fields = None
    dom_diagnostics: dict = {}
    if jsonld_fields is None:
        dom_fields, dom_diagnostics = _dom_scoped_fields(soup)

    diagnostic_fallback = _whole_page_diagnostic_price(html)

    if jsonld_fields is not None:
        fields = jsonld_fields
        extraction_path = "jsonld_structured_data"
    elif dom_fields is not None:
        fields = dom_fields
        extraction_path = dom_fields["price_evidence"]["extraction_method"]
    else:
        fields = None
        extraction_path = "whole_page_diagnostic_only_not_accepted"

    fail_reasons: list[str] = []

    if fields is None:
        rejected_reasons = [r.get("reason") for r in (dom_diagnostics.get("rejected") or [])]
        fail_reasons.extend(rejected_reasons or ["no_trustworthy_price_source_found"])
        if diagnostic_fallback:
            fail_reasons.append(
                f"whole_page_diagnostic_only_candidate_rejected:{diagnostic_fallback['raw_text']}"
            )
        product_title = None
        card_code = None
        treatment = None
        sell_price_jpy = None
        stock_status = None
        image_url = None
        price_evidence = None
    else:
        product_title = fields["product_title"]
        card_code = fields["card_code"]
        treatment = fields["treatment"]
        sell_price_jpy = fields["sell_price_jpy"]
        stock_status = fields["stock_status"]
        image_url = fields.get("product_image_url")
        price_evidence = fields["price_evidence"]

        external_id = _external_product_id(source_url)
        if sell_price_jpy is not None and _price_matches_code_digits(sell_price_jpy, card_code, external_id):
            fail_reasons.append(f"price_matches_card_code_or_id_digits:{sell_price_jpy}")
            sell_price_jpy = None
        elif sell_price_jpy is not None and sell_price_jpy < 10:
            fail_reasons.append(f"implausible_price_too_low:{sell_price_jpy}")
            sell_price_jpy = None

    if not product_title:
        fail_reasons.append("product_title_missing")
    if sell_price_jpy is None and "sell_price_missing_or_not_numeric" not in fail_reasons:
        fail_reasons.append("sell_price_missing_or_not_numeric")
    if card_code is not None and card_code != requested_card_code:
        fail_reasons.append(f"card_code_conflict:displayed={card_code},expected={requested_card_code}")
    if treatment is not None and treatment != "parallel":
        fail_reasons.append(f"treatment_conflict:displayed={treatment},expected=parallel")

    extracted = {
        "source_url": source_url,
        "final_url": source_url,
        "product_title": product_title,
        "card_code": card_code,
        "treatment": treatment,
        "sell_price_jpy": sell_price_jpy,
        "stock_status": stock_status,
        "product_image_url": image_url,
        "external_product_id": _external_product_id(source_url),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    validation = {
        "title_present": product_title is not None,
        "price_numeric": sell_price_jpy is not None,
        "card_code_matches_expected": card_code is None or card_code == requested_card_code,
        "treatment_matches_expected": treatment is None or treatment == "parallel",
        "accepted_selector": (price_evidence or {}).get("accepted_selector"),
        "raw_price_text": (price_evidence or {}).get("raw_price_text"),
        "normalized_price": (price_evidence or {}).get("normalized_price"),
        "surrounding_label_text": (price_evidence or {}).get("surrounding_label_text"),
        "extraction_method": (price_evidence or {}).get("extraction_method"),
        "rejected_candidates": (
            (price_evidence or {}).get("rejected_candidates")
            or dom_diagnostics.get("rejected")
            or []
        ),
    }

    return {
        "extraction_status": "extracted" if not fail_reasons else "fail_closed",
        "fail_reasons": fail_reasons,
        "selector_version": SELECTOR_VERSION,
        "extraction_path": extraction_path,
        "selector_diagnostics": dom_diagnostics or None,
        "extracted": extracted,
        "validation": validation,
    }


def extract_and_validate_product(page: Page, source_url: str, requested_card_code: str = EXPECTED_CARD_CODE) -> dict:
    """Thin Playwright wrapper around extract_product_from_html - all real
    extraction logic is pure/offline-testable (see extract_product_from_html
    and test_reliability.py). Only final_url and a page.title() fallback come
    from the live Page (final_url isn't present in the HTML itself)."""
    html = page.content()
    result = extract_product_from_html(html, source_url, requested_card_code)
    result["extracted"]["final_url"] = page.url
    if result["extracted"]["product_title"] is None:
        fallback_title = page.title() or None
        result["extracted"]["product_title"] = fallback_title
        result["validation"]["title_present"] = fallback_title is not None
    return result


def dump_dom_candidates(page: Page, limit: int = 40) -> list[dict]:
    """Diagnostic-only DOM inspection: leaf elements whose text matches a
    price/stock/treatment/card-code pattern, with tag/id/class - enough to
    identify stable selectors on the real rendered page without dumping the
    full HTML. Never used for extraction itself, only logged for review."""
    js = r"""
    () => {
      const patterns = {
        price: /[¥￥][\d,]+|[\d,]+\s*円/,
        stock: /在庫/,
        treatment: /パラレル|ノーマル/,
        cardCode: /OP\d{2}-\d{3}/,
      };
      const results = [];
      const all = document.querySelectorAll('body *');
      for (const el of all) {
        if (el.children.length > 0) continue;
        const text = (el.textContent || '').trim();
        if (!text || text.length > 120) continue;
        for (const [key, re] of Object.entries(patterns)) {
          if (re.test(text)) {
            results.push({
              match: key,
              tag: el.tagName.toLowerCase(),
              id: el.id || null,
              class: el.className || null,
              text: text.slice(0, 100),
            });
            break;
          }
        }
      }
      return results;
    }
    """
    try:
        candidates = page.evaluate(js)
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    return candidates[:limit]


def capture(page: Page, response, out_prefix: Path, elapsed_s: float, expected_markers: list[str] | None = None) -> dict:
    title = page.title()
    html = page.content()
    out_prefix.with_suffix(".html").write_text(html, encoding="utf-8")
    try:
        page.screenshot(path=str(out_prefix.with_suffix(".png")), full_page=True)
    except Exception:
        pass  # some engines can fail full_page screenshot on denial pages; html/status still captured

    status = response.status if response else None
    html_bytes = len(html.encode("utf-8"))
    cls, evidence = classify_page(status, html, title, expected_markers)

    try:
        reported_ua = page.evaluate("() => navigator.userAgent")
    except Exception:
        reported_ua = None

    return {
        "final_url": page.url,
        "http_status": status,
        "navigation_ok": bool(response and response.ok),
        "page_title": title,
        "navigator_user_agent": reported_ua,
        "classification": cls,
        "classification_evidence": evidence,
        "html_bytes": html_bytes,
        "elapsed_s": round(elapsed_s, 3),
    }


def goto_and_capture(
    page: Page, url: str, out_prefix: Path, expected_markers: list[str] | None = None
) -> dict:
    start = time.monotonic()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        elapsed = time.monotonic() - start
        return capture(page, resp, out_prefix, elapsed, expected_markers)
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 3)}


@dataclass
class ModeSpec:
    name: str
    description: str
    headless: bool
    engine: str  # "chromium" | "firefox" | "webkit"
    channel: str | None = None
    context_kwargs: dict = field(default_factory=dict)
    persistent: bool = False
    visit_homepage_first: bool = False
    capture_egress_ip: bool = False


MODES: dict[str, ModeSpec] = {
    "control_headless": ModeSpec(
        name="control_headless",
        description="Bundled Chromium, default context (control)",
        headless=True,
        engine="chromium",
    ),
    "control_headed": ModeSpec(
        name="control_headed",
        description="Bundled Chromium, default context (control)",
        headless=False,
        engine="chromium",
    ),
    "desktop_context_headless": ModeSpec(
        name="desktop_context_headless",
        description="Bundled Chromium, coherent desktop context",
        headless=True,
        engine="chromium",
        context_kwargs={
            "user_agent": DESKTOP_CHROME_UA,
            "locale": "ja-JP",
            "extra_http_headers": {"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
            "viewport": DESKTOP_VIEWPORT,
            "screen": DESKTOP_SCREEN,
            "java_script_enabled": True,
        },
    ),
    "desktop_context_headed": ModeSpec(
        name="desktop_context_headed",
        description="Bundled Chromium, coherent desktop context",
        headless=False,
        engine="chromium",
        context_kwargs={
            "user_agent": DESKTOP_CHROME_UA,
            "locale": "ja-JP",
            "extra_http_headers": {"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
            "viewport": DESKTOP_VIEWPORT,
            "screen": DESKTOP_SCREEN,
            "java_script_enabled": True,
        },
    ),
    "chrome_channel_headed": ModeSpec(
        name="chrome_channel_headed",
        description="Branded Google Chrome channel, default context",
        headless=False,
        engine="chromium",
        channel="chrome",
    ),
    "chrome_channel_headless": ModeSpec(
        name="chrome_channel_headless",
        description="Branded Google Chrome channel, default context",
        headless=True,
        engine="chromium",
        channel="chrome",
    ),
    "firefox_headed": ModeSpec(
        name="firefox_headed",
        description="Playwright Firefox, default context",
        headless=False,
        engine="firefox",
    ),
    "firefox_headless": ModeSpec(
        name="firefox_headless",
        description="Playwright Firefox, default context",
        headless=True,
        engine="firefox",
    ),
    "webkit_headed": ModeSpec(
        name="webkit_headed",
        description="Playwright WebKit, default context",
        headless=False,
        engine="webkit",
    ),
    "webkit_headless": ModeSpec(
        name="webkit_headless",
        description="Playwright WebKit, default context",
        headless=True,
        engine="webkit",
    ),
    "persistent_chrome": ModeSpec(
        name="persistent_chrome",
        description="Persistent branded-Chrome context, dedicated ignored profile dir",
        headless=False,
        engine="chromium",
        channel="chrome",
        persistent=True,
        visit_homepage_first=True,
    ),
    "railway_headless": ModeSpec(
        name="railway_headless",
        description=(
            "Bundled Chromium, default context, headless - one-shot run from a "
            "Railway service's server-side network (no display available there)"
        ),
        headless=True,
        engine="chromium",
        visit_homepage_first=True,
        capture_egress_ip=True,
    ),
}


def get_browser_type(p, engine: str):
    return {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}[engine]


def run(mode_name: str) -> dict:
    spec = MODES[mode_name]
    out_dir = OUTPUT_ROOT / spec.name
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.zip"

    result: dict = {
        "mode": spec.name,
        "description": spec.description,
        "headless": spec.headless,
        "engine": spec.engine,
        "channel": spec.channel,
        "context_kwargs": {k: v for k, v in spec.context_kwargs.items()},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "playwright_version": None,
        "browser_version": None,
        "egress": None,
        "steps": {},
        "extracted_product": None,
    }

    if spec.capture_egress_ip:
        result["egress"] = capture_egress_ip()

    with sync_playwright() as p:
        result["playwright_version"] = pkg_version("playwright")
        browser_type = get_browser_type(p, spec.engine)

        launch_kwargs: dict = {"headless": spec.headless}
        if spec.channel:
            launch_kwargs["channel"] = spec.channel
        proxy = get_proxy_config()
        if proxy:
            launch_kwargs["proxy"] = proxy

        browser: Browser | None = None
        context: BrowserContext

        if spec.persistent:
            profile_dir = PROFILE_ROOT / spec.name
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = browser_type.launch_persistent_context(
                str(profile_dir), **launch_kwargs, **spec.context_kwargs
            )
            result["browser_version"] = context.browser.version if context.browser else None
        else:
            browser = browser_type.launch(**launch_kwargs)
            context = browser.new_context(**spec.context_kwargs)
            result["browser_version"] = browser.version

        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        if spec.visit_homepage_first:
            result["steps"]["homepage"] = goto_and_capture(
                page, HOMEPAGE_URL, out_dir / "00_homepage", HOMEPAGE_EXPECTED_MARKERS
            )

        result["steps"]["category_page"] = goto_and_capture(
            page, CATEGORY_URL, out_dir / "01_category", CATEGORY_EXPECTED_MARKERS
        )

        product_step = goto_and_capture(
            page, PRODUCT_URL, out_dir / "02_product", PRODUCT_EXPECTED_MARKERS
        )
        result["steps"]["product_page"] = product_step
        if product_step.get("classification") == "normal_product":
            try:
                result["extracted_product"] = extract_and_validate_product(page, PRODUCT_URL)
            except Exception as exc:
                result["extracted_product"] = {"error": f"{type(exc).__name__}: {exc}"}

        context.tracing.stop(path=str(trace_path))
        context.close()
        if browser:
            browser.close()

    result["trace_path"] = str(trace_path)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def run_extraction(repeat: int = 3, delay_s: float = 8.0, dump_dom: bool = False) -> dict:
    """Repeated, validated, fail-closed extraction of the OP01-001 Zoro
    parallel product page only (no homepage/category detour - conservative
    request volume). Bundled headless Chromium, default context, no proxy/
    stealth/fingerprint tricks. Persists only the LATEST run's HTML/
    screenshot/trace - to OUTPUT_ROOT always, and additionally to a mounted
    Railway volume (RAILWAY_VOLUME_MOUNT_PATH) if one is attached."""
    out_dir = OUTPUT_ROOT / "railway_extract"
    out_dir.mkdir(parents=True, exist_ok=True)

    volume_root = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    volume_dir = Path(volume_root) / "yuyutei_extract_latest" if volume_root else None
    if volume_dir:
        volume_dir.mkdir(parents=True, exist_ok=True)

    overall: dict = {
        "spike": "yuyutei_op01_001_extraction",
        "source_url": PRODUCT_URL,
        "requested_card_code": EXPECTED_CARD_CODE,
        "selector_version": SELECTOR_VERSION,
        "repeat": repeat,
        "delay_s": delay_s,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "playwright_version": None,
        "browser_version": None,
        "runs": [],
    }

    proxy = get_proxy_config()
    overall["proxy_configured"] = proxy is not None

    with sync_playwright() as p:
        overall["playwright_version"] = pkg_version("playwright")
        launch_kwargs: dict = {"headless": True}
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = p.chromium.launch(**launch_kwargs)
        overall["browser_version"] = browser.version
        context = browser.new_context()

        for i in range(1, repeat + 1):
            egress = capture_egress_ip()
            out_prefix = out_dir / f"run{i}_product"
            trace_path = out_dir / f"run{i}_trace.zip"

            page = context.new_page()
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            start = time.monotonic()
            try:
                resp = page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                elapsed = time.monotonic() - start
                step = capture(page, resp, out_prefix, elapsed, PRODUCT_EXPECTED_MARKERS)
            except Exception as exc:
                elapsed = time.monotonic() - start
                step = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_s": round(elapsed, 3),
                    "final_url": None,
                    "http_status": None,
                    "classification": "navigation_error",
                    "classification_evidence": [],
                }

            dom_candidates = dump_dom_candidates(page) if dump_dom else None

            if step.get("classification") == "normal_product" and "error" not in step:
                try:
                    extraction = extract_and_validate_product(page, PRODUCT_URL, EXPECTED_CARD_CODE)
                except Exception as exc:
                    extraction = {
                        "extraction_status": "fail_closed",
                        "fail_reasons": [f"extraction_exception:{type(exc).__name__}: {exc}"],
                        "selector_version": SELECTOR_VERSION,
                        "extracted": {},
                        "validation": {},
                    }
            else:
                reason = "navigation_error" if "error" in step else "page_is_denial_or_challenge"
                extraction = {
                    "extraction_status": "fail_closed",
                    "fail_reasons": [reason],
                    "selector_version": SELECTOR_VERSION,
                    "extracted": {},
                    "validation": {},
                }

            context.tracing.stop(path=str(trace_path))
            page.close()

            run_record = {
                "run_index": i,
                "egress": egress,
                "http_status": step.get("http_status"),
                "final_url": step.get("final_url"),
                "classification": step.get("classification"),
                "classification_evidence": step.get("classification_evidence", []),
                "extraction_status": extraction["extraction_status"],
                "fail_reasons": extraction["fail_reasons"],
                "selector_version": extraction["selector_version"],
                "extracted": extraction["extracted"],
                "validation": extraction["validation"],
                "elapsed_s": step.get("elapsed_s"),
            }
            if dom_candidates is not None:
                run_record["dom_candidates"] = dom_candidates
            overall["runs"].append(run_record)

            # Only the latest run's artifacts are kept (small volume, per spec).
            if volume_dir:
                for suffix in (".html", ".png"):
                    src = out_prefix.with_suffix(suffix)
                    if src.exists():
                        (volume_dir / f"latest_product{suffix}").write_bytes(src.read_bytes())
                if trace_path.exists():
                    (volume_dir / "latest_trace.zip").write_bytes(trace_path.read_bytes())

            if i < repeat:
                time.sleep(delay_s)

        context.close()
        browser.close()

    classifications = {r["classification"] for r in overall["runs"]}
    extraction_statuses = {r["extraction_status"] for r in overall["runs"]}
    overall["all_runs_agree"] = len(classifications) <= 1 and len(extraction_statuses) <= 1

    (out_dir / "result.json").write_text(json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8")
    if volume_dir:
        (volume_dir / "result.json").write_text(json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8")
    return overall


def summarize_checks_by_egress_ip(checks: list[dict]) -> list[dict]:
    """Pure aggregation over already-recorded check dicts - no I/O, directly
    unit-testable. Groups by the diagnostic egress IP observed for each check
    (see EGRESS_IP_DISCLAIMER for what that IP does and doesn't prove).
    Preserves first-seen IP order."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for c in checks:
        ip = c.get("diagnostic_egress_ip") or "unknown"
        if ip not in groups:
            groups[ip] = {
                "egress_ip": ip,
                "checks_observed": 0,
                "http_200_count": 0,
                "http_403_count": 0,
                "http_429_count": 0,
                "challenge_count": 0,
                "other_status_count": 0,
                "_elapsed_s_values": [],
            }
            order.append(ip)
        g = groups[ip]
        g["checks_observed"] += 1
        status = c.get("http_status")
        if status == 200:
            g["http_200_count"] += 1
        elif status == 403:
            g["http_403_count"] += 1
        elif status == 429:
            g["http_429_count"] += 1
        else:
            g["other_status_count"] += 1
        if c.get("classification") == "challenge_or_captcha":
            g["challenge_count"] += 1
        if c.get("elapsed_s") is not None:
            g["_elapsed_s_values"].append(c["elapsed_s"])

    summary = []
    for ip in order:
        g = groups[ip]
        values = g.pop("_elapsed_s_values")
        g["average_elapsed_s"] = round(sum(values) / len(values), 3) if values else None
        summary.append(g)
    return summary


def _volume_root() -> Path | None:
    root = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    return Path(root) if root else None


def append_check_result(run_name: str, check_record: dict) -> str | None:
    """Appends one completed check as a single minified JSON line to a
    per-run NDJSON file on the attached Railway volume - so a partial run
    (killed deploy, OOM, crash) still preserves every check that finished
    before it, not just whatever made it into the final in-memory result.
    No-op (never raises) when no volume is attached, e.g. running locally."""
    volume_root = _volume_root()
    if volume_root is None:
        return None
    runs_dir = volume_root / "reliability_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{run_name}.ndjson"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(check_record, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")
    return str(path)


def log_event(event: str, **fields) -> None:
    """Every reliability-run stdout line is exactly one minified JSON object
    - never a pretty-printed multi-line dump. A single indent=2
    print(json.dumps(...)) of a full run's result previously exceeded
    Railway's 500 logs/sec ingestion cap and silently dropped most of a
    completed run's detail from the logs."""
    print(json.dumps({"event": event, **fields}, separators=(",", ":"), ensure_ascii=False))


def run_static_ip_reliability(
    url: str,
    out_name: str,
    checks: int,
    delay_s: float,
    expected_markers: list[str] | None,
    extract: bool = False,
    requested_card_code: str | None = None,
    dump_dom: bool = False,
) -> dict:
    """Static Outbound IP reliability check for one URL: ordinary bundled
    Playwright Chromium (no channel override), one brand-new browser context
    per check (no cookies/session carried over between checks), the optional
    fixed-proxy configuration is never applied regardless of environment
    variables (this mode specifically tests Railway's own static outbound IP
    egress, not a third-party proxy). Does not retry a failed check and does
    not stop on 403/429 - only on a genuine CAPTCHA/interactive-challenge
    classification - so distinct assigned static IPs can be compared across
    the full run."""
    out_dir = OUTPUT_ROOT / out_name
    out_dir.mkdir(parents=True, exist_ok=True)

    overall: dict = {
        "spike": "static_outbound_ip_reliability",
        "target_url": url,
        "checks_requested": checks,
        "delay_s": delay_s,
        "proxy_configured": False,
        "egress_ip_disclaimer": EGRESS_IP_DISCLAIMER,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "playwright_version": None,
        "browser_version": None,
        "extractor_version": SELECTOR_VERSION,
        "checks": [],
        "stopped_early": False,
        "stop_reason": None,
    }

    with sync_playwright() as p:
        overall["playwright_version"] = pkg_version("playwright")
        browser = p.chromium.launch(headless=True)
        overall["browser_version"] = browser.version

        for i in range(1, checks + 1):
            check_timestamp = datetime.now(timezone.utc).isoformat()
            egress = capture_egress_ip()
            context = browser.new_context()
            trace_path = out_dir / f"check{i:02d}_trace.zip" if extract else None
            if trace_path:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            out_prefix = out_dir / f"check{i:02d}"

            start = time.monotonic()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                elapsed = time.monotonic() - start
                step = capture(page, resp, out_prefix, elapsed, expected_markers)
            except Exception as exc:
                elapsed = time.monotonic() - start
                step = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_s": round(elapsed, 3),
                    "final_url": None,
                    "http_status": None,
                    "page_title": None,
                    "html_bytes": None,
                    "classification": "navigation_error",
                    "classification_evidence": [],
                }

            extraction = None
            dom_candidates = None
            if extract:
                dom_candidates = dump_dom_candidates(page) if dump_dom else None
                if step.get("classification") == "normal_product" and "error" not in step:
                    try:
                        extraction = extract_and_validate_product(
                            page, url, requested_card_code or EXPECTED_CARD_CODE
                        )
                    except Exception as exc:
                        extraction = {
                            "extraction_status": "fail_closed",
                            "fail_reasons": [f"extraction_exception:{type(exc).__name__}: {exc}"],
                            "selector_version": SELECTOR_VERSION,
                            "extraction_path": None,
                            "selector_diagnostics": None,
                            "extracted": {},
                            "validation": {},
                        }
                else:
                    reason = (
                        "navigation_error"
                        if "error" in step
                        else f"page_classification_not_normal_product:{step.get('classification')}"
                    )
                    extraction = {
                        "extraction_status": "fail_closed",
                        "fail_reasons": [reason],
                        "selector_version": SELECTOR_VERSION,
                        "extraction_path": None,
                        "selector_diagnostics": None,
                        "extracted": {},
                        "validation": {},
                    }

            if trace_path:
                context.tracing.stop(path=str(trace_path))
            context.close()

            check_record = {
                "check_number": i,
                "timestamp_utc": check_timestamp,
                "diagnostic_egress_ip": egress.get("ip"),
                "diagnostic_egress_lookup": egress,
                "http_status": step.get("http_status"),
                "final_url": step.get("final_url"),
                "page_title": step.get("page_title"),
                "response_body_length": step.get("html_bytes"),
                "classification": step.get("classification"),
                "classification_evidence": step.get("classification_evidence", []),
                "elapsed_s": step.get("elapsed_s"),
                "browser_version": overall["browser_version"],
                "extractor_version": SELECTOR_VERSION,
                "error": step.get("error"),
                "html_path": str(out_prefix.with_suffix(".html")) if out_prefix.with_suffix(".html").exists() else None,
                "screenshot_path": str(out_prefix.with_suffix(".png")) if out_prefix.with_suffix(".png").exists() else None,
                "trace_path": str(trace_path) if trace_path and trace_path.exists() else None,
            }
            if extract:
                check_record["extraction"] = extraction
                if dom_candidates is not None:
                    check_record["dom_candidates"] = dom_candidates
            overall["checks"].append(check_record)
            volume_path = append_check_result(out_name, check_record)
            log_event(
                "check_complete",
                run=out_name,
                check_number=i,
                diagnostic_egress_ip=check_record["diagnostic_egress_ip"],
                http_status=check_record["http_status"],
                classification=check_record["classification"],
                elapsed_s=check_record["elapsed_s"],
                extraction_status=(extraction or {}).get("extraction_status") if extract else None,
                volume_path=volume_path,
            )

            if step.get("classification") == "challenge_or_captcha":
                overall["stopped_early"] = True
                overall["stop_reason"] = f"challenge_or_captcha_at_check_{i}"
                break

            if i < checks:
                time.sleep(delay_s)

        browser.close()

    overall["summary_by_egress_ip"] = summarize_checks_by_egress_ip(overall["checks"])
    (out_dir / "result.json").write_text(json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8")
    return overall


def run_static_ip_reliability_pipeline() -> dict:
    """Orchestrates the full Static Outbound IP reliability test in one
    process/deployment run: 12 homepage checks (60s apart), then - only if
    every one of those 12 was a genuine normal HTTP 200 - 3 product-page
    checks (120s apart). Saves the first successful ("extracted") product
    extraction's artifacts to the Railway volume (RAILWAY_VOLUME_MOUNT_PATH)
    if attached, then holds the process open for 10 minutes so the artifacts
    can be retrieved before it exits."""
    out_dir = OUTPUT_ROOT / "static_ip_reliability_pipeline"
    out_dir.mkdir(parents=True, exist_ok=True)

    overall: dict = {
        "spike": "static_outbound_ip_reliability_pipeline",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "homepage": None,
        "homepage_gate_passed": False,
        "homepage_gate_reason": None,
        "product": None,
        "artifact_retention": None,
    }

    homepage = run_static_ip_reliability(
        url=HOMEPAGE_URL,
        out_name="static_ip_reliability_homepage",
        checks=12,
        delay_s=60.0,
        expected_markers=HOMEPAGE_EXPECTED_MARKERS,
        extract=False,
    )
    overall["homepage"] = homepage

    all_normal_200 = (
        not homepage["stopped_early"]
        and len(homepage["checks"]) == 12
        and all(
            c["http_status"] == 200 and c["classification"] == "normal_product"
            for c in homepage["checks"]
        )
    )
    overall["homepage_gate_passed"] = all_normal_200
    if not all_normal_200:
        overall["homepage_gate_reason"] = (
            homepage["stop_reason"]
            if homepage["stopped_early"]
            else "not_all_12_homepage_checks_were_genuine_normal_200"
        )
        (out_dir / "result.json").write_text(json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8")
        log_event(
            "homepage_gate",
            passed=False,
            reason=overall["homepage_gate_reason"],
            summary_by_egress_ip=homepage["summary_by_egress_ip"],
        )
        return overall

    log_event(
        "homepage_gate",
        passed=True,
        reason=None,
        summary_by_egress_ip=homepage["summary_by_egress_ip"],
    )

    product = run_static_ip_reliability(
        url=PRODUCT_URL,
        out_name="static_ip_reliability_product",
        checks=3,
        delay_s=120.0,
        expected_markers=PRODUCT_EXPECTED_MARKERS,
        extract=True,
        requested_card_code=EXPECTED_CARD_CODE,
        dump_dom=True,
    )
    overall["product"] = product
    log_event("product_summary", summary_by_egress_ip=product["summary_by_egress_ip"])

    first_success = next(
        (c for c in product["checks"] if (c.get("extraction") or {}).get("extraction_status") == "extracted"),
        None,
    )
    volume_root = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    retention: dict = {"volume_attached": bool(volume_root), "first_success_check": None, "files": []}

    if first_success and volume_root:
        retention["first_success_check"] = first_success["check_number"]
        target_dir = Path(volume_root) / "yuyutei_extract_latest"
        target_dir.mkdir(parents=True, exist_ok=True)

        product_out_dir = OUTPUT_ROOT / "static_ip_reliability_product"
        check_prefix = product_out_dir / f"check{first_success['check_number']:02d}"
        copy_map = {
            check_prefix.with_suffix(".html"): "rendered.html",
            check_prefix.with_suffix(".png"): "screenshot.png",
            product_out_dir / f"check{first_success['check_number']:02d}_trace.zip": "trace.zip",
        }
        for src, dest_name in copy_map.items():
            if src.exists():
                dest = target_dir / dest_name
                dest.write_bytes(src.read_bytes())
                retention["files"].append(
                    {"name": dest_name, "path": str(dest), "size_bytes": dest.stat().st_size}
                )

        result_json_path = target_dir / "result.json"
        result_json_path.write_text(json.dumps(product, indent=2, ensure_ascii=False), encoding="utf-8")
        retention["files"].append(
            {"name": "result.json", "path": str(result_json_path), "size_bytes": result_json_path.stat().st_size}
        )

        extraction_json_path = target_dir / "extraction.json"
        extraction_json_path.write_text(
            json.dumps(first_success["extraction"], indent=2, ensure_ascii=False), encoding="utf-8"
        )
        retention["files"].append(
            {
                "name": "extraction.json",
                "path": str(extraction_json_path),
                "size_bytes": extraction_json_path.stat().st_size,
            }
        )

        selector_diag_path = target_dir / "selector_diagnostics.json"
        selector_diag_payload = {
            "extraction_selector_diagnostics": first_success["extraction"].get("selector_diagnostics"),
            "dom_candidates": first_success.get("dom_candidates"),
        }
        selector_diag_path.write_text(
            json.dumps(selector_diag_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        retention["files"].append(
            {
                "name": "selector_diagnostics.json",
                "path": str(selector_diag_path),
                "size_bytes": selector_diag_path.stat().st_size,
            }
        )

        for f in retention["files"]:
            log_event("artifact_retained", name=f["name"], path=f["path"], size_bytes=f["size_bytes"])

    overall["artifact_retention"] = retention
    (out_dir / "result.json").write_text(json.dumps(overall, indent=2, ensure_ascii=False), encoding="utf-8")

    if first_success and volume_root:
        log_event("holding_process_alive_s", seconds=600, path="/data/yuyutei_extract_latest/")
        time.sleep(600)

    return overall


EXTRACT_MODE = "railway_extract"
RELIABILITY_MODE = "static_ip_reliability"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=sorted(MODES.keys()) + [EXTRACT_MODE, RELIABILITY_MODE], required=True
    )
    parser.add_argument("--repeat", type=int, default=3, help=f"{EXTRACT_MODE} only: number of runs")
    parser.add_argument("--delay-s", type=float, default=8.0, help=f"{EXTRACT_MODE} only: delay between runs")
    parser.add_argument("--dump-dom", action="store_true", help=f"{EXTRACT_MODE} only: log DOM selector candidates")
    args = parser.parse_args()

    print(f"python={sys.version.split()[0]} platform={platform.platform()}")
    print(f"proxy_configured={get_proxy_config() is not None}")  # never logs the endpoint or credentials

    if args.mode == RELIABILITY_MODE:
        # Per-check and per-stage detail is already streamed live as compact
        # single-line events by run_static_ip_reliability /
        # run_static_ip_reliability_pipeline (see log_event) and written in
        # full to the attached volume (see append_check_result) - this is
        # deliberately just a small closing summary, not a re-dump of
        # `result`, to avoid ever again exceeding Railway's log-rate cap.
        result = run_static_ip_reliability_pipeline()
        log_event(
            "reliability_run_complete",
            homepage_gate_passed=result["homepage_gate_passed"],
            homepage_gate_reason=result["homepage_gate_reason"],
            homepage_checks=len(result["homepage"]["checks"]),
            product_checks=len(result["product"]["checks"]) if result["product"] else 0,
            artifact_retention=result.get("artifact_retention"),
        )
        return

    if args.mode == EXTRACT_MODE:
        result = run_extraction(repeat=args.repeat, delay_s=args.delay_s, dump_dom=args.dump_dom)
        for run_record in result["runs"]:
            egress = run_record.get("egress") or {}
            print(
                f"run={run_record['run_index']} egress_ip={egress.get('ip')} "
                f"country={egress.get('country')} status={run_record.get('http_status')} "
                f"classification={run_record.get('classification')} "
                f"extraction_status={run_record.get('extraction_status')} "
                f"fail_reasons={run_record.get('fail_reasons')} "
                f"sell_price_jpy={run_record.get('extracted', {}).get('sell_price_jpy')} "
                f"stock_status={run_record.get('extracted', {}).get('stock_status')} "
                f"final_url={run_record.get('final_url')} "
                f"elapsed_s={run_record.get('elapsed_s')}"
            )
        print(f"all_runs_agree={result['all_runs_agree']}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    result = run(args.mode)

    if result.get("egress"):
        egress = result["egress"]
        print(
            f"egress_ip={egress.get('ip')} country={egress.get('country')} "
            f"region={egress.get('region')} error={egress.get('error')}"
        )
    for step_name, step in result.get("steps", {}).items():
        print(
            f"step={step_name} status={step.get('http_status')} "
            f"classification={step.get('classification')} "
            f"title={step.get('page_title')!r} url={step.get('final_url')} "
            f"body_bytes={step.get('html_bytes')} error={step.get('error')}"
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
