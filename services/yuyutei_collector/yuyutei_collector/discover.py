"""One-off category-page discovery helper used only to locate stable
Yuyu-Tei product URLs for candidate identity verification - not part of the
permanent single-mapping collection path (collect.py) and not scheduled or
invoked by any Beat/cron entry. Read-only: never writes to the database.
Bounded to exactly one request per category page, no retries.
"""

import argparse
import json
import re

from playwright.sync_api import sync_playwright

from yuyutei_collector.browser import deadline, log_event

CARD_CODE_RE = re.compile(r"\bOP\d{2}-\d{3}\b")


def list_category_products(set_slug: str, timeout_s: int = 60) -> list[dict]:
    url = f"https://yuyu-tei.jp/sell/opc/s/{set_slug}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, timeout=30000)
        context = browser.new_context()
        page = context.new_page()
        with deadline(timeout_s, "category_navigation"):
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
        status = resp.status if resp else None
        html = page.content()
        log_event("category_fetched", url=url, http_status=status, html_bytes=len(html.encode("utf-8")))

        items = page.eval_on_selector_all(
            "a[href*='/sell/opc/card/']",
            """els => els.map(el => ({href: el.href, text: (el.textContent || '').trim()}))""",
        )
        context.close()
        browser.close()

    seen = {}
    for it in items:
        href = it["href"]
        text = it["text"]
        code_match = CARD_CODE_RE.search(text)
        if href not in seen:
            seen[href] = {"href": href, "text": text[:200], "card_code": code_match.group(0) if code_match else None}
    return list(seen.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True, help="e.g. op01, op02")
    args = parser.parse_args()
    results = list_category_products(args.set)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
