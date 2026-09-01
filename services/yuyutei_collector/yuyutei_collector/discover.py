"""One-off category-page discovery helper used only to locate stable
Yuyu-Tei product URLs for candidate identity verification - not part of the
permanent single-mapping collection path (collect.py) and not scheduled or
invoked by any Beat/cron entry. Read-only: never writes to the database.
Bounded to exactly one request per category page, no retries.
"""

import argparse
import json

from playwright.sync_api import sync_playwright

from yuyutei_collector.browser import deadline, log_event
from yuyutei_collector.card_code import CARD_CODE_RE

# Re-exported, not redefined: discovery_listing, discovery_probe and
# tests/test_discovery_probe.py all import CARD_CODE_RE from here, and the
# grammar itself now lives in yuyutei_collector.card_code so extraction and
# discovery cannot drift apart again. Keeping the name importable from this
# module means none of those callers has to change.
__all__ = ["CARD_CODE_RE", "list_category_products", "main"]


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
            """els => els.map(el => {
                const card = el.closest('li') || el.closest('.card') || el.parentElement;
                const img = el.querySelector('img') || (card ? card.querySelector('img') : null);
                return {
                    href: el.href,
                    text: (el.textContent || '').trim(),
                    card_text: card ? (card.textContent || '').trim().replace(/\\s+/g, ' ') : '',
                    img_alt: img ? (img.getAttribute('alt') || '') : '',
                };
            })""",
        )
        context.close()
        browser.close()

    seen = {}
    for it in items:
        href = it["href"]
        label = it["text"] or it["img_alt"] or it["card_text"]
        code_match = CARD_CODE_RE.search(label) or CARD_CODE_RE.search(it["card_text"])
        if href not in seen:
            seen[href] = {
                "href": href,
                "label": label[:200],
                "card_text": it["card_text"][:200],
                "card_code": code_match.group(0) if code_match else None,
            }
    return list(seen.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True, help="e.g. op01, op02")
    args = parser.parse_args()
    results = list_category_products(args.set)
    # One compact line - Railway ships each stdout line as a separate log
    # entry, so a pretty-printed multi-line dump arrives jumbled/reordered.
    print(json.dumps(results, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
