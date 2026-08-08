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


def capture(page: Page, response, elapsed_s: float, expected_markers: list[str] | None = None) -> dict:
    title = page.title()
    html = page.content()
    status = response.status if response else None
    html_bytes = len(html.encode("utf-8"))
    cls, evidence = classify_page(status, html, title, expected_markers)

    return {
        "final_url": page.url,
        "http_status": status,
        "navigation_ok": bool(response and response.ok),
        "page_title": title,
        "classification": cls,
        "classification_evidence": evidence,
        "html_bytes": html_bytes,
        "elapsed_s": round(elapsed_s, 3),
        "html": html,
    }


def goto_and_capture(page: Page, url: str, expected_markers: list[str] | None = None) -> dict:
    start = time.monotonic()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        elapsed = time.monotonic() - start
        return capture(page, resp, elapsed, expected_markers)
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 3)}


def _write_json_artifact(path: Path, data: dict) -> dict:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size}
