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

from known_prints import KNOWN_PRINTS, KnownPrint

HOMEPAGE_URL = "https://snkrdunk.com/"
BRAND_URL = "https://snkrdunk.com/brands/onepiece"
CATEGORY_URL = "https://snkrdunk.com/brands/onepiece/categories/33"

# Discovered from a real category-page "see more" link (run 20260809T091742Z):
# https://snkrdunk.com/search?brandIds=onepiece&searchCategoryIds=6%2F33&keywords=...&sort=popular
# The category page's own default "popular" feed does not reliably surface
# any specific older common-set print, so discovery searches by card code
# directly against this endpoint instead of only harvesting category links.
SEARCH_URL_TEMPLATE = (
    "https://snkrdunk.com/search?brandIds=onepiece&searchCategoryIds=6%2F33"
    "&keywords={query}&sort=new"
)

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

# Section 9/10 fail-closed exclusions. Graded-slab and sealed-product
# mentions on a candidate/product page mean it is not an eligible raw-print
# floor/sale source. Kept as plain Japanese/English substrings, not a
# hardcoded schema - this spike does not yet know SNKRDUNK's exact condition
# taxonomy.
GRADED_KEYWORDS = ["psa", "bgs", "cgc", "ars", "鑑定"]
SEALED_KEYWORDS = ["box", "パック", "未開封", "シュリンク", "カートン"]
SOLD_HISTORY_LINK_KEYWORDS = ["取引履歴", "売却履歴", "販売実績", "取引実績", "sold", "history"]
LOGIN_REQUIRED_MARKERS = ["ログイン", "login", "sign in", "signin"]

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


def candidate_terms(kp: KnownPrint) -> list[str]:
    """Strong deterministic match terms for a known print: its card code,
    the JP name with any parenthetical suffix split off, and the
    parenthetical suffix itself (typically the treatment/rarity word, e.g.
    "パラレル" = parallel)."""
    terms = [kp.card_code]
    base = re.sub(r"[（(].*?[）)]", "", kp.name_jp).strip()
    if base:
        terms.append(base)
    paren_match = re.search(r"[（(](.*?)[）)]", kp.name_jp)
    if paren_match:
        terms.append(paren_match.group(1).strip())
    return [t for t in terms if t]


def score_link_against_print(link: dict[str, str], kp: KnownPrint) -> tuple[int, list[str]]:
    haystack = f"{link.get('text', '')} {link.get('href', '')}"
    matched = [t for t in candidate_terms(kp) if t and t in haystack]
    return len(matched), matched


APPAREL_ID_RE = re.compile(r"/apparels/(\d+)")


def _apparel_id(href: str) -> str | None:
    match = APPAREL_ID_RE.search(href)
    return match.group(1) if match else None


