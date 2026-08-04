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


SELECTOR_VERSION = "v1"
EXPECTED_CARD_CODE = "OP01-001"
PRODUCT_EXPECTED_MARKERS = ["ロロノア・ゾロ", "パラレル"]
CATEGORY_EXPECTED_MARKERS = ["ROMANCE DAWN"]
HOMEPAGE_EXPECTED_MARKERS = ["遊々亭"]


def _meta_content(page: Page, prop: str) -> str | None:
    el = page.query_selector(f'meta[property="{prop}"]') or page.query_selector(f'meta[name="{prop}"]')
    return el.get_attribute("content") if el else None


def _external_product_id(url: str) -> str | None:
    """Derived from the stable product URL path (.../card/<series>/<id>), not
    the displayed card code - this is Yuyu-Tei's own internal product id, a
    separate identifier from the printed card number."""
    m = re.search(r"/card/([a-z0-9]+)/(\d+)", url, re.IGNORECASE)
    return f"{m.group(1)}-{m.group(2)}".lower() if m else None


def extract_and_validate_product(page: Page, source_url: str, requested_card_code: str = EXPECTED_CARD_CODE) -> dict:
    """Deterministic (non-AI) extraction over stable selectors: OGP meta tags
    for title/image (standard, markup-independent), regex over rendered body
    text for the semi-structured Japanese fields. Fails closed - see
    `validation` - rather than returning a plausible-looking but wrong value.
    Dealer buy-price is intentionally not extracted in this tranche."""
    html = page.content()
    text = page.inner_text("body") if page.query_selector("body") else ""

    product_title = _meta_content(page, "og:title") or page.title() or None
    image_url = _meta_content(page, "og:image")

    card_code_match = re.search(r"\bOP\d{2}-\d{3}\b", text) or re.search(r"\bOP\d{2}-\d{3}\b", html)
    card_code = card_code_match.group(0) if card_code_match else None

    treatment = None
    if "パラレル" in text:
        treatment = "parallel"
    elif "ノーマル" in text:
        treatment = "normal"

    sell_price_jpy = None
    sell_match = re.search(r"販売[^\d¥￥]{0,20}[¥￥]?([\d,]+)\s*円?", text)
    if sell_match:
        try:
            sell_price_jpy = int(sell_match.group(1).replace(",", ""))
        except ValueError:
            sell_price_jpy = None

    stock_status = None
    if "在庫あり" in text:
        stock_status = "in_stock"
    elif "在庫切れ" in text or "品切れ" in text:
        stock_status = "out_of_stock"
    elif "在庫" in text:
        stock_status = "unknown_present_marker"

    extracted = {
        "source_url": source_url,
        "final_url": page.url,
        "product_title": product_title,
        "card_code": card_code,
        "treatment": treatment,
        "sell_price_jpy": sell_price_jpy,
        "stock_status": stock_status,
        "product_image_url": image_url,
        "external_product_id": _external_product_id(page.url) or _external_product_id(source_url),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    fail_reasons = []
    if not product_title:
        fail_reasons.append("product_title_missing")
    if sell_price_jpy is None:
        fail_reasons.append("sell_price_missing_or_not_numeric")
    if card_code is not None and card_code != requested_card_code:
        fail_reasons.append(f"card_code_conflict:displayed={card_code},expected={requested_card_code}")
    if treatment is not None and treatment != "parallel":
        fail_reasons.append(f"treatment_conflict:displayed={treatment},expected=parallel")

    validation = {
        "title_present": product_title is not None,
        "price_numeric": sell_price_jpy is not None,
        "card_code_matches_expected": card_code is None or card_code == requested_card_code,
        "treatment_matches_expected": treatment is None or treatment == "parallel",
    }

    return {
        "extraction_status": "extracted" if not fail_reasons else "fail_closed",
        "fail_reasons": fail_reasons,
        "selector_version": SELECTOR_VERSION,
        "extracted": extracted,
        "validation": validation,
    }


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


EXTRACT_MODE = "railway_extract"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES.keys()) + [EXTRACT_MODE], required=True)
    parser.add_argument("--repeat", type=int, default=3, help=f"{EXTRACT_MODE} only: number of runs")
    parser.add_argument("--delay-s", type=float, default=8.0, help=f"{EXTRACT_MODE} only: delay between runs")
    parser.add_argument("--dump-dom", action="store_true", help=f"{EXTRACT_MODE} only: log DOM selector candidates")
    args = parser.parse_args()

    print(f"python={sys.version.split()[0]} platform={platform.platform()}")
    print(f"proxy_configured={get_proxy_config() is not None}")  # never logs the endpoint or credentials

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
