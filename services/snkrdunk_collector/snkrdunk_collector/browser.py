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


def goto_and_capture(page: Page, url: str) -> dict:
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