def dedupe_by_product(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Multiple /apparels/{id}/used/{usedId} listings are separate current
    listings of the *same* card, not separate cards - collapse them to one
    candidate per apparel id (preferring the bare /apparels/{id} product
    page, which is the canonical detail page, over an individual /used/
    listing) so ambiguity is judged per distinct card, not per listing."""
    groups: dict[str, list[dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []
    for entry in scored:
        pid = _apparel_id(entry["link"]["href"])
        if pid is None:
            unkeyed.append(entry)
            continue
        groups.setdefault(pid, []).append(entry)

    deduped: list[dict[str, Any]] = []
    for pid, entries in groups.items():
        bare = [e for e in entries if "/used/" not in e["link"]["href"]]
        chosen = bare[0] if bare else entries[0]
        deduped.append(chosen)
    deduped.extend(unkeyed)
    deduped.sort(key=lambda x: -x["score"])
    return deduped


def scored_links_for_print(links: list[dict[str, str]], kp: KnownPrint) -> list[dict[str, Any]]:
    """Links matching >=2 distinct terms for kp (card code alone is too weak
    - SNKRDUNK card codes may not appear verbatim in link text/href), deduped
    per distinct product (see dedupe_by_product), sorted by descending
    score."""
    scored = []
    for link in links:
        score, matched = score_link_against_print(link, kp)
        if score >= 2:
            scored.append({"link": link, "score": score, "matched_terms": matched})
    return dedupe_by_product(scored)


def find_best_match(
    links: list[dict[str, str]],
) -> tuple[KnownPrint | None, dict | None, dict[str, Any]]:
    """Iterate KNOWN_PRINTS in spec section-6 preference order against one
    fixed link set (e.g. the category page). Returns the first print with
    exactly one matching link (unambiguous) plus full diagnostics for every
    print attempted, so a failure to match is still fully explained."""
    diagnostics: dict[str, Any] = {"attempts": []}
    for kp in KNOWN_PRINTS:
        scored = scored_links_for_print(links, kp)
        diagnostics["attempts"].append(
            {
                "card_print_id": kp.card_print_id,
                "card_code": kp.card_code,
                "terms": candidate_terms(kp),
                "candidate_count": len(scored),
                "candidates": scored[:5],
            }
        )
        if len(scored) == 1:
            return kp, scored[0]["link"], diagnostics
        # Ambiguous (>1) or none: fail closed for this print, try the next
        # preference per spec section 6/7.
    return None, None, diagnostics


def build_search_url(query: str) -> str:
    from urllib.parse import quote

    return SEARCH_URL_TEMPLATE.format(query=quote(query))


def find_embedded_json_blocks(html: str) -> dict[str, Any]:
    """Deterministic scan for common SPA/framework data-embedding patterns.
    Section 8: determine current SNKRDUNK data model without assuming older
    implementation details. Returns presence flags and, where safely
    parseable, the parsed JSON - never executes any script content."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "next_data_present": False,
        "next_data_top_level_keys": [],
        "ld_json_blocks": [],
        "other_json_script_ids": [],
    }

    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        result["next_data_present"] = True
        try:
            parsed = json.loads(next_data_tag.string)
            if isinstance(parsed, dict):
                result["next_data_top_level_keys"] = list(parsed.keys())
        except json.JSONDecodeError:
            result["next_data_top_level_keys"] = ["<unparseable>"]

    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            parsed = json.loads(tag.string)
            block_type = parsed.get("@type") if isinstance(parsed, dict) else None
            result["ld_json_blocks"].append({"type": block_type, "raw": parsed})
        except json.JSONDecodeError:
            result["ld_json_blocks"].append({"type": None, "raw": None, "parse_error": True})

    for tag in soup.find_all("script", id=True, type="application/json"):
        if tag.get("id") != "__NEXT_DATA__":
            result["other_json_script_ids"].append(tag["id"])

    return result


PRICE_RE = re.compile(r"¥\s?([\d,]{2,})")


