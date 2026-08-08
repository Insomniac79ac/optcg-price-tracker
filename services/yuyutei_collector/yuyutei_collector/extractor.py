"""Page classification and product extraction, moved out of
spikes/yuyutei-browser-feasibility/spike.py after that spike's extractor v3
was live-validated against a real Yuyu-Tei OP01-001 response (see
spikes/yuyutei-browser-feasibility/tests/fixtures/product_op01_001_reduced.html,
a reduction of that genuine retrieved page). No AI calls; deterministic
regex/DOM extraction only.

Extraction hierarchy per field, in priority order:
1. trusted JSON-LD (script[type=application/ld+json] Product.offers)
2. product-scoped DOM (leaf elements inside the real product-detail
   container only - never the page-wide DOM)
3. product-container text fallback (still confined to that same container)
4. whole-page regex - diagnostic-only, logged for audit, never eligible to
   become an accepted value

A price or stock value is only accepted when the JSON-LD side and the DOM
side (tiers 1-3 collapsed into one "DOM" side) independently agree - see
extract_with_agreement. Disagreement, or either side being indeterminate,
fails closed.
"""

import json
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

SELECTOR_VERSION = "v3"
# Historical default for the original single-print vertical slice. Callers
# should pass their mapping/print's own treatment explicitly (see
# extract_with_agreement's expected_treatment parameter) rather than rely on
# this - kept only so existing call sites without that argument still work.
EXPECTED_TREATMENT = "parallel"

CARD_CODE_RE = re.compile(r"\bOP\d{2}-\d{3}\b")
PRICE_LEAF_RE = re.compile(r"^[¥￥]?\s*([\d,]+)\s*円$")
PRICE_ANYWHERE_RE = re.compile(r"[¥￥]?[\d,]+\s*円")
MAIN_CONTAINER_KEYWORD_RE = re.compile(r"product|detail|item|goods", re.IGNORECASE)


def _describe_element(el) -> str:
    tag = el.name
    el_id = el.get("id")
    classes = el.get("class") or []
    if el_id:
        return f"{tag}#{el_id}"
    if classes:
        return f"{tag}.{'.'.join(classes)}"
    return tag


def _external_product_id(url: str) -> str | None:
    """Derived from the stable product URL path (.../card/<series>/<id>),
    not the displayed card code - this is Yuyu-Tei's own internal product
    id, a separate identifier from the printed card number."""
    m = re.search(r"/card/([a-z0-9]+)/(\d+)", url, re.IGNORECASE)
    return f"{m.group(1)}-{m.group(2)}".lower() if m else None


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
    {1 (from "01"), 1 (from "001")}. Guards against the historical "OP01 ->
    1 JPY" bug regardless of which extraction tier produced the price."""
    for code in codes:
        if not code:
            continue
        for group in re.findall(r"\d+", code):
            if int(group) == price:
                return True
    return False


def _find_jsonld_product(soup: BeautifulSoup) -> dict | None:
    """First schema.org Product block found in a
    <script type="application/ld+json"> tag, if any - tier 1."""
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


def _normalize_availability(raw: str) -> str | None:
    """schema.org `offers.availability` (e.g. "https://schema.org/InStock")
    -> internal stock state, or None if empty/unrecognized."""
    availability_lower = raw.lower()
    if "outofstock" in availability_lower:
        return "out_of_stock"
    if "instock" in availability_lower:
        return "in_stock"
    if availability_lower:
        return "unknown_present_marker"
    return None


def _find_main_detail_container(soup: BeautifulSoup):
    """Smallest element that both (a) has an id/class hinting
    product/detail/item/goods AND (b) actually contains a card-code-shaped
    string and a 円-suffixed price - not just any element with a matching
    class name."""
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
    captured page) - deliberately not the decorative breadcrumb h1
    elsewhere on the page, and not a recommendation tile's <p> title."""
    power = soup.find(id="power") or soup.find(class_="power")
    if power:
        heading = power.find(["h2", "h3"])
        if heading and heading.get_text(strip=True):
            return heading
    return None


