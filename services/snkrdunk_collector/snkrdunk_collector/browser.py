"""Playwright navigation, bounded wall-clock deadlines, and compact JSON
logging. Moved out of spikes/snkrdunk-browser-feasibility/spike.py (page
classification, deadline(), navigate_and_capture()) after that spike's
extractor was live-validated against a real SNKRDUNK product page
(https://snkrdunk.com/apparels/104428) - see that spike's README/tests for
the feasibility evidence this collector is built from. No proxy rotation, no
CAPTCHA-solving, no fingerprint spoofing beyond supported Playwright context
options, no attempt to bypass a rendered challenge/denial page, one normal
navigation attempt per URL per run - no retries after 403/429/challenge.
"""

import hashlib
import json
import re
import signal
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from playwright.sync_api import Page

HOMEPAGE_URL = "https://snkrdunk.com/"

DESKTOP_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
DESKTOP_ACCEPT_LANGUAGE = "ja-JP,ja;q=0.9,en;q=0.8"
DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}

# Same evidence-based denial/challenge markers validated in the feasibility
# spike (spikes/snkrdunk-browser-feasibility/spike.py) - a bare mention of
# "cloudflare" etc. is never sufficient on its own, since Cloudflare is
# SNKRDUNK's CDN and legitimately appears on normal pages.
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
DENIAL_BODY_PHRASES = [
    "checking your browser before accessing",
    "please stand by, while we are checking your browser",
    "verify you are human",
    "enable javascript and cookies to continue",
    "アクセスが拒否",
    "を拒否されました",
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
WEAK_MARKERS = ["cloudflare", "captcha", "cf-error", "ray id"]

# Since 2026-10-26 a SNKRDUNK product page arrives with every condition chip reading
# 出品待ち and fills the real prices in from its own price request
# (GET /v2/products/<id>/size-chips, <id> = the /apparels/<id> of the page) after load. A
# snapshot taken before that response is placeholders, which would read as "nothing listed".
# A product capture therefore waits for THIS product's size-chips response, reads its body
# (the response the page already received; no extra request), lets the page render it, and
# only then takes the snapshot. A page whose chips are ALL still 出品待ち is accepted only
# when that body itself holds no price; otherwise (or without the response) the capture is
# PRICES_NOT_LOADED and never reaches extraction. A 403/429 on it is a source denial.
PRICE_CHIPS_PATH = re.compile(r"/v2/products/(\d+)/size-chips")
PRODUCT_PATH = re.compile(r"/apparels/(\d+)/?")
SNKRDUNK_HOSTS = frozenset({"snkrdunk.com", "www.snkrdunk.com"})
PRICE_CHIPS_WAIT_S = 15.0
PRICE_CHIPS_RENDER_MS = 750
PRICE_CHIPS_RENDER_MAX_S = 3.0
PRICE_CHIPS_POLL_MS = 250
PRICE_CHIPS_BODY_MAX = 512_000
PRICES_NOT_LOADED = "prices_not_loaded"
_PRICE_KEY = re.compile("price", re.I)
_DIGITS = re.compile(r"[0-9][0-9,]*")


def _price_chips_response(response) -> tuple[str, int] | None:
    """(product id, status) when this is a SNKRDUNK size-chips response."""
    try:
        parsed = urlsplit(response.url)
    except (AttributeError, ValueError):
        return None
    if parsed.hostname not in SNKRDUNK_HOSTS:
        return None
    match = PRICE_CHIPS_PATH.fullmatch(parsed.path)
    return (match.group(1), response.status) if match else None


def expected_price_product(url: str | None) -> str | None:
    """The product id whose size-chips response this page needs: /apparels/<id> on SNKRDUNK."""
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return None
    match = PRODUCT_PATH.fullmatch(parsed.path) if parsed.hostname in SNKRDUNK_HOSTS else None
    return match.group(1) if match else None


def wait_for_condition_prices(page: Page, seen: list, product_id: str, *, clock=None):
    """Wait (bounded) for this product's size-chips response. `seen` holds (id, status,
    response) from a listener registered before navigation; other products' responses (a
    recommendation, a prefetch) are ignored. Returns (evidence, response or None)."""
    clock = clock or time.monotonic
    start = clock()
    end = start + PRICE_CHIPS_WAIT_S

    def ours():
        return next((entry for entry in seen if entry[0] == product_id), None)

    while ours() is None and clock() < end:
        page.wait_for_timeout(PRICE_CHIPS_POLL_MS)
    found = ours()
    waited = round(clock() - start, 3)
    if found is None:
        return {"status": "not_seen", "product_id": product_id, "waited_s": waited}, None
    status = "response_200" if found[1] == 200 else f"http_{found[1]}"
    return {"status": status, "product_id": product_id, "waited_s": waited}, found[2]


def _price_value(value) -> str:
    """'price' a positive amount, 'empty' no amount, 'other' anything else."""
    if value is None or isinstance(value, bool):
        return "empty" if value is None else "other"
    if isinstance(value, (int, float)):
        return "price" if value > 0 else "empty"
    if isinstance(value, str):
        digits = _DIGITS.search(value)
        if not value.strip() or value.strip() in {"-", "--", "出品待ち"}:
            return "empty"
        if digits:
            return "price" if int(digits.group(0).replace(",", "")) > 0 else "empty"
    return "other"


def body_listings(text: str | None) -> dict:
    """What the size-chips body says, without assuming its exact schema: every key naming a
    price, at any depth. 'prices' when one holds a positive amount, 'none' when there are such
    keys and none does, 'unrecognised' otherwise (not JSON, no price keys, odd values)."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return {"body_listings": "unrecognised", "body_json": False}
    kinds = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if _PRICE_KEY.search(str(key)) and not isinstance(value, (dict, list)):
                    kinds.append(_price_value(value))
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    shape = sorted(data)[:8] if isinstance(data, dict) else type(data).__name__
    verdict = ("prices" if "price" in kinds
               else "none" if kinds and set(kinds) == {"empty"} else "unrecognised")
    return {"body_listings": verdict, "body_json": True, "body_price_keys": len(kinds),
            "body_priced": kinds.count("price"), "body_shape": shape}


def read_price_body(response) -> tuple[dict, str | None]:
    """The size-chips body the page already received (Response.body() reads it from the
    browser; it is not another request)."""
    try:
        body = response.body()
    except Exception as exc:  # noqa: BLE001 - evicted or failed body: not evidence
        return {"body_listings": "unavailable", "body_error": type(exc).__name__}, None
    if len(body) > PRICE_CHIPS_BODY_MAX:
        return {"body_listings": "unrecognised", "body_bytes": len(body), "body_error": "too_large"}, None
    text = body.decode("utf-8", "replace")
    return {"body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest()[:16],
            **body_listings(text)}, text


def chips_all_awaiting(html: str) -> bool:
    """True when the product's chip picker is found and every chip still reads 出品待ち (no
    chip anywhere shows a price), i.e. the page has not rendered any price."""
    from bs4 import BeautifulSoup

    from snkrdunk_collector.extractor import _has_module_class, find_condition_chip_container

    container, _ = find_condition_chip_container(BeautifulSoup(html or "", "html.parser"))
    if container is None:
        return False
    chips = [b for b in container.find_all("button", recursive=False) if _has_module_class(b, "chip")]
    values = [p for chip in chips for p in chip.find_all("p", recursive=False)]
    return bool(chips) and not any(_has_module_class(p, "price") for p in values) and all(
        any(_has_module_class(p, "awaiting") and p.get_text(strip=True) == "出品待ち"
            for p in chip.find_all("p", recursive=False))
        for chip in chips
    )


def confirm_prices_loaded(evidence: dict, html: str, *, all_awaiting: bool | None = None) -> dict:
    """'loaded' only when this product's 200 size-chips response is named by the page and the
    snapshot agrees with it: rendered prices, or every chip 出品待ち and a body with no price."""
    if evidence.get("status") != "response_200":
        return evidence
    if evidence["product_id"] not in set(PRICE_CHIPS_PATH.findall(html or "")):
        return {**evidence, "status": "not_named_by_page"}
    if all_awaiting is None:
        all_awaiting = chips_all_awaiting(html)
    if not all_awaiting:
        return {**evidence, "status": "loaded", "dom": "rendered"}
    listings = evidence.get("body_listings")
    if listings == "none":
        return {**evidence, "status": "loaded", "dom": "all_awaiting_body_confirms"}
    return {**evidence, "status": "dom_not_rendered" if listings == "prices" else f"body_{listings}",
            "dom": "all_awaiting"}


def log_event(event: str, **fields) -> None:
    """Every collector stdout line is exactly one minified JSON object -
    never a pretty-printed multi-line dump, consistent with
    yuyutei_collector.browser.log_event (a pretty dump previously exceeded
    Railway's log ingestion rate cap in the spike that pattern was moved
    from)."""
    print(json.dumps({"event": event, **fields}, separators=(",", ":"), ensure_ascii=False))


class DeadlineExceeded(Exception):
    """Raised by deadline() when its wall-clock budget elapses. Unix-only
    (uses signal.alarm, main-thread only) - correct for this service's
    single Railway Linux container target."""


_deadline_stack: list[tuple[float, str]] = []


def _deadline_signal_handler(signum, frame) -> None:
    label = _deadline_stack[-1][1] if _deadline_stack else "deadline"
    raise DeadlineExceeded(label)


def _rearm_alarm() -> None:
    if not _deadline_stack:
        signal.alarm(0)
        return
    nearest_at = min(at for at, _ in _deadline_stack)
    remaining = max(1, int(round(nearest_at - time.monotonic())))
    signal.alarm(remaining)


@contextmanager
def deadline(seconds: float, label: str):
    """Wall-clock deadline for the enclosed block. Nestable - the nearest
    deadline always wins."""
    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _deadline_signal_handler)
    _deadline_stack.append((time.monotonic() + seconds, label))
    _rearm_alarm()
    try:
        yield
    finally:
        _deadline_stack.pop()
        _rearm_alarm()
        signal.signal(signal.SIGALRM, old_handler)


def classify_page(status: int | None, html: str, title: str) -> tuple[str, list[str]]:
    """Deterministic, evidence-based classification. Returns (classification,
    evidence). Classifications: normal_page, static_403, static_429,
    challenge_or_captcha, error."""
    evidence: list[str] = []
    title_lower = (title or "").strip().lower()
    html_lower = (html or "").lower()

    for marker in CHALLENGE_DOM_MARKERS:
        if marker.lower() in html_lower:
            evidence.append(f"dom_marker:{marker}")
    for phrase in DENIAL_BODY_PHRASES:
        if phrase.lower() in html_lower:
            evidence.append(f"body_phrase:{phrase}")
    for denial_title in DENIAL_TITLES:
        if denial_title in title_lower:
            evidence.append(f"title:{denial_title}")

    if evidence:
        return "challenge_or_captcha", evidence

    if status == 403:
        return "static_403", ["http_status:403"]
    if status == 429:
        return "static_429", ["http_status:429"]
    if status is not None and status >= 400:
        return "error", [f"http_status:{status}"]

    weak_hits = [m for m in WEAK_MARKERS if m in html_lower]
    if weak_hits and len(html or "") < 2000:
        return "error", [f"weak_marker:{m}" for m in weak_hits] + ["short_body"]

    if status == 200:
        return "normal_page", []
    if status is None:
        return "error", ["no_http_status"]
    return "error", [f"http_status:{status}"]


def goto_and_capture(page: Page, url: str, *, before_parse=None, condition_prices=False) -> dict:
    """One bounded navigation attempt. Returns a dict with either an "error"
    key (navigation-level exception, e.g. DNS/timeout) or the captured
    page state + classification. `condition_prices` (product pages): the
    snapshot waits for the page's own price request, see PRICE_CHIPS_PATH."""
    start = time.monotonic()
    seen: list = []
    listener = None
    try:
        if condition_prices:
            def listener(response):
                found = _price_chips_response(response)
                if found:
                    seen.append((*found, response))
            page.on("response", listener)
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        status = response.status if response else None
        html = page.content()
        title = page.title()
        classification, evidence = classify_page(status, html, title)
        prices = chips = None
        if condition_prices:
            prices, chips = _settle_condition_prices(page, seen, status, classification)
            if prices["status"] == "response_200":
                html = page.content()
                all_awaiting = chips_all_awaiting(html)
                render_end = time.monotonic() + PRICE_CHIPS_RENDER_MAX_S
                # The body holds prices but none is on the page yet: give the render a
                # little longer (bounded) before the snapshot.
                while (all_awaiting and prices.get("body_listings") == "prices"
                       and time.monotonic() < render_end):
                    page.wait_for_timeout(PRICE_CHIPS_POLL_MS)
                    html = page.content()
                    all_awaiting = chips_all_awaiting(html)
                title = page.title()
                classification, evidence = classify_page(status, html, title)
                prices = confirm_prices_loaded(prices, html, all_awaiting=all_awaiting)
        elapsed = time.monotonic() - start
        if before_parse is not None:
            before_parse({
                "html": html, "http_status": status, "final_url": page.url,
                **({"condition_prices": prices} if prices is not None else {}),
                # The body is kept as evidence where it decides the outcome: every chip 出品待ち.
                **({"price_chips": chips} if chips and prices.get("dom", "").startswith("all_awaiting")
                   else {}),
            })
        if prices is not None and classification == "normal_page" and prices["status"] != "loaded":
            denied = prices["status"] in {"http_403", "http_429"}
            classification = f"static_{prices['status'][5:]}" if denied else PRICES_NOT_LOADED
            evidence = [f"condition_prices:{prices['status']}"]
        return {
            "final_url": page.url,
            "http_status": status,
            "page_title": title,
            "classification": classification,
            "classification_evidence": evidence,
            "html_bytes": len(html.encode("utf-8")),
            "elapsed_s": round(elapsed, 3),
            "html": html,
            **({"condition_prices": prices} if prices is not None else {}),
        }
    except Exception as exc:  # noqa: BLE001 - record and continue, never crash the run
        elapsed = time.monotonic() - start
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 3)}
    finally:
        if listener is not None:
            try:
                page.remove_listener("response", listener)
            except Exception:  # noqa: BLE001 - a closed page has no listeners left
                pass


