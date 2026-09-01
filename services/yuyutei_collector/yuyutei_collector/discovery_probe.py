"""Read-only Yuyu-Tei catalogue enumeration probe. Reports; never persists.

WHAT THIS IS FOR. Before Atlas builds candidate persistence it needs to know
whether Yuyu-Tei's listing pages can be enumerated deterministically: do
category pages list every product, is there pagination, are product ids
stable, and do parallel printings appear as separate products? This probe
answers those questions from the real source and prints a structured report.
It is the measurement step that replaces the estimates in the feasibility
audit with facts.

WHAT IT DELIBERATELY IS NOT.
  - It writes NOTHING. No database session is opened, no candidate row, no
    mapping, no observation. The only output is stdout JSON.
  - It opens NO product pages. Listing pages only - so the question "is the
    listing alone sufficient?" is answered by what the listing actually
    carries, not by backfilling from detail pages.
  - It is NOT scheduled and has no Beat/cron entry. One manual invocation.
  - It infers NO global set index. Slugs are passed in explicitly; the probe
    never discovers-then-crawls its way across the catalogue.

SOURCE POSTURE, unchanged from the collector's charter (see browser.py): one
normal navigation per URL, no proxy rotation, no CAPTCHA service, no
fingerprint spoofing beyond supported Playwright context options, and no
retry after a 403/429/challenge. A denial stops the whole probe immediately
rather than being retried or worked around - see _DENIAL_STATUSES.

RUN IT FROM RAILWAY STAGING, NEVER FROM CODESPACES. That egress IP is blocked
at the edge and answers 403 for every Yuyu-Tei URL, including ones staging
fetches with HTTP 200 daily. A 403 seen from Codespaces says nothing about
the source and must never be treated as a policy change or answered with a
workaround.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from yuyutei_collector.browser import deadline, log_event
from yuyutei_collector.config import settings
from yuyutei_collector.discover import CARD_CODE_RE

CATEGORY_URL = "https://yuyu-tei.jp/sell/opc/s/{slug}"

# The stable product URL shape: /sell/opc/card/<series>/<id>. `series` is the
# Yuyu category slug and `id` its opaque numeric product id - together they
# are the product's identity. The id is NOT derivable from a card code, which
# is exactly why enumeration is needed at all.
PRODUCT_PATH_RE = re.compile(r"/sell/opc/card/([^/?#]+)/(\d+)")

# Statuses that mean "the source declined". The probe stops; it never retries,
# never backs off into a second attempt, never varies its request to get a
# different answer.
_DENIAL_STATUSES = frozenset({401, 403, 405, 429, 451, 503})

# Hard ceilings, both PER SLUG. Every requested slug gets its own product
# budget rather than drawing on a shared pool, because a shared pool makes the
# probe's coverage depend on slug ORDER: the first large category eats the
# budget and every later slug reports zero, which is indistinguishable in the
# output from a category that genuinely has no products. Per-slug budgets keep
# each set an independent measurement while still bounding the total crawl at
# len(slugs) * MAX_PRODUCTS_PER_SLUG.
DEFAULT_MAX_PRODUCTS_PER_SLUG = 200
DEFAULT_MAX_PAGES_PER_SLUG = 3


class SourceDenied(RuntimeError):
    """The source answered with a denial status. Never caught-and-retried."""


def _parse_product(href: str) -> tuple[str, str] | None:
    """(series, product_id) for a product URL, else None."""
    match = PRODUCT_PATH_RE.search(urlparse(href).path)
    return (match.group(1), match.group(2)) if match else None


def _pagination_links(page, base_url: str) -> list[str]:
    """Absolute URLs of any page-2+ links this listing offers.

    Read from real anchors only - the probe never fabricates `?page=2` and
    tries it. If the source paginates, it says so in the DOM; if it does not,
    the absence of links here IS the finding, and the report records it.
    """
    hrefs = page.eval_on_selector_all(
        "a[href*='page='], a[rel='next'], .pagination a, nav[aria-label*='age'] a",
        "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
    )
    out: list[str] = []
    for href in hrefs:
        absolute = urljoin(base_url, href)
        if absolute != base_url and absolute not in out:
            out.append(absolute)
    return out


def _scrape_listing(page, url: str, timeout_s: int) -> dict[str, Any]:
    """One listing page: navigate once, read what it carries, move on."""
    with deadline(timeout_s, "category_navigation"):
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1_500)

    status = response.status if response else None
    if status in _DENIAL_STATUSES:
        log_event("probe_source_denied", url=url, http_status=status)
        raise SourceDenied(f"{status} at {url}")

    rows = page.eval_on_selector_all(
        "a[href*='/sell/opc/card/']",
        """els => els.map(el => {
            const card = el.closest('li') || el.closest('.card') || el.parentElement;
            const img = el.querySelector('img') || (card ? card.querySelector('img') : null);
            return {
                href: el.href,
                text: (el.textContent || '').trim(),
                card_text: card ? (card.textContent || '').trim().replace(/\\s+/g, ' ') : '',
                img_alt: img ? (img.getAttribute('alt') || '') : '',
                img_src: img ? (img.getAttribute('src') || '') : '',
            };
        })""",
    )
    return {
        "url": url,
        "http_status": status,
        "html_bytes": len(page.content().encode("utf-8")),
        "anchors": rows,
        "pagination_links": _pagination_links(page, url),
    }


def _normalize(row: dict[str, Any]) -> dict[str, Any] | None:
    """One listing anchor as a discovered product, or None if it is not one."""
    parsed = _parse_product(row["href"])
    if parsed is None:
        return None
    series, product_id = parsed
    # The label is whatever the listing actually shows. Card code is taken
    # from it via the shared CARD_CODE_RE, so discovery and the rest of the
    # collector agree on what a code looks like.
    label = row["text"] or row["img_alt"] or row["card_text"]
    haystack = f"{label} {row['card_text']} {row['img_alt']}"
    code = CARD_CODE_RE.search(haystack)
    return {
        "series": series,
        "product_id": product_id,
        "url": f"https://yuyu-tei.jp/sell/opc/card/{series}/{product_id}",
        "card_code": code.group(0) if code else None,
        "label": label[:120],
        "listing_text": row["card_text"][:160],
        "image_src": row["img_src"][:160],
    }


def probe_slug(
    page, slug: str, *, max_pages: int, remaining_budget: int, timeout_s: int
) -> dict[str, Any]:
    """Enumerate one category slug within its page and product budgets."""
    pages_fetched: list[dict[str, Any]] = []
    products: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_links = 0
    queue = [CATEGORY_URL.format(slug=slug)]
    seen_urls: set[str] = set()

    while queue and len(pages_fetched) < max_pages and len(products) < remaining_budget:
        url = queue.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        if pages_fetched:
            # Same inter-request delay the collector already uses. Applied
            # between pages, never skipped to go faster.
            time.sleep(settings.YUYUTEI_REQUEST_DELAY_MS / 1000)

        result = _scrape_listing(page, url, timeout_s)
        pages_fetched.append(
            {
                "url": url,
                "http_status": result["http_status"],
                "html_bytes": result["html_bytes"],
                "anchor_count": len(result["anchors"]),
                "pagination_links": result["pagination_links"],
            }
        )
        for row in result["anchors"]:
            item = _normalize(row)
            if item is None:
                continue
            key = (item["series"], item["product_id"])
            if key in products:
                duplicate_links += 1
                continue
            if len(products) >= remaining_budget:
                break
            products[key] = item
        for link in result["pagination_links"]:
            if link not in seen_urls:
                queue.append(link)

    found = list(products.values())
    codes = [p["card_code"] for p in found if p["card_code"]]
    # A product whose own series slug differs from the category it was listed
    # under - worth surfacing, because it means a listing page cross-links
    # into other sets and a naive count would over-report the set.
    foreign = [p for p in found if p["series"] != slug]
    return {
        "slug": slug,
        "pages_fetched": pages_fetched,
        "page_count": len(pages_fetched),
        "pagination_seen": any(p["pagination_links"] for p in pages_fetched),
        "pagination_followed": max(0, len(pages_fetched) - 1),
        "products_discovered": len(found),
        "duplicate_product_links": duplicate_links,
        "distinct_card_codes": len(set(codes)),
        "products_without_code": sum(1 for p in found if not p["card_code"]),
        "products_from_other_series": len(foreign),
        "other_series_seen": sorted({p["series"] for p in foreign})[:10],
        "budget_exhausted": len(found) >= remaining_budget,
        "sample": found[:5],
        "products": found,
    }


def run_probe(
    slugs: list[str],
    *,
    max_products_per_slug: int = DEFAULT_MAX_PRODUCTS_PER_SLUG,
    max_pages_per_slug: int = DEFAULT_MAX_PAGES_PER_SLUG,
    timeout_s: int = 90,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "slugs_requested": slugs,
        "max_products_per_slug": max_products_per_slug,
        "max_pages_per_slug": max_pages_per_slug,
        "request_delay_ms": settings.YUYUTEI_REQUEST_DELAY_MS,
        "sets": [],
        "stopped_reason": None,
    }
    total = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
        )
        context = browser.new_context()
        page = context.new_page()
        try:
            for slug in slugs:
                if report["sets"]:
                    time.sleep(settings.YUYUTEI_REQUEST_DELAY_MS / 1000)
                try:
                    result = probe_slug(
                        page,
                        slug,
                        max_pages=max_pages_per_slug,
                        remaining_budget=max_products_per_slug,
                        timeout_s=timeout_s,
                    )
                except SourceDenied as exc:
                    # Stop everything. Not this slug only, and never a retry:
                    # the source declined and the probe's answer is to leave.
                    report["stopped_reason"] = f"source_denied: {exc}"
                    break
                total += result["products_discovered"]
                report["sets"].append(result)
        finally:
            context.close()
            browser.close()

    report["total_products_discovered"] = total
    report["total_pages_fetched"] = sum(s["page_count"] for s in report["sets"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Yuyu-Tei listing probe. Writes nothing.")
    parser.add_argument("--slugs", required=True, help="comma-separated, e.g. op01,op13,eb01")
    parser.add_argument(
        "--max-products-per-slug", type=int, default=DEFAULT_MAX_PRODUCTS_PER_SLUG
    )
    parser.add_argument("--max-pages-per-slug", type=int, default=DEFAULT_MAX_PAGES_PER_SLUG)
    args = parser.parse_args()

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    report = run_probe(
        slugs,
        max_products_per_slug=args.max_products_per_slug,
        max_pages_per_slug=args.max_pages_per_slug,
    )
    # A compact summary line per set, then one machine-readable object. Railway
    # ships each stdout line as its own log entry, so a pretty-printed dump
    # arrives interleaved and unreadable.
    for result in report["sets"]:
        log_event(
            "probe_set_complete",
            slug=result["slug"],
            pages=result["page_count"],
            pagination_seen=result["pagination_seen"],
            products=result["products_discovered"],
            distinct_codes=result["distinct_card_codes"],
            without_code=result["products_without_code"],
            duplicates=result["duplicate_product_links"],
            other_series=result["products_from_other_series"],
        )
    slim = {**report, "sets": [{k: v for k, v in s.items() if k != "products"} for s in report["sets"]]}
    print(json.dumps(slim, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
