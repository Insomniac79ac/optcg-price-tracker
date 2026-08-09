"""Standalone feasibility spike: can an ordinary Playwright Chromium session,
run from a Railway container, reach SNKRDUNK's public ONE PIECE pages and
extract exact-print raw-market data for one of our verified `card_prints`?

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
  full      - access -> discover (category/search) or direct --product-url ->
              extract, all in one bounded session (the mode the Railway
              service actually runs).

Extraction pipeline (--stage full), per product:
  1. Parse identity (card_code/rarity/treatment) from the rendered title,
     generically handling the site's "<rarity>-P" parallel-print convention.
  2. Verify the product's own primary image against the known official
     Bandai artwork for the target card_print (perceptual hash + aspect
     ratio), accounting for the site's background-removed product photos.
  3. Extract the product's own raw condition (A/B/C/D) prices from its
     condition-chip picker, scoped to that DOM container only - never a
     whole-page price regex, never graded (PSA/BGS/ARS/...) chips, never
     recommendation-carousel prices.
  4. Follow the page's own "state-scoped market list" link (normal public
     UI) to the product's sales-history page and extract up to the latest
     10 raw (non-graded) sold transactions, if publicly visible.
  5. Parse embedded JSON-LD (object/array/@graph-wrapped) as corroborating
     evidence only - never allowed to override the scoped raw-condition
     table.
"""

from __future__ import annotations

import argparse
import io
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
from bs4.element import Tag
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

LOGIN_REQUIRED_MARKERS = ["ログイン", "login", "sign in", "signin"]

# Section-3/8 raw vs. graded condition taxonomy, confirmed against the live
# product's own condition-chip picker (2026-08-09, apparels/104428): exactly
# these 4 labels are raw; everything else in that same picker (PSA*, BGS*,
# ARS*, 他鑑定品) is a graded-slab category and must never be treated as raw.
RAW_CONDITION_LABELS = ("A", "B", "C", "D")

AWAITING_LISTING_TEXT = "出品待ち"

# Links to the product's own sold/market-history page use this visible
# phrasing on the live site ("see the market price list by condition"),
# confirmed via a real Playwright session following the product page's own
# link (normal UI click, no login, no private endpoint guessing).
SOLD_HISTORY_LINK_KEYWORDS = [
    "状態ごとの相場一覧",
    "売買履歴",
    "取引履歴",
    "売却履歴",
    "販売実績",
    "取引実績",
    "sales-histories",
    "sold",
    "history",
]

TOTAL_RUN_BUDGET_SECONDS = 300
PER_STEP_BUDGET_SECONDS = 45

PARSER_VERSION = "snkrdunk-spike-extractor-v2"


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
    """Strong deterministic match terms for a known print: its card code and
    its JP name (with any parenthetical suffix, e.g. a treatment note, split
    off as its own term when present)."""
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
    """Iterate KNOWN_PRINTS in preference order against one fixed link set
    (e.g. the category page). Returns the first print with exactly one
    matching link (unambiguous) plus full diagnostics for every print
    attempted, so a failure to match is still fully explained."""
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
        # preference.
    return None, None, diagnostics


def build_search_url(query: str) -> str:
    from urllib.parse import quote

    return SEARCH_URL_TEMPLATE.format(query=quote(query))


# ---------------------------------------------------------------------------
# Section 2: generic "<rarity>-P" parallel-treatment identity parser.
# ---------------------------------------------------------------------------

# Card codes as they appear in a title's own "[...]" bracket. Observed live
# forms: "OP01-001", "ST29-008", "PRB02-006", "EB03-054", "P-159" - a
# letters(+digits) set prefix, a dash, then a 2-3 digit number.
CARD_CODE_IN_TITLE_RE = re.compile(r"\[([A-Z]{1,4}\d{0,2}-\d{2,3})\]")

# The rarity-token itself, scoped to the run of text between the card name
# and the "[card_code]" bracket (never searched blindly across the whole
# title/page) - see parse_card_identity. "<rarity>-P" is the site's generic
# parallel-print marker, confirmed live across multiple rarities (L-P, R-P,
# SR-P, SEC-P all observed for different cards on 2026-08-09). This must NOT
# match a bare "P" (the standalone Promo rarity - no dash) or a superficially
# similar-looking suffix like "-RSP" (a distinct "red comic parallel" marker
# seen live on OP13-118) - anchoring the regex to the full token boundaries
# (^...$) rather than a substring search rules both out.
RARITY_PARALLEL_TOKEN_RE = re.compile(r"^([A-Z]{1,4})-P$")