def extract_price_mentions(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    values = []
    for match in PRICE_RE.finditer(text):
        try:
            values.append(int(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def extract_product_page(html: str, url: str) -> dict[str, Any]:
    """Deterministic, offline-testable extractor for a single already-fetched
    product page. Structure mirrors spec section 12: identity / floor /
    sales / evidence. Never guesses - fields are None/empty when not found,
    and diagnostics record what was/wasn't detected so a feasibility
    decision can be made from real evidence, not assumption."""
    soup = BeautifulSoup(html, "html.parser")
    text_lower = soup.get_text(" ", strip=True).lower()

    title = soup.title.get_text(strip=True) if soup.title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    og_image = soup.find("meta", property="og:image")
    image_url = og_image["content"] if og_image and og_image.has_attr("content") else None

    embedded = find_embedded_json_blocks(html)
    prices = extract_price_mentions(html)

    is_graded = any(kw in text_lower for kw in GRADED_KEYWORDS)
    is_sealed = any(kw in text_lower for kw in SEALED_KEYWORDS)
    login_required_markers_present = any(kw in text_lower for kw in LOGIN_REQUIRED_MARKERS)

    sold_history_links = []
    for a in soup.find_all("a", href=True):
        link_text = a.get_text(" ", strip=True)
        if any(kw in link_text or kw in a["href"] for kw in SOLD_HISTORY_LINK_KEYWORDS):
            sold_history_links.append({"href": a["href"], "text": link_text[:120]})

    return {
        "identity": {
            "title": title,
            "h1": h1_text,
            "image_url": image_url,
            "product_url": url,
        },
        "floor": {
            "raw_floor_jpy": None,  # not populated in this offline pass -
            # requires knowing which of `price_mentions` (if any) is the
            # authoritative current listing price vs. a reference/MSRP/other
            "price_mentions_jpy": sorted(set(prices)),
            "listing_count": None,
            "conditions_represented": [],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        "sales": {
            "sold_history_publicly_visible": bool(sold_history_links),
            "sold_history_candidate_links": sold_history_links[:10],
            "observations": [],
        },
        "evidence": {
            "final_url": url,
            "next_data_present": embedded["next_data_present"],
            "next_data_top_level_keys": embedded["next_data_top_level_keys"],
            "ld_json_block_types": [b.get("type") for b in embedded["ld_json_blocks"]],
            "other_json_script_ids": embedded["other_json_script_ids"],
            "parser_version": "snkrdunk-spike-extractor-v1",
        },
        "flags": {
            "is_graded": is_graded,
            "is_sealed": is_sealed,
            "login_required_markers_present": login_required_markers_present,
        },
    }


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


def run_discover_extract_stage(page: Page, out_dir: Path) -> dict[str, Any]:
    """Section 6-12: given the category page is already loaded, harvest its
    link surface, find an unambiguous match against KNOWN_PRINTS (spec
    preference order). The category page's default "popular" feed may not
    surface an older common-set print at all, so if no unambiguous category
    match exists, fall back to SNKRDUNK's own /search endpoint (discovered
    from a real "see more" link), querying by each known print's card code
    in preference order until an unambiguous match is found. Once matched,
    navigate to the product once and run the deterministic offline
    extractor against the rendered page."""
    result: dict[str, Any] = {}

    links = extract_links(page)
    result["category_links_count"] = len(links)
    result["category_links"] = links  # small enough (~100s) to log in full

    matched_print, matched_link, diagnostics = find_best_match(links)
    result["match_diagnostics"] = diagnostics
    result["match_source"] = "category_page" if matched_print else None

    if matched_print is None:
        result["search_attempts"] = []
        for kp in KNOWN_PRINTS:
            search_url = build_search_url(kp.card_code)
            nav = navigate_and_capture(page, search_url, f"03_search_{kp.card_code}", out_dir)
            log(
                "search_navigate_result",
                card_code=kp.card_code,
                search_url=search_url,
                classification=nav.classification,
                http_status=nav.http_status,
            )
            attempt: dict[str, Any] = {
                "card_code": kp.card_code,
                "search_url": search_url,
                "nav_classification": nav.classification,
            }
            if nav.classification == "normal_page":
                search_links = extract_links(page)
                scored = scored_links_for_print(search_links, kp)
                attempt["candidate_count"] = len(scored)
                attempt["candidates"] = scored[:5]
                if len(scored) == 1:
                    matched_print = kp
                    matched_link = scored[0]["link"]
                    result["match_source"] = f"search:{kp.card_code}"
                    result["search_attempts"].append(attempt)
                    break
            result["search_attempts"].append(attempt)

    if matched_print is None or matched_link is None:
        result["matched"] = False
        log("discover_no_unambiguous_match")
        return result

    from urllib.parse import urljoin

    product_url = urljoin(page.url, matched_link["href"])
    result["matched"] = True
    result["matched_print"] = {
        "card_print_id": matched_print.card_print_id,
        "card_code": matched_print.card_code,
        "name_jp": matched_print.name_jp,
    }
    result["matched_link"] = matched_link
    result["product_url"] = product_url

    result.update(navigate_and_extract(page, out_dir, product_url, matched_print))
    return result


def navigate_and_extract(
    page: Page, out_dir: Path, product_url: str, known_print: KnownPrint
) -> dict[str, Any]:
    """Navigate to product_url once and run the deterministic offline
    extractor + section-7 offline verification against known_print. Shared
    by both the search-discovered path and a direct --product-url run."""
    result: dict[str, Any] = {}
    log(
        "product_target",
        card_print_id=known_print.card_print_id,
        card_code=known_print.card_code,
        product_url=product_url,
    )

    nav_result = navigate_and_capture(page, product_url, "03_product", out_dir)
    result["product_nav"] = asdict(nav_result)
    log(
        "product_navigate_result",
        classification=nav_result.classification,
        http_status=nav_result.http_status,
        evidence=nav_result.evidence,
    )

    if nav_result.classification != "normal_page":
        result["extraction"] = None
        return result

    html = page.content()
    extraction = extract_product_page(html, nav_result.final_url)

    # Offline exact-print verification (section 7): fail closed on any
    # artwork/language/treatment mismatch signal we can check without a
    # human eye on the two images. We can only check what's programmatically
    # available here (title/h1 text against the known JP name and treatment
    # term); a true pixel/artwork comparison is a human/manual step noted in
    # the final report, not automated by this spike.
    identity_text = f"{extraction['identity']['title']} {extraction['identity']['h1']}"
    verification_terms = candidate_terms(known_print)
    verification_hits = [t for t in verification_terms if t in identity_text]
    extraction["verification"] = {
        "known_print_card_code": known_print.card_code,
        "known_print_name_jp": known_print.name_jp,
        "terms_checked": verification_terms,
        "terms_confirmed_on_product_page": verification_hits,
        "all_terms_confirmed": len(verification_hits) == len(verification_terms),
        "fail_closed_reasons": []
        + (["graded_slab_markers_present"] if extraction["flags"]["is_graded"] else [])
        + (["sealed_product_markers_present"] if extraction["flags"]["is_sealed"] else [])
        + (
            ["not_all_identity_terms_confirmed"]
            if len(verification_hits) != len(verification_terms)
            else []
        ),
    }

    result["extraction"] = extraction

    (out_dir / "extracted.json").write_text(
        json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        "extraction_complete",
        raw_floor_jpy=extraction["floor"]["raw_floor_jpy"],
        price_mentions_count=len(extraction["floor"]["price_mentions_jpy"]),
        sold_history_publicly_visible=extraction["sales"]["sold_history_publicly_visible"],
        verification_all_confirmed=extraction["verification"]["all_terms_confirmed"],
        fail_closed_reasons=extraction["verification"]["fail_closed_reasons"],
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["access", "full"],
        default="access",
        help="access = the section-5 3-URL access test only. full = access, "
        "then (if the category page loaded normally) discover + extract "
        "against a KNOWN_PRINTS match, all in one bounded session.",
    )
    parser.add_argument(
        "--product-url",
        default=None,
        help="If set with --stage full, skip category-link/search discovery "
        "entirely and extract directly from this product URL. Used once a "
        "prior discover run's diagnostics already identified a specific "
        "well-reasoned candidate (e.g. distinguishing the original-booster "
        "Japanese listing from same-card-code anniversary/promo/English "
        "reprints that also matched by card code alone) - avoids repeating "
        "the same search requests.",
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

                    category_ok = bool(access_results) and access_results[-1].classification == "normal_page" and access_results[-1].url == CATEGORY_URL
                    if args.stage == "full" and category_ok and args.product_url:
                        # A prior discover run's diagnostics already
                        # identified this well-reasoned candidate - skip
                        # repeating the category/search requests.
                        known_print = KNOWN_PRINTS[0]
                        de: dict[str, Any] = {
                            "matched": True,
                            "match_source": "direct_product_url_from_prior_run_diagnostics",
                            "matched_print": {
                                "card_print_id": known_print.card_print_id,
                                "card_code": known_print.card_code,
                                "name_jp": known_print.name_jp,
                            },
                            "product_url": args.product_url,
                        }
                        de.update(navigate_and_extract(page, out_dir, args.product_url, known_print))
                        summary["discover_extract"] = de
                    elif args.stage == "full" and category_ok:
                        summary["discover_extract"] = run_discover_extract_stage(page, out_dir)
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
