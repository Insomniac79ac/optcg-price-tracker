"""Playwright navigation, bounded wall-clock deadlines, and compact JSON
logging - moved out of spikes/yuyutei-browser-feasibility/spike.py
(deadline(), goto_and_capture(), capture(), log_event() were live-validated
there via run_single_live_validation). No proxy rotation, no CAPTCHA-solving
service, no fingerprint spoofing beyond supported Playwright context
options, no attempt to bypass a rendered challenge/denial page, one normal
navigation attempt per URL per run - no retries after 403/429/challenge.
"""

import json
import signal
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page

from yuyutei_collector.config import settings
from yuyutei_collector.extractor import classify_page

HOMEPAGE_URL = "https://yuyu-tei.jp/"
HOMEPAGE_EXPECTED_MARKERS = ["遊々亭"]


def log_event(event: str, **fields) -> None:
    """Every collector stdout line is exactly one minified JSON object -
    never a pretty-printed multi-line dump (a single indent=2 dump of a
    full run's result previously exceeded Railway's log ingestion rate cap
    in the spike this was moved from)."""
    print(json.dumps({"event": event, **fields}, separators=(",", ":"), ensure_ascii=False))


class DeadlineExceeded(Exception):
    """Raised by deadline() when its wall-clock budget elapses. Unix-only
    (uses signal.alarm, main-thread only) - correct for this service's
    single Railway Linux container target, not intended to be portable."""


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
    deadline always wins. Raises DeadlineExceeded(label) if the block does
    not finish in time, even if it is stuck inside a call with no timeout
    parameter of its own: signal.alarm interrupts at the OS level rather
    than relying on the blocked call to cooperate."""
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


def capture_response(page: Page, response, elapsed_s: float) -> dict:
    """Read the response metadata and body without interpreting either.

    Collection uses this lower-level boundary so durable raw evidence can be
    committed before page classification or product parsing.  Callers that do
    not persist raw evidence (for example discovery) continue to use
    :func:`goto_and_capture`, which composes this with ``classify_capture`` and
    therefore keeps its existing result shape and behaviour.
    """
    title = page.title()
    html = page.content()
    status = response.status if response else None
    html_bytes = len(html.encode("utf-8"))

    return {
        "final_url": page.url,
        "http_status": status,
        "navigation_ok": bool(response and response.ok),
        "page_title": title,
        "html_bytes": html_bytes,
        "elapsed_s": round(elapsed_s, 3),
        "html": html,
    }


def classify_capture(step: dict, expected_markers: list[str] | None = None) -> dict:
    """Add the established page classification to an uninterpreted capture."""
    if "error" in step:
        return step
    cls, evidence = classify_page(
        step.get("http_status"),
        step["html"],
        step.get("page_title") or "",
        expected_markers,
    )
    return {
        **step,
        "classification": cls,
        "classification_evidence": evidence,
    }


def capture(page: Page, response, elapsed_s: float, expected_markers: list[str] | None = None) -> dict:
    """Backward-compatible capture-and-classify helper."""
    return classify_capture(capture_response(page, response, elapsed_s), expected_markers)


def goto_and_capture_raw(page: Page, url: str) -> dict:
    """Navigate once and return a body capture before page classification."""
    start = time.monotonic()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        elapsed = time.monotonic() - start
        return capture_response(page, resp, elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 3)}


def goto_and_capture(page: Page, url: str, expected_markers: list[str] | None = None) -> dict:
    return classify_capture(goto_and_capture_raw(page, url), expected_markers)


def homepage_session_ok(step: dict) -> bool:
    """Did the warm-up establish a usable session?

    Extracted from collect.py, which has gated on exactly these three
    conditions since the collector shipped, so that discovery can ask the same
    question without restating the expression. All three matter and none is
    redundant: `error` catches a navigation that never produced a response,
    the status check refuses anything that is not a plain 200, and the
    classification check is what rejects a rendered challenge page served WITH
    a 200 - the case a status check alone cannot see.
    """
    return (
        "error" not in step
        and step.get("http_status") == 200
        and step.get("classification") == "normal_product"
    )


def warm_up_homepage(page: Page) -> dict:
    """Navigate the homepage once, on the CALLER'S OWN page, and return the
    capture.

    WHY EVERY CALLER MUST DO THIS FIRST. Measured on Railway staging
    2026-09-02: a cold navigation straight to a listing URL was answered 403,
    while the same egress minutes earlier reached the homepage and then three
    listing pages with 200 apiece. The warm-up is therefore not decoration -
    it is what makes the following navigation a continuation of a session
    rather than an unheralded deep hit.

    THE PAGE IS THE CALLER'S ON PURPOSE. Whatever session state the homepage
    establishes lives in the BrowserContext behind that page, so warming a
    second context would leave the real navigation exactly as cold as before.
    This function must never create one.

    Posture is unchanged from the collector: one navigation, one wall-clock
    deadline, no retry, no headers, no cookies, no timing variation. It does
    not decide anything - `homepage_session_ok` judges the result and the
    caller chooses what a failure means for it.
    """
    with deadline(settings.HOMEPAGE_NAV_TIMEOUT_S, "homepage_navigation"):
        return goto_and_capture(page, HOMEPAGE_URL, HOMEPAGE_EXPECTED_MARKERS)


def _write_json_artifact(path: Path, data: dict) -> dict:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size}


class TurnBrowser:
    """One browser and one warmed context reused by a due-work turn.

    Today's per-capture path launches a browser, warms the homepage and
    throws both away for every product. A turn keeps the context (and so the
    session the homepage established) across attempts: each attempt opens its
    own page, is metered by exactly one bound Attempt through a single
    context-level TurnMeter, and only an attempt that finds the turn cold pays
    for a warm-up. Any failure discards the whole browser, so the next
    attempt starts exactly as a fresh capture does today. Schedules, budgets,
    reservations and pacing are untouched; there is simply less to request.
    """

    def __init__(self, playwright_factory=None, context_options=None):
        self._playwright_factory = playwright_factory
        self._context_options = dict(context_options or {})
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

            if self._playwright is None:
                if self._playwright_factory is None:
                    from playwright.sync_api import sync_playwright

                    self._playwright_factory = sync_playwright
                self._playwright = self._playwright_factory().start()
            self.browser = self._playwright.chromium.launch(
                headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
            )
            self.context = self.browser.new_context(
                service_workers="block", **self._context_options
            )
            self.meter = TurnMeter()
            self.meter.install(self.context)
            self.warm = False
            self.launches += 1
        return self.context

    def discard(self, reason=None):
        """Close everything, innermost first, bounded and quiet. The next
        attempt relaunches and warms up from scratch."""
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
                with deadline(settings.BROWSER_TEARDOWN_TIMEOUT_S, "browser_teardown"):
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