def _settle_condition_prices(page: Page, seen: list, status, classification) -> tuple[dict, dict | None]:
    """Wait for this product's size-chips response (only on a normal 200 page: a challenge
    or denial is not waited on), read its body and let the page render it. Returns
    (evidence, {"url", "body"} or None)."""
    if status != 200 or classification != "normal_page":
        return {"status": "page_not_normal"}, None
    product_id = expected_price_product(page.url)
    if product_id is None:
        return {"status": "no_product_id"}, None
    prices, response = wait_for_condition_prices(page, seen, product_id)
    if prices["status"] != "response_200":
        return prices, None
    body, text = read_price_body(response)
    prices.update(body)
    page.wait_for_timeout(PRICE_CHIPS_RENDER_MS)
    return prices, ({"url": response.url, "body": text} if text is not None else None)


def fetch_bytes(page: Page, url: str) -> bytes | None:
    """Fetch raw bytes for an image URL via the browser's own request
    context - reuses the already-established session/IP rather than a
    separate HTTP client. Returns None on any failure (fail closed)."""
    try:
        response = page.context.request.get(url)
        if not response.ok:
            return None
        return response.body()
    except Exception:  # noqa: BLE001
        return None


TURN_TEARDOWN_TIMEOUT_S = 10


class TurnBrowser:
    """One browser and one warmed desktop context reused by a due-work turn.

    The per-capture path launches a browser and captures the homepage (stored
    as RAW, and the source-wide denial canary) for every product. A turn keeps
    the context across attempts: each attempt opens its own page and is
    metered by exactly one bound Attempt through a context-level TurnMeter;
    only an attempt that finds the turn cold captures the homepage, which is
    still stored and still gates that attempt. Any unclean capture discards
    the whole browser, so the next attempt starts as a fresh capture does.
    Schedules, budgets, reservations and pacing are untouched.
    """

    def __init__(self, playwright_factory=None):
        self._playwright_factory = playwright_factory
        self._playwright = None
        self.browser = None
        self.context = None
        self.meter = None
        self.warm = False
        self.launches = 0
        self.warmups = 0

    def ensure(self):
        """The live context, launching one if the turn has none. Call under
        the caller's browser_launch deadline."""
        if self.context is None:
            from app.services.freshness_integration import TurnMeter
            from snkrdunk_collector.config import settings

            if self._playwright is None:
                if self._playwright_factory is None:
                    from playwright.sync_api import sync_playwright

                    self._playwright_factory = sync_playwright
                self._playwright = self._playwright_factory().start()
            self.browser = self._playwright.chromium.launch(
                headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
            )
            self.context = self.browser.new_context(
                user_agent=DESKTOP_CHROME_UA,
                viewport=DESKTOP_VIEWPORT,
                locale="ja-JP",
                extra_http_headers={"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
                service_workers="block",
            )
            self.meter = TurnMeter()
            self.meter.install(self.context)
            self.warm = False
            self.launches += 1
        return self.context

    def discard(self, reason=None):
        """Close everything, innermost first, bounded and quiet."""
        if reason and self._playwright is not None:
            log_event("turn_browser_discarded", reason=reason)
        for label, handle, method in (
            ("context", self.context, "close"),
            ("browser", self.browser, "close"),
            ("playwright", self._playwright, "stop"),
        ):
            if handle is None:
                continue
            try:
                with deadline(TURN_TEARDOWN_TIMEOUT_S, "browser_teardown"):
                    getattr(handle, method)()
            except Exception as exc:
                log_event(
                    "browser_teardown_error",
                    handle=label,
                    error=f"{type(exc).__name__}: {exc}",
                )
        self._playwright = self.browser = self.context = self.meter = None
        self.warm = False

    close = discard
