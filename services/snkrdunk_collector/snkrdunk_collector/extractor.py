"""Product-scoped raw condition/price extraction, JSON-LD parsing, and main-
image discovery. Moved out of spikes/snkrdunk-browser-feasibility/spike.py,
live-validated 2026-08-09 against https://snkrdunk.com/apparels/104428 (see
that spike's tests/ for the fixture-backed proof of each piece below).

No AI calls; deterministic BeautifulSoup DOM/regex extraction only. Never a
whole-page price regex - every price comes from inside the product's own
condition-chip container, confirmed live to be the sole such container on
the page (see find_condition_chip_container).
"""

import json
import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from snkrdunk_collector.identity import (
    normalize_set_token_to_release_product_code,
    parse_card_identity,
    parse_page_language,
    set_token_from_card_code,
)

SELECTOR_VERSION = "v1"

# Confirmed live (apparels/104428, 2026-08-09): exactly these 4 labels are
# raw; everything else in the same condition-chip picker (PSA*, BGS*, ARS*,
# 他鑑定品) is a graded-slab category and must never be treated as raw.
RAW_CONDITION_LABELS = ("A", "B", "C", "D")
AWAITING_LISTING_TEXT = "出品待ち"

PRICE_DIGITS_RE = re.compile(r"([\d,]+)")


def _class_has_suffix(tag: Tag, suffix: str) -> bool:
    classes = tag.get("class") or []
    return any(c.endswith(suffix) for c in classes)


def find_condition_chip_container(soup: BeautifulSoup) -> tuple[Tag | None, dict[str, Any]]:
    """Locate the smallest stable DOM container holding the product's own
    condition/price chip picker, distinguishing it from any recommendation
    carousel or unrelated filter UI elsewhere on the page.

    Confirmed live structure: every condition (raw A/B/C/D and every graded
    category) is a `<button class="...__chip">` containing a
    `<p class="...__variant">` label and either a `<p class="...__price">`
    or `<p class="...__awaiting">`; all such buttons share one direct
    parent container. CSS-module hash prefixes change per deploy, so
    matching is done on the stable suffix only.
    """
    chip_buttons = [b for b in soup.find_all("button") if _class_has_suffix(b, "__chip")]
    diagnostics: dict[str, Any] = {"chip_button_count": len(chip_buttons)}
    if not chip_buttons:
        diagnostics["reason"] = "no_chip_buttons_found"
        return None, diagnostics

    parents = {id(b.parent) for b in chip_buttons if b.parent is not None}
    diagnostics["distinct_parent_count"] = len(parents)
    if len(parents) != 1:
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


