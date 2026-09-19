"""Zero-write Yuyu-Tei homepage diagnostic.

This module deliberately has no database, model, writer, telemetry, batch,
collector, or discovery imports.  It makes one non-redirecting stdlib HTTP
request and one Playwright navigation through the collector's existing
homepage warm-up helper, then prints only allowlisted metadata.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable

from playwright.sync_api import sync_playwright

from yuyutei_collector.browser import (
    HOMEPAGE_EXPECTED_MARKERS,
    HOMEPAGE_URL,
    classify_capture,
    deadline,
    warm_up_homepage,
)
from yuyutei_collector.config import settings

PROBE_VERSION = 1
HTTP_TIMEOUT_S = 20
MAX_CLASSIFICATION_BYTES = 128 * 1024

# Cookies and request-identifying values are intentionally absent.  Header
# lookup is case-insensitive, and output keys are normalized to lowercase.
DIAGNOSTIC_RESPONSE_HEADERS = (
    "server",
    "content-type",
    "content-length",
    "location",
    "retry-after",
    "via",
    "cf-ray",
    "cf-cache-status",
    "cf-mitigated",
    "x-cache",
    "x-sucuri-id",
    "x-sucuri-cache",
    "x-akamai-transformed",
    "akamai-grn",
)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    def title(self) -> str:
        return " ".join("".join(self._parts).split())[:200]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Record a redirect response but never issue the follow-up request."""

    def __init__(self) -> None:
        super().__init__()
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        return None


def _safe_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in DIAGNOSTIC_RESPONSE_HEADERS:
        value = headers.get(name) if headers is not None else None
        if value is not None:
            result[name] = str(value)[:500]
    return result


def _decode_body(body: bytes, headers: Any) -> str:
    charset = None
    if headers is not None and hasattr(headers, "get_content_charset"):
        charset = headers.get_content_charset()
    return body.decode(charset or "utf-8", errors="replace")


def _page_title(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html)
    return parser.title()


def _error_name(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    if reason is not None:
        return f"{type(exc).__name__}: {type(reason).__name__}"
    return type(exc).__name__


def run_simple_http(*, opener: Any | None = None) -> dict[str, Any]:
    """Make exactly one bounded homepage request and return safe metadata.

    Redirect following is disabled so one call cannot silently become several
    network requests.  At most ``MAX_CLASSIFICATION_BYTES`` are retained in
    memory, solely for title/challenge classification, and are never returned.
    """

    redirect_handler = _NoRedirectHandler()
    http = opener or urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(HOMEPAGE_URL, method="GET")

    response = None
    try:
        with deadline(HTTP_TIMEOUT_S, "simple_http_request"):
            try:
                response = http.open(request, timeout=HTTP_TIMEOUT_S)
            except urllib.error.HTTPError as exc:
                # HTTPError is also the bounded response stream for 3xx/4xx/5xx.
                response = exc

            status = response.getcode()
            final_url = response.geturl()
            headers = response.headers
            body = response.read(MAX_CLASSIFICATION_BYTES)
        html = _decode_body(body, headers)
        classified = classify_capture(
            {
                "http_status": status,
                "html": html,
                "page_title": _page_title(html),
            },
            HOMEPAGE_EXPECTED_MARKERS,
        )
        return {
            "status": status,
            "final_url": final_url,
            "redirect_count": redirect_handler.redirect_count,
            "headers": _safe_headers(headers),
            "classification": classified.get("classification"),
            "classification_evidence": classified.get("classification_evidence", []),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": None,
            "final_url": HOMEPAGE_URL,
            "redirect_count": redirect_handler.redirect_count,
            "headers": {},
            "classification": "navigation_error",
            "classification_evidence": [],
            "error": _error_name(exc),
        }
    finally:
        if response is not None:
            response.close()


def run_playwright(
    *,
    playwright_factory: Callable[[], Any] = sync_playwright,
    homepage_runner: Callable[[Any], dict[str, Any]] = warm_up_homepage,
) -> dict[str, Any]:
    """Navigate once with the collector's browser/context/warm-up behavior."""

    browser = None
    context = None
    page = None
    try:
        with playwright_factory() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=True,
                    timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000,
                )
                context = browser.new_context()
                page = context.new_page()
                step = homepage_runner(page)
                error = step.get("error")
                return {
                    "status": step.get("http_status"),
                    "final_url": step.get("final_url") or HOMEPAGE_URL,
                    "title": str(step.get("page_title") or "")[:200],
                    "classification": step.get("classification")
                    or ("navigation_error" if error else None),
                    "classification_evidence": step.get("classification_evidence", []),
                    "error": error,
                }
            finally:
                for label, handle in (
                    ("probe_page_close", page),
                    ("probe_context_close", context),
                    ("probe_browser_close", browser),
                ):
                    if handle is not None:
                        try:
                            with deadline(settings.BROWSER_TEARDOWN_TIMEOUT_S, label):
                                handle.close()
                        except Exception:
                            pass
    except Exception as exc:
        return {
            "status": None,
            "final_url": HOMEPAGE_URL,
            "title": "",
            "classification": "navigation_error",
            "classification_evidence": [],
            "error": _error_name(exc),
        }


def build_result(
    *,
    simple_probe: Callable[[], dict[str, Any]] | None = None,
    playwright_probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    simple_probe = simple_probe or run_simple_http
    playwright_probe = playwright_probe or run_playwright
    return {
        "probe_version": PROBE_VERSION,
        "target": "yuyutei_homepage",
        "simple_http": simple_probe(),
        "playwright": playwright_probe(),
        "writes_possible": False,
    }


def main() -> None:
    print(json.dumps(build_result(), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