def _leaf_price_candidates(container) -> list[dict]:
    """Tier 2: every leaf (no element children) descendant of `container`
    whose own text is *only* a 円-suffixed price. Recommendation-tile and
    breadcrumb prices are excluded structurally (they simply aren't inside
    `container`), not by keyword guessing."""
    candidates = []
    for el in container.find_all(True):
        if el.find(True) is not None:
            continue
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


def _container_text_price_fallback(container) -> dict | None:
    """Tier 3: a text-regex scan still confined to `container` - used only
    when tier 2 finds no single leaf-level price candidate. Never looks
    outside `container`."""
    container_text = container.get_text(" ", strip=True)
    m = PRICE_ANYWHERE_RE.search(container_text)
    if not m:
        return None
    normalized = _normalize_price_text(m.group(0))
    if normalized is None:
        return None
    return {
        "selector": f"{_describe_element(container)} (container text scan)",
        "raw_text": m.group(0),
        "normalized_price": normalized,
    }


def _whole_page_diagnostic_price(html: str) -> dict | None:
    """Tier 4: diagnostic-only whole-page scan. Structurally cannot become
    an accepted price - callers must never read this into `extracted`."""
    m = PRICE_ANYWHERE_RE.search(html)
    if not m:
        return None
    return {"raw_text": m.group(0), "normalized_price": _normalize_price_text(m.group(0))}


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


DENIAL_TITLES = [
    "403", "403 forbidden", "access denied", "just a moment...", "just a moment",
    "attention required! | cloudflare", "please wait...", "please stand by",
]
DENIAL_BODY_PHRASES = [
    "checking your browser before accessing",
    "please stand by, while we are checking your browser",
    "verify you are human",
    "enable javascript and cookies to continue",
    "を拒否されました",
    "アクセスが拒否",
]
CHALLENGE_DOM_MARKERS = [
    "cf-challenge-running", "cf_challenge", "challenges.cloudflare.com",
    "g-recaptcha", "cf-turnstile", 'id="challenge-form"', 'id="challenge-stage"',
]
WEAK_MARKERS = ["cloudflare", "captcha", "cf-error", "ray id"]