# A bare (non-parallel) rarity token: letters/digits only, no separators.
BARE_RARITY_TOKEN_RE = re.compile(r"^[A-Z0-9]{1,4}$")


def parse_card_identity(title: str) -> dict[str, str | None]:
    """Generic parser for SNKRDUNK's card-title rarity/treatment convention.

    Titles look like "<name> <rarity token> [<card_code>] (<release>)...".
    The rarity token is whatever whitespace-delimited run of text
    immediately precedes the "[card_code]" bracket (skipping any trailing
    ":"-prefixed descriptor tokens, e.g. "L :開封済", which sit between the
    rarity token and the bracket for some listings). "<RARITY>-P" means
    parallel treatment; a bare rarity token means normal treatment. Text
    anywhere else in the title (after the bracket, e.g. a set/box name) is
    never considered - this deliberately does not "interpret every -P
    string blindly".

    Returns {"card_code": ..., "rarity": ..., "treatment": ...}, all None if
    the title doesn't contain a recognizable "[card_code]" bracket at all
    (malformed/unexpected title - fail closed, never guess).
    """
    code_match = CARD_CODE_IN_TITLE_RE.search(title or "")
    if not code_match:
        return {"card_code": None, "rarity": None, "treatment": None}

    card_code = code_match.group(1)
    prefix = title[: code_match.start()].strip()
    tokens = [t for t in prefix.split() if t]

    # Skip trailing ":"-prefixed descriptor tokens (e.g. "開封済", "通常版")
    # that some listings insert between the rarity token and the bracket.
    while tokens and (tokens[-1].startswith(":") or tokens[-1].startswith("：")):
        tokens.pop()

    if not tokens:
        return {"card_code": card_code, "rarity": None, "treatment": None}

    last_token = tokens[-1]

    parallel_match = RARITY_PARALLEL_TOKEN_RE.match(last_token)
    if parallel_match:
        return {"card_code": card_code, "rarity": parallel_match.group(1), "treatment": "parallel"}

    if BARE_RARITY_TOKEN_RE.match(last_token):
        return {"card_code": card_code, "rarity": last_token, "treatment": "normal"}

    # Token present but not a recognizable rarity shape (e.g. "SEC-RSP") -
    # fail closed rather than guess.
    return {"card_code": card_code, "rarity": None, "treatment": None}


# ---------------------------------------------------------------------------
# Section 4/5: product-scoped raw condition/price extraction.
# ---------------------------------------------------------------------------


def _class_has_suffix(tag: Tag, suffix: str) -> bool:
    classes = tag.get("class") or []
    return any(c.endswith(suffix) for c in classes)


def find_condition_chip_container(soup: BeautifulSoup) -> tuple[Tag | None, dict[str, Any]]:
    """Locate the smallest stable DOM container holding the product's own
    condition/price chip picker, distinguishing it from any recommendation
    carousel or unrelated filter UI elsewhere on the page.

    Confirmed live structure (apparels/104428, 2026-08-09): every condition
    (raw A/B/C/D and every graded category) is a `<button class="...__chip">`
    containing a `<p class="...__variant">` label and either a
    `<p class="...__price">` or `<p class="...__awaiting">`; all such buttons
    share one direct parent container. CSS-module hash prefixes change per
    deploy, so matching is done on the stable suffix only.
    """
    chip_buttons = [
        b for b in soup.find_all("button") if _class_has_suffix(b, "__chip")
    ]
    diagnostics: dict[str, Any] = {"chip_button_count": len(chip_buttons)}
    if not chip_buttons:
        diagnostics["reason"] = "no_chip_buttons_found"
        return None, diagnostics

    parents = {id(b.parent) for b in chip_buttons if b.parent is not None}
    diagnostics["distinct_parent_count"] = len(parents)
    if len(parents) != 1:
        # Ambiguous - more than one distinct chip group on the page (or a
        # detached button). Fail closed rather than guess which is the
        # product's own.
        diagnostics["reason"] = "chip_buttons_do_not_share_single_parent"
        return None, diagnostics

    container = chip_buttons[0].parent
    diagnostics["reason"] = "ok"
    diagnostics["container_selector"] = 'div (parent of button[class$="__chip"])'
    diagnostics["row_selector"] = 'button[class$="__chip"]'
    diagnostics["condition_label_selector"] = 'p[class$="__variant"]'
    diagnostics["price_selector"] = 'p[class$="__price"]'
    diagnostics["awaiting_selector"] = 'p[class$="__awaiting"]'
    return container, diagnostics


