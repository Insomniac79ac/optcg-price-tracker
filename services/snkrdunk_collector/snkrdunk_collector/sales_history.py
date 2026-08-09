"""Public sold/sales-history extraction - EVIDENCE ONLY. Moved out of
spikes/snkrdunk-browser-feasibility/spike.py, live-validated 2026-08-09
against https://snkrdunk.com/apparels/104428/sales-histories (reached by
following the product page's own "状態ごとの相場一覧を見る" link - normal
public UI, no login, no guessed API route).

Deliberately NOT wired into writer.py: the live-validated run's own output
contains two genuinely separate condition-A sales on 2026/07/06, both
priced ¥32,999 - concrete, real proof that
(product_id + condition + price + date) can silently collapse two distinct
transactions into one. No stable per-sale identifier exists anywhere in the
DOM (no href, no data-* attribute, no id - only a generic rotating
"user-icon-N.png" avatar, not a sale identifier) or in any embedded JSON on
the page (no __NEXT_DATA__, no sale-scoped JSON-LD). Per this tranche's
scope, sold rows are retained as raw evidence/log metadata only - never
persisted as individual price_observations rows - until a safe fingerprint
is found.
"""

import re
from typing import Any

from bs4 import BeautifulSoup

from snkrdunk_collector.extractor import PRICE_DIGITS_RE, RAW_CONDITION_LABELS

SOLD_HISTORY_LINK_KEYWORDS = [
    "状態ごとの相場一覧",
    "売買履歴",
    "取引履歴",
    "売却履歴",
    "販売実績",
    "取引実績",
    "sales-histories",
]
LOGIN_REQUIRED_MARKERS = ["ログイン", "login", "sign in", "signin"]

SALES_HISTORY_CONDITION_HEADING_RE = re.compile(r"状態(.+?)の売買履歴")


def find_sales_history_link(soup: BeautifulSoup) -> tuple[str | None, dict[str, Any]]:
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if any(kw in text or kw in href for kw in SOLD_HISTORY_LINK_KEYWORDS):
            return href, {"reason": "ok", "matched_text": text, "selector": "a[href]"}
    return None, {"reason": "no_sales_history_link_found"}


def parse_sales_history_page(html: str, product_id: str | None) -> dict[str, Any]:
    """Parse a sales-history page into per-condition raw/graded transaction
    lists, for logging/evidence purposes only - see module docstring. No
    stable per-sale ID is invented."""
    soup = BeautifulSoup(html, "html.parser")
    login_markers_present = any(kw in soup.get_text(" ", strip=True) for kw in LOGIN_REQUIRED_MARKERS)

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
    elif all_sales or conditions_found:
        availability_status = "public_sold_history_available"
    else:
        availability_status = "not_exposed_on_current_product"

    return {
        "availability_status": availability_status,
        "raw_sales": all_sales[:10],
        "stable_identifier_available": False,
        "conditions_found": conditions_found,
    }