def classify_page(
    status: int | None,
    html: str,
    title: str,
    expected_markers: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Evidence-based classification. A bare mention of "cloudflare" (or any
    other weak marker) is never sufficient on its own - Cloudflare is
    Yuyu-Tei's CDN, so that string legitimately appears on normal 200
    pages. Returns (classification, evidence)."""
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
    weak_evidence_with_missing_content = bool(weak_marker_hits) and expected_present is False

    if strong_evidence or weak_evidence_with_missing_content:
        if weak_evidence_with_missing_content and not strong_evidence:
            evidence.append("weak_marker_with_missing_expected_content")
        return "challenge_or_captcha", evidence

    if status == 200 and html_bytes > 500:
        return "normal_product", evidence
    if status is None:
        return "navigation_error", evidence
    return f"other_status_{status}", evidence


def extract_with_agreement(
    html: str,
    source_url: str,
    requested_card_code: str,
    expected_treatment: str = EXPECTED_TREATMENT,
) -> dict:
    """Independent-agreement extractor (selector_version v3). Extracts
    JSON-LD and DOM values independently and only accepts a price/stock
    value when both sides agree - failing closed (accepted value = None) on
    disagreement or when either side is indeterminate. Never hardcodes an
    expected price; the only accepted price is whatever the live page's two
    independent sources agree on."""
    soup = BeautifulSoup(html, "html.parser")
    fail_reasons: list[str] = []
    rejected: list[dict] = []
    accepted_selectors: dict = {
        "main_container": None,
        "price_selector": None,
        "stock_selector": None,
        "card_code_selector": None,
        "title_selector": None,
        "jsonld_present": False,
    }

    # ---- JSON-LD side (tier 1, independent of DOM) ----
    jsonld_product = _find_jsonld_product(soup)
    jsonld_raw: dict = {}
    jsonld_norm: dict = {
        "price": None, "currency": None, "availability_raw": None,
        "availability": None, "title": None, "card_code": None, "image_url": None,
    }
    if jsonld_product:
        accepted_selectors["jsonld_present"] = True
        offers = jsonld_product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        offers = offers or {}
        jsonld_raw = {
            "name": jsonld_product.get("name"),
            "offers_price": offers.get("price"),
            "offers_priceCurrency": offers.get("priceCurrency"),
            "offers_availability": offers.get("availability"),
            "description": jsonld_product.get("description"),
            "image": jsonld_product.get("image"),
        }
        jsonld_norm["price"] = _normalize_price_text(str(offers.get("price", "")))
        jsonld_norm["currency"] = offers.get("priceCurrency")
        jsonld_norm["availability_raw"] = offers.get("availability")
        jsonld_norm["availability"] = _normalize_availability(str(offers.get("availability") or ""))
        jsonld_norm["title"] = jsonld_product.get("name")
        description = str(jsonld_product.get("description") or "")
        code_match = CARD_CODE_RE.search(description) or CARD_CODE_RE.search(str(jsonld_product.get("name") or ""))
        jsonld_norm["card_code"] = code_match.group(0) if code_match else None
        jsonld_norm["image_url"] = jsonld_product.get("image") or None
    else:
        rejected.append({"reason": "no_jsonld_product_block_found"})

    # ---- DOM side (tiers 2-3, independent of JSON-LD, scoped to the real product container) ----
    container = _find_main_detail_container(soup)
    dom_raw: dict = {"container": None, "price_candidates": [], "stock_element": None, "card_code_element": None}
    dom_norm: dict = {"price": None, "stock": None, "title": None, "card_code": None}
    dom_price_tier: str | None = None

    if container is not None:
        dom_raw["container"] = _describe_element(container)
        accepted_selectors["main_container"] = dom_raw["container"]

        price_candidates = _leaf_price_candidates(container)
        dom_raw["price_candidates"] = price_candidates
        distinct_prices = {c["normalized_price"] for c in price_candidates}
        if len(price_candidates) == 1:
            dom_norm["price"] = price_candidates[0]["normalized_price"]
            accepted_selectors["price_selector"] = price_candidates[0]["selector"]
            dom_price_tier = "leaf_element_scoped"
        elif len(distinct_prices) > 1:
            rejected.append({"reason": "ambiguous_dom_price_candidates", "candidates": price_candidates})
        else:
            # No leaf-level candidate at all - tier 3 fallback, still
            # confined to this same container.
            fallback = _container_text_price_fallback(container)
            if fallback is not None:
                dom_norm["price"] = fallback["normalized_price"]
                accepted_selectors["price_selector"] = fallback["selector"]
                dom_price_tier = "container_text_scoped_fallback"
            else:
                rejected.append({"reason": "dom_price_not_found_in_container"})

        stock_el = _find_stock_element(container)
        dom_raw["stock_element"] = stock_el
        if stock_el:
            dom_norm["stock"] = stock_el["stock_status"]
            accepted_selectors["stock_selector"] = stock_el["selector"]
        else:
            rejected.append({"reason": "dom_stock_label_not_found_in_container"})

        card_code_el = _find_card_code_element(container)
        dom_raw["card_code_element"] = card_code_el
        if card_code_el:
            dom_norm["card_code"] = card_code_el["text"]
            accepted_selectors["card_code_selector"] = card_code_el["selector"]
    else:
        rejected.append({"reason": "no_product_container_found"})

    title_el = _find_title_container(soup)
    dom_norm["title"] = title_el.get_text(strip=True) if title_el else None
    if title_el is not None:
        accepted_selectors["title_selector"] = _describe_element(title_el)

    # Tier 4: whole-page diagnostic only - never contributes to an accepted
    # value, logged purely for audit (e.g. to show the historical "OP01 ->
    # 1 JPY" trap is visible but was not taken).
    whole_page_diagnostic = _whole_page_diagnostic_price(html)

    # ---- Price: require independent agreement, fail closed otherwise ----
    price_agreement = {"jsonld_price": jsonld_norm["price"], "dom_price": dom_norm["price"], "agree": False}
    accepted_price = None
    if jsonld_norm["price"] is not None and dom_norm["price"] is not None:
        if jsonld_norm["price"] == dom_norm["price"]:
            price_agreement["agree"] = True
            accepted_price = jsonld_norm["price"]
        else:
            fail_reasons.append(
                f"price_disagreement:jsonld={jsonld_norm['price']},dom={dom_norm['price']}"
            )
    else:
        fail_reasons.append("price_agreement_indeterminate:missing_jsonld_or_dom_value")

    external_id = _external_product_id(source_url)
    if accepted_price is not None and _price_matches_code_digits(accepted_price, requested_card_code, external_id):
        fail_reasons.append(f"price_matches_card_code_or_id_digits:{accepted_price}")
        price_agreement["agree"] = False
        accepted_price = None

    # ---- Stock: require semantic agreement, fail closed otherwise ----
    stock_agreement = {
        "jsonld_availability": jsonld_norm["availability"],
        "dom_stock": dom_norm["stock"],
        "agree": False,
    }
    accepted_stock = None
    if jsonld_norm["availability"] is not None and dom_norm["stock"] is not None:
        if jsonld_norm["availability"] == dom_norm["stock"]:
            stock_agreement["agree"] = True
            accepted_stock = jsonld_norm["availability"]
        else:
            fail_reasons.append(
                f"stock_disagreement:jsonld={jsonld_norm['availability']},dom={dom_norm['stock']}"
            )
    elif jsonld_norm["availability"] is None and dom_norm["stock"] is None:
        fail_reasons.append("stock_agreement_indeterminate:missing_both_sides")
    else:
        # Exactly one side present: JSON-LD is never allowed to override a
        # conflicting (or simply present) visible DOM value, and a lone DOM
        # value with no JSON-LD to corroborate it is likewise not enough.
        fail_reasons.append("stock_agreement_indeterminate:only_one_side_present")

    # ---- Identity checks ----
    resolved_card_code = dom_norm["card_code"] or jsonld_norm["card_code"]
    if dom_norm["card_code"] and jsonld_norm["card_code"] and dom_norm["card_code"] != jsonld_norm["card_code"]:
        fail_reasons.append(
            f"card_code_source_disagreement:jsonld={jsonld_norm['card_code']},dom={dom_norm['card_code']}"
        )
    if resolved_card_code != requested_card_code:
        fail_reasons.append(f"card_code_conflict:displayed={resolved_card_code},expected={requested_card_code}")

    title_text = dom_norm["title"] or jsonld_norm["title"] or ""
    if not title_text:
        fail_reasons.append("product_title_missing")

    if "パラレル" in title_text:
        treatment = "parallel"
    elif "ノーマル" in title_text:
        treatment = "normal"
    elif title_text:
        # Yuyu-Tei only marks a title with a special-treatment word
        # (parallel/normal) when the product needs disambiguating from a
        # sibling print; an otherwise-valid title with neither marker is the
        # base/default printing - source-wide convention, not a per-card rule.
        treatment = "normal"
    else:
        treatment = None
    if treatment != expected_treatment:
        fail_reasons.append(f"treatment_conflict:displayed={treatment},expected={expected_treatment}")

    extraction_status = "extracted" if not fail_reasons else "fail_closed"

    return {
        "extraction_status": extraction_status,
        "fail_reasons": fail_reasons,
        "selector_version": SELECTOR_VERSION,
        "raw": {"jsonld": jsonld_raw, "dom": dom_raw},
        "normalized": {"jsonld": jsonld_norm, "dom": dom_norm},
        "dom_price_tier": dom_price_tier,
        "whole_page_diagnostic_price": whole_page_diagnostic,
        "agreement": {"price": price_agreement, "stock": stock_agreement},
        "accepted_selectors": accepted_selectors,
        "rejected_candidates": rejected,
        "extracted": {
            "source_url": source_url,
            "final_url": source_url,
            "product_title": title_text or None,
            "card_code": resolved_card_code,
            "treatment": treatment,
            "sell_price_jpy": accepted_price,
            "stock_status": accepted_stock,
            "product_image_url": jsonld_norm["image_url"],
            "external_product_id": external_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    }
