"""Standalone feasibility spike: can an ordinary Playwright Chromium session,
run from a Railway container, reach SNKRDUNK's public ONE PIECE pages and
extract exact-print raw-market data for one of our 20 already-verified
`card_prints`?

Isolated from the application - no imports from services/*, no database
writes, no deployment of application code. Deterministic extraction only
(regex/DOM/embedded-JSON parsing) - no AI model calls. Historical SNKRDUNK
discovery/matching code under services/worker/worker/ is NOT imported or
relied on here; this spike verifies current site structure independently.

Rules honored: no stealth plugins, no fingerprint spoofing, no proxy
rotation, no CAPTCHA solving, no repeated retries after 403/429, no sign-in,
one bounded navigation attempt per URL, hard total-run watchdog.

Stages (run via --stage):
  access    - navigate the three public entry points in order, classify each,
              save evidence. Stops immediately after the first blocked/
              challenged response.
  discover  - (only meaningful after `access` succeeds) search/browse for a
              product matching one of KNOWN_PRINTS and save candidate
              evidence. Does not write a source mapping.
  extract   - given a matched product URL, run the deterministic extractor
              (identity/floor/sales/evidence) against the rendered page.
  full      - access -> discover -> extract in one bounded session (the mode
              the Railway service actually runs).
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

HOMEPAGE_URL = "https://snkrdunk.com/"
BRAND_URL = "https://snkrdunk.com/brands/onepiece"
CATEGORY_URL = "https://snkrdunk.com/brands/onepiece/categories/33"

DESKTOP_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
DESKTOP_ACCEPT_LANGUAGE = "ja-JP,ja;q=0.9,en;q=0.8"
DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

# Strong evidence: known denial/challenge page *titles*.
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

# Strong evidence: specific challenge-page body phrasing, not a bare vendor
# name (which can appear incidentally, e.g. Cloudflare as a normal CDN).
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

TOTAL_RUN_BUDGET_SECONDS = 300
PER_STEP_BUDGET_SECONDS = 45


class DeadlineExceeded(Exception):
    """Raised when a deadline() budget elapses. Unix-only (signal.alarm)."""


_deadline_stack: list[tuple[float, str]] = []


def _deadline_signal_handler(signum, frame) -> None:
    label = _deadline_stack[-1][1] if _deadline_stack else "deadline"
    raise DeadlineExceeded(label)


def _rearm_alarm() -> None:
    if not _deadline_stack:
        signal.alarm(0)
        return
    remaining = max(1, int(_deadline_stack[-1][0] - time.monotonic()))
    signal.alarm(remaining)


@contextmanager
def deadline(seconds: float, label: str):
    signal.signal(signal.SIGALRM, _deadline_signal_handler)
    _deadline_stack.append((time.monotonic() + seconds, label))
    _rearm_alarm()
    try:
        yield
    finally:
        _deadline_stack.pop()
        _rearm_alarm()


def log(event: str, **fields: Any) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    print(json.dumps(record, ensure_ascii=False), flush=True)


@dataclass
class NavResult:
    url: str
    final_url: str = ""
    http_status: int | None = None
    title: str = ""
    body_length: int = 0
    classification: str = "error"
    evidence: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None


def classify_page(status: int | None, title: str, html: str) -> tuple[str, list[str]]:
    """Deterministic classification. Returns (classification, evidence).

    Classifications: normal_page, static_403, static_429, challenge_or_captcha,
    error.
    """
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
        # Short body + only weak markers: plausibly a denial page that didn't
        # match a strong signature. Flag but don't hard-classify as denial.
        return "error", [f"weak_marker:{m}" for m in weak_hits] + ["short_body"]

    return "normal_page", []


def navigate_and_capture(page: Page, url: str, name: str, out_dir: Path) -> NavResult:
    result = NavResult(url=url)
    start = time.monotonic()
    try:
        with deadline(PER_STEP_BUDGET_SECONDS, f"nav:{name}"):
            response = page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            result.http_status = response.status if response else None
            result.final_url = page.url
            result.title = page.title()
            html = page.content()
            result.body_length = len(html)

            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{name}.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(out_dir / f"{name}.png"), full_page=False)

            classification, evidence = classify_page(result.http_status, result.title, html)
            result.classification = classification
            result.evidence = evidence
    except DeadlineExceeded as exc:
        result.classification = "error"
        result.error = f"deadline_exceeded:{exc}"
    except Exception as exc:  # noqa: BLE001 - record and continue, never crash the run
        result.classification = "error"
        result.error = f"{type(exc).__name__}:{exc}"
    finally:
        result.elapsed_seconds = round(time.monotonic() - start, 3)
    return result


def extract_links(page: Page) -> list[dict[str, str]]:
    """Deterministic anchor-tag harvest: href + visible text for every <a>
    on the current page. Used for offline discovery-surface inspection, not
    an extraction of market data."""
    soup = BeautifulSoup(page.content(), "html.parser")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href in seen:
            continue
        seen.add(href)
        text = " ".join(a.get_text(" ", strip=True).split())
        links.append({"href": href, "text": text[:120]})
    return links


def run_access_stage(page: Page, out_dir: Path) -> list[NavResult]:
    urls = [
        (HOMEPAGE_URL, "00_homepage"),
        (BRAND_URL, "01_brand_onepiece"),
        (CATEGORY_URL, "02_category_33"),
    ]
    results: list[NavResult] = []
    for url, name in urls:
        log("navigate_start", url=url, name=name)
        result = navigate_and_capture(page, url, name, out_dir)
        log(
            "navigate_result",
            url=result.url,
            final_url=result.final_url,
            http_status=result.http_status,
            title=result.title,
            body_length=result.body_length,
            classification=result.classification,
            evidence=result.evidence,
            elapsed_seconds=result.elapsed_seconds,
            error=result.error,
        )
        results.append(result)

        if result.classification in ("static_403", "static_429", "challenge_or_captcha"):
            log("access_stage_stopped", reason=result.classification, at=name)
            break
        if result.classification == "error":
            log("access_stage_stopped", reason="error", at=name, detail=result.error)
            break

        # Category page: also harvest the link surface for discovery.
        if name == "02_category_33":
            links = extract_links(page)
            (out_dir / "02_category_33_links.json").write_text(
                json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log("category_links_captured", count=len(links))

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["access", "full"],
        default="access",
        help="access = the section-5 3-URL access test only. full = access "
        "stage today; discover/extract stages are added once real site "
        "structure is known from an access-stage run.",
    )
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = OUTPUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    log("run_start", stage=args.stage, run_id=run_id)
    overall_start = time.monotonic()

    summary: dict[str, Any] = {"run_id": run_id, "stage": args.stage}

    try:
        with deadline(TOTAL_RUN_BUDGET_SECONDS, "total_run"):
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=DESKTOP_CHROME_UA,
                    viewport=DESKTOP_VIEWPORT,
                    locale="ja-JP",
                    extra_http_headers={"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                page = context.new_page()

                try:
                    access_results = run_access_stage(page, out_dir)
                    summary["access_results"] = [asdict(r) for r in access_results]
                finally:
                    context.tracing.stop(path=str(out_dir / "trace.zip"))
                    context.close()
                    browser.close()
    except DeadlineExceeded as exc:
        summary["fatal_error"] = f"deadline_exceeded:{exc}"
        log("run_deadline_exceeded", detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        summary["fatal_error"] = f"{type(exc).__name__}:{exc}"
        log("run_fatal_error", detail=str(exc))

    summary["total_elapsed_seconds"] = round(time.monotonic() - overall_start, 3)
    (out_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log("run_complete", **{k: v for k, v in summary.items() if k != "access_results"})
    # Also print the full summary as one compact JSON line so it can be
    # recovered from Railway logs even without volume access.
    print("RESULT_JSON=" + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
