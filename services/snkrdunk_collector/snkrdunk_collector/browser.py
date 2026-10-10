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

import json
import signal
import time
from contextlib import contextmanager

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


def goto_and_capture(page: Page, url: str, *, before_parse=None) -> dict:
    """One bounded navigation attempt. Returns a dict with either an "error"
    key (navigation-level exception, e.g. DNS/timeout) or the captured
    page state + classification."""
    start = time.monotonic()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        elapsed = time.monotonic() - start
        html = page.content()
        title = page.title()
        status = response.status if response else None
        if before_parse is not None:
            before_parse({"html": html, "http_status": status, "final_url": page.url})
        classification, evidence = classify_page(status, html, title)
        return {
            "final_url": page.url,
            "http_status": status,
            "page_title": title,
            "classification": classification,
            "classification_evidence": evidence,
            "html_bytes": len(html.encode("utf-8")),
            "elapsed_s": round(elapsed, 3),
            "html": html,
        }
    except Exception as exc:  # noqa: BLE001 - record and continue, never crash the run
        elapsed = time.monotonic() - start
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 3)}


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