def extract_raw_conditions(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract the product's own raw (A/B/C/D) condition prices from its
    condition-chip container. Never touches graded (PSA/BGS/ARS/...) chips
    or any price found elsewhere on the page (e.g. recommendations)."""
    container, diagnostics = find_condition_chip_container(soup)
    result: dict[str, Any] = {
        "conditions": {},
        "raw_floor_jpy": None,
        "raw_floor_condition": None,
        "container_diagnostics": diagnostics,
    }
    if container is None:
        return result

    conditions: dict[str, Any] = {}
    for chip in container.find_all("button", recursive=False):
        if not _class_has_suffix(chip, "__chip"):
            continue
        variant_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__variant")), None
        )
        if variant_el is None:
            continue
        label = variant_el.get_text(strip=True)
        if label not in RAW_CONDITION_LABELS:
            continue

        price_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__price")), None
        )
        awaiting_el = next(
            (p for p in chip.find_all("p", recursive=False) if _class_has_suffix(p, "__awaiting")), None
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

        conditions[label] = {"condition": label, "price_jpy": price_jpy, "raw_text": raw_text}

    result["conditions"] = conditions
    available = [(c["price_jpy"], c["condition"]) for c in conditions.values() if c["price_jpy"] is not None]
    if available:
        floor_price, floor_condition = min(available, key=lambda x: x[0])
        result["raw_floor_jpy"] = floor_price
        result["raw_floor_condition"] = floor_condition
    return result


def find_main_product_image(soup: BeautifulSoup) -> tuple[str | None, dict[str, Any]]:
    """Locate the product's own primary photo, not the site-wide OGP
    fallback image (meta[property=og:image] is a generic SNKRDUNK logo,
    confirmed live - not product-specific). Confirmed live selector: an
    <img class="...__mainImage"> inside the page's single image carousel."""
    imgs = [img for img in soup.find_all("img") if _class_has_suffix(img, "__mainImage")]
    diagnostics = {"main_image_candidate_count": len(imgs)}
    if len(imgs) != 1:
        diagnostics["reason"] = "expected_exactly_one_mainImage_img"
        return None, diagnostics
    src = imgs[0].get("src")
    diagnostics["reason"] = "ok"
    diagnostics["selector"] = 'img[class$="__mainImage"]'
    return src, diagnostics


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
    """Deterministic scan for JSON-LD (object/array/@graph-wrapped) - used
    as corroborating evidence only, never allowed to override the scoped
    raw-condition table (see writer.py, which never reads price from this)."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {"ld_json_nodes": [], "ld_json_parse_errors": 0}

    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            parsed = json.loads(tag.string)
        except json.JSONDecodeError:
            result["ld_json_parse_errors"] += 1
            continue
        result["ld_json_nodes"].extend(_flatten_ld_nodes(parsed))

    return result


def find_product_ld_node(ld_json_nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in ld_json_nodes:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if "Product" in types:
            return node
    return None


def extract_product(
    html: str, url: str, expected_card_code: str, expected_treatment: str | None
) -> dict[str, Any]:
    """Top-level deterministic extractor for one already-fetched product
    page. Fails closed (extraction_status="fail_closed") on any identity
    conflict or missing raw price - never guesses. Mirrors the shape of
    yuyutei_collector.extractor.extract_with_agreement (extraction_status /
    fail_reasons / extracted{...} / raw{...}) for consistency across
    collectors, adapted for SNKRDUNK's per-condition price picker instead of
    a single sell price."""
    soup = BeautifulSoup(html, "html.parser")
    fail_reasons: list[str] = []

    title = soup.title.get_text(strip=True) if soup.title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""

    parsed_identity = parse_card_identity(title)
    if parsed_identity.get("card_code") is None:
        parsed_identity = parse_card_identity(h1_text)
    page_language = parse_page_language(html)

    image_url, image_diagnostics = find_main_product_image(soup)
    embedded = find_embedded_json_blocks(html)
    product_ld_node = find_product_ld_node(embedded["ld_json_nodes"])
    raw_conditions = extract_raw_conditions(soup)

    resolved_card_code = parsed_identity.get("card_code")
    resolved_treatment = parsed_identity.get("treatment")

    # The set the *page itself* claims, rendered in the repository's
    # release_product_code convention, derived from the card code the page
    # displays.
    #
    # EVIDENCE ONLY - IT DECIDES NOTHING. It is an inference from the CARD
    # code, so it is a fact about the card and never an observation about
    # which product the item shipped in; for a reprint the two legitimately
    # differ. Release verification measures the title's release
    # parenthetical (`release_text`, below) against the authoritative names of
    # the product the PRINT belongs to - see release_identity.py. This value
    # is retained because an audit record should show what the page claimed.
    observed_set_token = set_token_from_card_code(resolved_card_code)
    observed_release_product_code = normalize_set_token_to_release_product_code(observed_set_token)

    if resolved_card_code != expected_card_code:
        fail_reasons.append(
            f"card_code_conflict:displayed={resolved_card_code},expected={expected_card_code}"
        )
    # None means the print carries no Atlas treatment classification, so
    # there is nothing to conflict with; it does NOT mean the page must show
    # no treatment. A real expectation is still checked exactly as strictly.
    if expected_treatment is not None and resolved_treatment != expected_treatment:
        fail_reasons.append(
            f"treatment_conflict:displayed={resolved_treatment},expected={expected_treatment}"
        )
    if raw_conditions["raw_floor_jpy"] is None:
        fail_reasons.append("no_raw_condition_price_available")
    if image_url is None:
        fail_reasons.append(f"main_image_not_found:{image_diagnostics.get('reason')}")

    extraction_status = "extracted" if not fail_reasons else "fail_closed"

    return {
        "extraction_status": extraction_status,
        "fail_reasons": fail_reasons,
        "selector_version": SELECTOR_VERSION,
        "extracted": {
            "title": title,
            "h1": h1_text,
            "card_name": parsed_identity.get("name"),
            "card_code": resolved_card_code,
            "rarity": parsed_identity.get("rarity"),
            # Whether the title PUBLISHED a rarity, could not be READ, or
            # carried none at all - see identity.RARITY_*. The writer needs the
            # distinction: silence narrows nothing, an unreadable claim fails
            # closed.
            "rarity_evidence": parsed_identity.get("rarity_evidence"),
            "treatment": resolved_treatment,
            "page_language": page_language,
            "release_text": parsed_identity.get("release_text"),
            "release_product_code": observed_release_product_code,
            "set_token": observed_set_token,
            "product_image_url": image_url,
            "raw_floor_jpy": raw_conditions["raw_floor_jpy"],
            "raw_floor_condition": raw_conditions["raw_floor_condition"],
            "conditions": raw_conditions["conditions"],
            "final_url": url,
        },
        "raw": {
            "condition_container": raw_conditions["container_diagnostics"],
            "main_image": image_diagnostics,
            "ld_json_node_types": [n.get("@type") for n in embedded["ld_json_nodes"]],
            "ld_json_product_node_present": product_ld_node is not None,
            "ld_json_parse_errors": embedded["ld_json_parse_errors"],
        },
    }