PRICE_DIGITS_RE = re.compile(r"([\d,]+)")


def extract_raw_conditions(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract the product's own raw (A/B/C/D) condition prices from its
    condition-chip container. Never touches graded (PSA/BGS/ARS/...) chips
    or any price found elsewhere on the page (e.g. recommendations)."""
    container, diagnostics = find_condition_chip_container(soup)
    result: dict[str, Any] = {
        "conditions": {},
        "raw_floor_jpy": None,
        "container_diagnostics": diagnostics,
    }
    if container is None:
        return result

    conditions: dict[str, Any] = {}
    for chip in container.find_all("button", recursive=False):
        if not _class_has_suffix(chip, "__chip"):
            continue
        variant_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__variant")),
            None,
        )
        if variant_el is None:
            continue
        label = variant_el.get_text(strip=True)
        if label not in RAW_CONDITION_LABELS:
            continue  # excludes every graded category deterministically

        price_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__price")),
            None,
        )
        awaiting_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__awaiting")),
            None,
        )

        price_jpy: int | None = None
        raw_text: str | None = None
        if price_el is not None:
            raw_text = price_el.get_text(strip=True)
            digits_match = PRICE_DIGITS_RE.search(raw_text)
            if digits_match:
                price_jpy = int(digits_match.group(1).replace(",", ""))
        elif awaiting_el is not None:
            raw_text = awaiting_el.get_text(strip=True)

        conditions[label] = {
            "condition": label,
            "price_jpy": price_jpy,
            "raw_text": raw_text,
        }

    result["conditions"] = conditions
    available_prices = [c["price_jpy"] for c in conditions.values() if c["price_jpy"] is not None]
    result["raw_floor_jpy"] = min(available_prices) if available_prices else None
    return result


# ---------------------------------------------------------------------------
# Section 7: JSON-LD parsing (object / array / @graph-wrapped).
# ---------------------------------------------------------------------------


def _flatten_ld_nodes(parsed: Any) -> list[dict[str, Any]]:
    """Normalize any JSON-LD shape (single object, list of objects, or an
    object wrapping an "@graph" list) into a flat list of node dicts."""
    nodes: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        for item in parsed:
            nodes.extend(_flatten_ld_nodes(item))
    elif isinstance(parsed, dict):
        graph = parsed.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                nodes.extend(_flatten_ld_nodes(item))
        else:
            nodes.append(parsed)
    return nodes


def find_embedded_json_blocks(html: str) -> dict[str, Any]:
    """Deterministic scan for common SPA/framework data-embedding patterns.
    Returns presence flags and, where safely parseable, the parsed/flattened
    JSON-LD nodes - never executes any script content."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "next_data_present": False,
        "next_data_top_level_keys": [],
        "ld_json_nodes": [],
        "ld_json_parse_errors": 0,
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
        except json.JSONDecodeError:
            result["ld_json_parse_errors"] += 1
            continue
        result["ld_json_nodes"].extend(_flatten_ld_nodes(parsed))

    for tag in soup.find_all("script", id=True, type="application/json"):
        if tag.get("id") != "__NEXT_DATA__":
            result["other_json_script_ids"].append(tag["id"])

    return result


def find_product_ld_node(ld_json_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a Product-typed node among flattened JSON-LD nodes, if any.
    Corroborating evidence only - never used to override the scoped
    raw-condition table (see extract_product_page)."""
    for node in ld_json_nodes:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if "Product" in types:
            return node
    return None


# ---------------------------------------------------------------------------
# Section 3: exact-artwork verification (perceptual hash + aspect ratio).
# ---------------------------------------------------------------------------

# Empirically derived 2026-08-09 from the real, confirmed-matching pair
# (official Bandai OP01-001_p2.png vs. SNKRDUNK's apparels/104428 product
# photo, alpha-bbox-cropped): average_hash distance 3/64, aspect ratio
# 0.716 vs. 0.7151 (0.13% apart). Thresholds below are set with margin above
# that observed distance while still well below what a genuinely different
# card's artwork produces (a differently-posed/colored card typically scores
# 20-30+ on average_hash at this normalization).
ARTWORK_HASH_DISTANCE_THRESHOLD = 12
ARTWORK_ASPECT_RATIO_TOLERANCE = 0.08  # relative difference, e.g. 0.08 = 8%
ARTWORK_HASH_SIZE = 8
ARTWORK_COMPARE_SIZE = (256, 256)


def _autocrop_transparent_padding(image: Any) -> Any:
    """If the image carries an alpha channel, crop to the bounding box of
    its non-transparent pixels. Background-removed product photos (as
    SNKRDUNK serves them) are otherwise padded with transparent space inside
    a canvas of a different aspect ratio than the actual card artwork,
    which would make an aspect-ratio/perceptual-hash comparison against the
    un-padded official artwork meaningless."""
    from PIL import Image

    if image.mode not in ("RGBA", "LA") and "transparency" not in image.info:
        return image
    rgba = image.convert("RGBA")
    alpha = rgba.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        return image
    cropped = rgba.crop(bbox)
    background = Image.new("RGB", cropped.size, (255, 255, 255))
    background.paste(cropped, mask=cropped.split()[-1])
    return background


def compare_artwork(official_bytes: bytes, candidate_bytes: bytes) -> dict[str, Any]:
    """Compare a candidate (SNKRDUNK) product image against the known
    official Bandai artwork. Pure function over raw bytes - independently
    testable offline with small synthetic images, no network required.

    Never requires byte identity. Accounts for background removal
    (autocrop to alpha bbox), resolution/compression differences (resize to
    a common normalization size before hashing). Fails closed (match=False)
    on any decode error or when computed distances exceed the documented
    thresholds.
    """
    import imagehash
    from PIL import Image, UnidentifiedImageError

    result: dict[str, Any] = {
        "match": False,
        "thresholds": {
            "hash_distance_max": ARTWORK_HASH_DISTANCE_THRESHOLD,
            "aspect_ratio_tolerance": ARTWORK_ASPECT_RATIO_TOLERANCE,
        },
    }
    try:
        official_img = Image.open(io.BytesIO(official_bytes))
        candidate_img = Image.open(io.BytesIO(candidate_bytes))
    except UnidentifiedImageError as exc:
        result["error"] = f"decode_error:{exc}"
        return result

    official_raw_size = official_img.size
    candidate_raw_size = candidate_img.size

    official_norm = _autocrop_transparent_padding(official_img).convert("RGB")
    candidate_norm = _autocrop_transparent_padding(candidate_img).convert("RGB")

    official_aspect = official_norm.size[0] / official_norm.size[1]
    candidate_aspect = candidate_norm.size[0] / candidate_norm.size[1]
    aspect_diff = abs(official_aspect - candidate_aspect) / official_aspect

    official_resized = official_norm.resize(ARTWORK_COMPARE_SIZE)
    candidate_resized = candidate_norm.resize(ARTWORK_COMPARE_SIZE)

    distances = {}
    for name, fn in (
        ("average_hash", imagehash.average_hash),
        ("dhash", imagehash.dhash),
        ("phash", imagehash.phash),
    ):
        h_official = fn(official_resized, hash_size=ARTWORK_HASH_SIZE)
        h_candidate = fn(candidate_resized, hash_size=ARTWORK_HASH_SIZE)
        distances[name] = int(h_official - h_candidate)

    result.update(
        {
            "official_raw_size": official_raw_size,
            "candidate_raw_size": candidate_raw_size,
            "official_normalized_size": official_norm.size,
            "candidate_normalized_size": candidate_norm.size,
            "official_aspect_ratio": round(official_aspect, 4),
            "candidate_aspect_ratio": round(candidate_aspect, 4),
            "aspect_ratio_relative_diff": round(aspect_diff, 4),
            "hash_distances": distances,
        }
    )

    hash_ok = bool(distances["average_hash"] <= ARTWORK_HASH_DISTANCE_THRESHOLD)
    aspect_ok = bool(aspect_diff <= ARTWORK_ASPECT_RATIO_TOLERANCE)
    result["match"] = bool(hash_ok and aspect_ok)
    result["hash_ok"] = hash_ok
    result["aspect_ok"] = aspect_ok
    return result


def find_main_product_image(soup: BeautifulSoup) -> tuple[str | None, dict[str, Any]]:
    """Locate the product's own primary photo, not the site-wide OGP
    fallback image (meta[property=og:image] is a generic SNKRDUNK logo on
    this site, confirmed live - not product-specific). Confirmed live
    selector: an <img class="...__mainImage"> inside the page's single
    image carousel."""
    imgs = [img for img in soup.find_all("img") if _class_has_suffix(img, "__mainImage")]
    diagnostics = {"main_image_candidate_count": len(imgs)}
    if len(imgs) != 1:
        diagnostics["reason"] = "expected_exactly_one_mainImage_img"
        return None, diagnostics
    src = imgs[0].get("src")
    diagnostics["reason"] = "ok"
    diagnostics["selector"] = 'img[class$="__mainImage"]'
    return src, diagnostics


# ---------------------------------------------------------------------------
# Section 8: sold/sales-history (public UI only).
# ---------------------------------------------------------------------------

SALES_HISTORY_CONDITION_HEADING_RE = re.compile(r"状態(.+?)の売買履歴")


def find_sales_history_link(soup: BeautifulSoup) -> tuple[str | None, dict[str, Any]]:
    """Find the product page's own normal-UI link to its public sales-history
    page (no login, no guessed API route - the literal href of a real
    on-page link)."""
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if any(kw in text or kw in href for kw in SOLD_HISTORY_LINK_KEYWORDS):
            return href, {"reason": "ok", "matched_text": text, "selector": "a[href]"}
    return None, {"reason": "no_sales_history_link_found"}


def parse_sales_history_page(html: str, product_id: str | None) -> dict[str, Any]:
    """Parse a sales-history page into per-condition raw/graded transaction
    lists. Each condition section is "状態{X}の売買履歴" followed by a
    `ul.sales-history.item-title` header row (skipped) and a
    `ul.sales-history.item-list` of `li.used` rows (p.date / p.size /
    p.price). No stable per-sale ID is exposed by the site - fields are
    recorded for a future fingerprint without inventing one."""
    soup = BeautifulSoup(html, "html.parser")
    login_markers_present = any(
        kw in soup.get_text(" ", strip=True) for kw in LOGIN_REQUIRED_MARKERS
    )

    all_sales: list[dict[str, Any]] = []
    conditions_found: list[str] = []

    for heading in soup.find_all(string=SALES_HISTORY_CONDITION_HEADING_RE):
        match = SALES_HISTORY_CONDITION_HEADING_RE.search(heading)
        if not match:
            continue
        condition_label = match.group(1).strip()
        conditions_found.append(condition_label)
        if condition_label not in RAW_CONDITION_LABELS:
            continue  # graded category - excluded from raw sold history

        heading_tag = heading.parent
        item_list = heading_tag.find_next(
            "ul", class_=lambda c: c and "sales-history" in c and "item-list" in c
        )
        if item_list is None:
            continue
        for row in item_list.find_all("li", class_="used"):
            date_el = row.find("p", class_="date")
            size_el = row.find("p", class_="size")
            price_el = row.find("p", class_="price")
            if date_el is None or size_el is None or price_el is None:
                continue
            row_condition = size_el.get_text(strip=True)
            if row_condition != condition_label:
                continue
            price_text = price_el.get_text(strip=True)
            digits_match = PRICE_DIGITS_RE.search(price_text)
            if not digits_match:
                continue
            all_sales.append(
                {
                    "product_id": product_id,
                    "condition": row_condition,
                    "price_jpy": int(digits_match.group(1).replace(",", "")),
                    "date": date_el.get_text(strip=True),
                }
            )

    all_sales.sort(key=lambda s: s["date"], reverse=True)

    if login_markers_present and not all_sales:
        availability_status = "login_required"
    elif all_sales:
        availability_status = "public_sold_history_available"
    elif conditions_found:
        # Condition sections were found but every one was empty - the page
        # structure is exposed, there just isn't any raw sale data (yet).
        availability_status = "public_sold_history_available"
    else:
        availability_status = "not_exposed_on_current_product"

    return {
        "availability_status": availability_status,
        "raw_sales": all_sales[:10],
        "stable_identifier_available": False,
        "conditions_found": conditions_found,
    }


# ---------------------------------------------------------------------------
# Top-level product extraction.
# ---------------------------------------------------------------------------


def extract_product_page(
    html: str,
    url: str,
    known_print: KnownPrint | None = None,
    artwork_comparison: dict[str, Any] | None = None,
    sold_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic, offline-testable extractor for a single already-fetched
    product page. Assembles the identity / raw_market / sold_history /
    evidence structure. Never guesses - fields are None/empty when not
    found, and diagnostics record what was/wasn't detected so a feasibility
    decision can be made from real evidence, not assumption."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""

    parsed_identity = parse_card_identity(title) or parse_card_identity(h1_text)

    image_url, image_diagnostics = find_main_product_image(soup)

    embedded = find_embedded_json_blocks(html)
    product_ld_node = find_product_ld_node(embedded["ld_json_nodes"])

    raw_conditions = extract_raw_conditions(soup)

    login_required_markers_present = any(
        kw in soup.get_text(" ", strip=True).lower() for kw in LOGIN_REQUIRED_MARKERS
    )

    product_id_match = APPAREL_ID_RE.search(url)
    product_id = product_id_match.group(1) if product_id_match else None

    exact_print_match = False
    identity_mismatch_reasons: list[str] = []
    if known_print is not None:
        if parsed_identity.get("card_code") != known_print.card_code:
            identity_mismatch_reasons.append("card_code_mismatch")
        if parsed_identity.get("rarity") != known_print.rarity:
            identity_mismatch_reasons.append("rarity_mismatch")
        if parsed_identity.get("treatment") != known_print.treatment:
            identity_mismatch_reasons.append("treatment_mismatch")
        if artwork_comparison is None or not artwork_comparison.get("match"):
            identity_mismatch_reasons.append("artwork_not_confirmed_match")
        exact_print_match = len(identity_mismatch_reasons) == 0

    return {
        "identity": {
            "product_id": product_id,
            "title": title,
            "h1": h1_text,
            "card_code": parsed_identity.get("card_code"),
            "rarity": parsed_identity.get("rarity"),
            "treatment": parsed_identity.get("treatment"),
            "set_code": known_print.set_code if known_print else None,
            "release_name": known_print.release_name if known_print else None,
            "language": known_print.language if known_print else None,
            "image_url": image_url,
            "product_url": url,
            "exact_print_match": exact_print_match,
            "identity_mismatch_reasons": identity_mismatch_reasons,
        },
        "raw_market": {
            "conditions": raw_conditions["conditions"],
            "raw_floor_jpy": raw_conditions["raw_floor_jpy"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        "sold_history": sold_history
        or {
            "availability_status": "inconclusive",
            "raw_sales": [],
            "stable_identifier_available": False,
        },
        "evidence": {
            "final_url": url,
            "condition_container": raw_conditions["container_diagnostics"],
            "main_image": image_diagnostics,
            "next_data_present": embedded["next_data_present"],
            "next_data_top_level_keys": embedded["next_data_top_level_keys"],
            "ld_json_node_types": [n.get("@type") for n in embedded["ld_json_nodes"]],
            "ld_json_product_node_present": product_ld_node is not None,
            "ld_json_parse_errors": embedded["ld_json_parse_errors"],
            "other_json_script_ids": embedded["other_json_script_ids"],
            "artwork_comparison": artwork_comparison,
            "parser_version": PARSER_VERSION,
        },
        "flags": {
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
    """Harvest the category page's link surface, find an unambiguous match
    against KNOWN_PRINTS (preference order). Falls back to SNKRDUNK's own
    /search endpoint per known print's card code if no unambiguous category
    match exists. Once matched, extract once."""
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


def _fetch_bytes(page: Page, url: str) -> bytes | None:
    """Fetch raw bytes for an image URL via the browser's own request
    context (reuses the already-established, Static-Outbound-IP session -
    no separate HTTP client/proxy)."""
    try:
        with deadline(PER_STEP_BUDGET_SECONDS, f"fetch:{url}"):
            response = page.context.request.get(url)
            if not response.ok:
                return None
            return response.body()
    except Exception:  # noqa: BLE001 - fail closed, never crash the run
        return None


def navigate_and_extract(
    page: Page, out_dir: Path, product_url: str, known_print: KnownPrint
) -> dict[str, Any]:
    """Navigate to product_url once, verify artwork, follow the page's own
    sales-history link once, then run the deterministic offline extractor.
    Shared by both the search-discovered path and a direct --product-url
    run."""
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
    soup = BeautifulSoup(html, "html.parser")

    # Section 3: artwork verification.
    artwork_comparison: dict[str, Any] | None = None
    candidate_image_url, _ = find_main_product_image(soup)
    if candidate_image_url:
        official_bytes = _fetch_bytes(page, known_print.image_url)
        candidate_bytes = _fetch_bytes(page, candidate_image_url)
        if official_bytes and candidate_bytes:
            artwork_comparison = compare_artwork(official_bytes, candidate_bytes)
        else:
            artwork_comparison = {
                "match": False,
                "error": "image_fetch_failed",
                "official_fetched": bool(official_bytes),
                "candidate_fetched": bool(candidate_bytes),
            }
    else:
        artwork_comparison = {"match": False, "error": "no_candidate_image_found"}
    log(
        "artwork_comparison_complete",
        match=artwork_comparison.get("match"),
        hash_distances=artwork_comparison.get("hash_distances"),
        aspect_ratio_relative_diff=artwork_comparison.get("aspect_ratio_relative_diff"),
    )

    # Section 8: sold history via the page's own normal-UI link.
    product_id_match = APPAREL_ID_RE.search(product_url)
    product_id = product_id_match.group(1) if product_id_match else None
    sold_history: dict[str, Any]
    history_href, history_link_diagnostics = find_sales_history_link(soup)
    if history_href is None:
        sold_history = {
            "availability_status": "not_exposed_on_current_product",
            "raw_sales": [],
            "stable_identifier_available": False,
            "link_diagnostics": history_link_diagnostics,
        }
    else:
        from urllib.parse import urljoin

        history_url = urljoin(product_url, history_href)
        history_nav = navigate_and_capture(page, history_url, "04_sales_history", out_dir)
        log(
            "sales_history_navigate_result",
            classification=history_nav.classification,
            http_status=history_nav.http_status,
        )
        if history_nav.classification == "normal_page":
            sold_history = parse_sales_history_page(page.content(), product_id)
            sold_history["link_diagnostics"] = history_link_diagnostics
            sold_history["source_url"] = history_url
        else:
            sold_history = {
                "availability_status": "inconclusive",
                "raw_sales": [],
                "stable_identifier_available": False,
                "link_diagnostics": history_link_diagnostics,
                "nav_classification": history_nav.classification,
            }
        # Navigating away means the product page's own DOM is gone from
        # `page` - re-fetch it isn't needed since `html`/`soup` above were
        # already captured before this navigation.

    extraction = extract_product_page(
        html,
        nav_result.final_url,
        known_print=known_print,
        artwork_comparison=artwork_comparison,
        sold_history=sold_history,
    )
    result["extraction"] = extraction

    (out_dir / "extracted.json").write_text(
        json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        "extraction_complete",
        raw_floor_jpy=extraction["raw_market"]["raw_floor_jpy"],
        conditions=list(extraction["raw_market"]["conditions"].keys()),
        sold_history_status=extraction["sold_history"]["availability_status"],
        sold_sales_count=len(extraction["sold_history"]["raw_sales"]),
        exact_print_match=extraction["identity"]["exact_print_match"],
        identity_mismatch_reasons=extraction["identity"]["identity_mismatch_reasons"],
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["access", "full"],
        default="access",
        help="access = the 3-URL access test only. full = access, then (if "
        "the category page loaded normally) discover + extract against a "
        "KNOWN_PRINTS match, all in one bounded session.",
    )
    parser.add_argument(
        "--product-url",
        default=None,
        help="If set with --stage full, skip category-link/search discovery "
        "entirely and extract directly from this product URL against "
        "KNOWN_PRINTS[0] (the primary target print).",
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

                    category_ok = (
                        bool(access_results)
                        and access_results[-1].classification == "normal_page"
                        and access_results[-1].url == CATEGORY_URL
                    )
                    if args.stage == "full" and category_ok and args.product_url:
                        known_print = KNOWN_PRINTS[0]
                        de: dict[str, Any] = {
                            "matched": True,
                            "match_source": "direct_product_url",
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
