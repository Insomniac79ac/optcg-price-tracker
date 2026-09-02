"""Persistence-capable Yuyu-Tei listing discovery: enumerate, classify, store.

WHAT THIS DOES. For each explicitly requested category slug it fetches the
listing page(s) once, turns every own-series product row into a
yuyutei_candidates row, and records the whole run in yuyutei_discovery_runs
with per-slug measurements. It is the persisting sibling of discovery_probe,
and it reuses that module's page fetching so there is exactly one
implementation of "navigate a listing page" in this service.

WHAT IT DELIBERATELY DOES NOT DO, and the imports below are the proof:
  - no source_card_mappings row is created, updated or read
  - no price_observations row is written - a candidate records what the
    listing displayed, which is evidence, not a priced observation
  - no Market Index code is invoked
  - no approval is granted; no candidate is ever promoted
  - no product page is fetched; the listing row is the only input
  - no schedule exists - there is no cron entry and no Beat task; this runs
    only when a person invokes it with explicit slugs

SOURCE POSTURE, unchanged from browser.py's charter and from the probe: one
normal navigation per URL, the configured inter-request delay between pages,
no proxy rotation, no fingerprint spoofing, and NO retry after a denial. A
401/403/405/429/451/503 stops the entire run, which is recorded with status
'denied' - never retried, never varied to get a different answer.

RUN IT FROM RAILWAY STAGING, NEVER FROM CODESPACES. That egress IP is blocked
at the edge and answers 403 for every Yuyu-Tei URL, including ones staging
fetches with HTTP 200 daily. A 403 seen from Codespaces says nothing about the
source and must never be answered with a workaround.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from yuyutei_collector.browser import (
    HOMEPAGE_URL,
    homepage_session_ok,
    log_event,
    warm_up_homepage,
)
from yuyutei_collector.config import settings
from yuyutei_collector.discovery_listing import ListingProduct, parse_listing_row
from yuyutei_collector.discovery_match import classify_card_code
from yuyutei_collector.discovery_probe import (
    CATEGORY_URL,
    DEFAULT_MAX_PAGES_PER_SLUG,
    _DENIAL_STATUSES,
    SourceDenied,
    _scrape_listing,
)
from yuyutei_collector.models import YuyuteiCandidate, YuyuteiDiscoveryRun

# Per slug, never a shared pool: a shared budget makes coverage depend on slug
# order, so the first large category starves every later one and the output
# cannot be told apart from a genuinely empty set. Measured set sizes are
# 80-200 products, so 500 leaves real headroom while still bounding a run at
# len(slugs) * 500.
MAX_PRODUCTS_PER_SLUG = 500


@dataclass
class SlugEnumeration:
    """What one category slug yielded, before anything was written."""

    slug: str
    products: list[ListingProduct] = field(default_factory=list)
    pages_fetched: list[dict[str, Any]] = field(default_factory=list)
    raw_product_anchors: int = 0
    distinct_source_products: int = 0
    duplicate_products: int = 0
    foreign_series_filtered: int = 0
    foreign_series_seen: list[str] = field(default_factory=list)
    pagination_seen: bool = False
    budget_exhausted: bool = False
    page_budget_exhausted: bool = False
    unfetched_pages: int = 0
    enumeration_complete: bool = True


def enumerate_slug(
    page,
    slug: str,
    *,
    max_products: int = MAX_PRODUCTS_PER_SLUG,
    max_pages: int = DEFAULT_MAX_PAGES_PER_SLUG,
    timeout_s: int = 90,
) -> SlugEnumeration:
    """Listing pages for one slug, deduplicated and filtered to that slug.

    Identity is (series, product_id). Yuyu-Tei numbers products WITHIN a
    category - ids 10152-10154 exist in both op01 and op13 and denote different
    cards - so product_id alone would merge unrelated products.

    Products whose own series differs from `slug` are counted and dropped:
    listing pages cross-link into other sets (measured at 12-38% of rows), and
    keeping them would file another set's products under this one. The product
    budget applies to KEPT products only, so a page full of cross-links cannot
    consume a slug's allowance - which is also why dropping them can never make
    a complete enumeration look truncated.

    `enumeration_complete` says whether the slug was read to the end: False
    when the product cap stopped it, or when the page cap left a real,
    unvisited pagination link behind. It is set from those two facts and never
    from the number of products found - a small set and a truncated large one
    are indistinguishable by count.
    """
    result = SlugEnumeration(slug=slug)
    seen: set[tuple[str, str]] = set()
    foreign: set[str] = set()
    queue = [CATEGORY_URL.format(slug=slug)]
    visited: set[str] = set()

    while queue and len(result.pages_fetched) < max_pages and not result.budget_exhausted:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if result.pages_fetched:
            # The collector's own inter-request delay, applied between pages
            # and never skipped to go faster.
            time.sleep(settings.YUYUTEI_REQUEST_DELAY_MS / 1000)

        scraped = _scrape_listing(page, url, timeout_s)
        result.pages_fetched.append(
            {
                "url": url,
                "http_status": scraped["http_status"],
                "html_bytes": scraped["html_bytes"],
                "anchor_count": len(scraped["anchors"]),
                "pagination_links": scraped["pagination_links"],
            }
        )
        if scraped["pagination_links"]:
            result.pagination_seen = True

        for row in scraped["anchors"]:
            product = parse_listing_row(row)
            if product is None:
                continue
            result.raw_product_anchors += 1
            key = (product.series, product.product_id)
            if key in seen:
                result.duplicate_products += 1
                continue
            seen.add(key)
            if product.series != slug:
                result.foreign_series_filtered += 1
                foreign.add(product.series)
                continue
            if len(result.products) >= max_products:
                result.budget_exhausted = True
                break
            result.products.append(product)

        for link in scraped["pagination_links"]:
            if link not in visited:
                queue.append(link)

    # A link is only outstanding if it was never fetched. The last page of a
    # set links back to page 1, so a queue entry alone proves nothing - and
    # exhausting max_pages with nothing left to fetch is a complete read.
    unvisited = [url for url in dict.fromkeys(queue) if url not in visited]
    result.page_budget_exhausted = bool(unvisited) and len(result.pages_fetched) >= max_pages
    result.unfetched_pages = len(unvisited)
    result.enumeration_complete = not (result.budget_exhausted or result.page_budget_exhausted)
    result.distinct_source_products = len(seen)
    result.foreign_series_seen = sorted(foreign)
    return result


def upsert_candidate(
    session: Session,
    discovery_run_id: int | None,
    product: ListingProduct,
    classification,
) -> tuple[YuyuteiCandidate, bool]:
    """Insert or refresh one candidate, keyed on (set_slug, product_id).

    Returns (candidate, is_new). A repeat discovery of the same source product
    updates that row in place - price, availability, name, image, rarity, code
    and classification all move with the source - and can never produce a
    second row for it.

    Unlike worker.matching.candidate_store.upsert_candidate, which preserves a
    prior match decision, the classification IS refreshed here. That is safe
    precisely because no status in this vocabulary is ever set by a human or
    ever creates a mapping: every one is a statement about current catalogue
    cardinality, so a stale one would simply be wrong. Approval, when it
    exists, will be recorded elsewhere - never by overwriting this field.
    """
    existing = session.scalars(
        select(YuyuteiCandidate).where(
            YuyuteiCandidate.set_slug == product.series,
            YuyuteiCandidate.product_id == product.product_id,
        )
    ).one_or_none()

    fields = dict(
        discovery_run_id=discovery_run_id,
        source_url=product.source_url,
        detected_card_code=product.detected_card_code,
        detected_rarity=product.detected_rarity,
        name_jp=product.name_jp,
        image_url=product.image_url,
        price_jpy=product.price_jpy,
        availability=product.availability,
        raw_listing_text=product.raw_listing_text,
        match_status=classification.match_status,
        matched_card_print_id=classification.matched_card_print_id,
        match_explanation_json=classification.explanation,
    )

    if existing is None:
        candidate = YuyuteiCandidate(
            set_slug=product.series, product_id=product.product_id, **fields
        )
        session.add(candidate)
        session.flush()
        return candidate, True

    for key, value in fields.items():
        setattr(existing, key, value)
    session.flush()
    return existing, False


def own_series_code_counts(enumeration: SlugEnumeration) -> dict[str, int]:
    """How many KEPT products carry each parsed card code.

    Kept means own-series and deduplicated, i.e. the listing result for the
    slug. Foreign-series cross-links are already gone by this point and must
    stay gone: another set's product sharing a code says nothing about how many
    products THIS set sells under it, and counting it would suppress a
    legitimate 1:1 print match. Products with no parseable code are absent -
    they are classified unmatched on the code alone.

    These are OBSERVED counts. They are a floor, not a total, unless
    `enumeration.enumeration_complete` is True, which is why the completeness
    flag travels to the classifier beside them.
    """
    counts: dict[str, int] = {}
    for product in enumeration.products:
        if product.detected_card_code:
            counts[product.detected_card_code] = counts.get(product.detected_card_code, 0) + 1
    return counts


def _slug_metrics(enumeration: SlugEnumeration, statuses: list[str], written: int) -> dict[str, Any]:
    """Everything measured for one slug. No count here is expected, configured
    or compared against a previous run - each is read off this run's data."""
    kept = enumeration.products
    codes = [p.detected_card_code for p in kept if p.detected_card_code]
    code_counts = own_series_code_counts(enumeration)
    return {
        "slug": enumeration.slug,
        "pages_fetched": len(enumeration.pages_fetched),
        "pagination_seen": enumeration.pagination_seen,
        "raw_product_anchors": enumeration.raw_product_anchors,
        "distinct_source_products": enumeration.distinct_source_products,
        "own_series_products": len(kept),
        "foreign_series_filtered": enumeration.foreign_series_filtered,
        "foreign_series_seen": enumeration.foreign_series_seen,
        "duplicate_products": enumeration.duplicate_products,
        "enumeration_complete": enumeration.enumeration_complete,
        "page_budget_exhausted": enumeration.page_budget_exhausted,
        "unfetched_pages": enumeration.unfetched_pages,
        "parsed_card_codes": len(codes),
        "unparseable_codes": len(kept) - len(codes),
        "distinct_card_codes": len(code_counts),
        "codes_with_multiple_products": sum(1 for n in code_counts.values() if n > 1),
        "candidates_with_price": sum(1 for p in kept if p.price_jpy is not None),
        "candidates_with_ambiguous_price": sum(1 for p in kept if p.price_ambiguous),
        "candidates_with_image": sum(1 for p in kept if p.image_url),
        "candidates_with_rarity": sum(1 for p in kept if p.detected_rarity),
        "candidates_with_name_jp": sum(1 for p in kept if p.name_jp),
        "candidates_with_availability": sum(1 for p in kept if p.availability),
        "unmatched": statuses.count("unmatched"),
        "family_matched": statuses.count("family_matched"),
        "print_matched": statuses.count("print_matched"),
        "identity_conflict": statuses.count("identity_conflict"),
        "candidates_written": written,
        "budget_exhausted": enumeration.budget_exhausted,
    }


# A homepage that answers with one of these, or renders one of these, is the
# source declining - the same judgement `_scrape_listing` already makes about a
# listing page, so it produces the same `denied` run rather than a new status.
# `static_403` and `challenge_or_captcha` are classify_page's names for a
# denial that arrives WITH a 200, which no status check can see.
DENIAL_CLASSIFICATIONS = frozenset({"static_403", "challenge_or_captcha"})


def _warm_up_session(page, *, discovery_run_id: int) -> None:
    """Establish the session the collector establishes, before any listing URL.

    Returns normally when the homepage gave a usable session. Otherwise raises,
    and WHICH exception is the whole point:

      * `SourceDenied` when the source declined - caught by the caller and
        recorded as the existing `denied` run status, identical to a listing
        denial. No listing URL is requested and nothing is retried.
      * `RuntimeError` for any other non-normal outcome (a navigation error, an
        unexpected status). That is not a refusal, it is a fault, so it takes
        the existing unexpected-failure path: the run is finalised `failed`
        with an `error_message` and the exception propagates, exactly as any
        other unexpected error in this function already does.

    Either way enumeration does not begin - there is no path here that warms
    unsuccessfully and continues.
    """
    step = warm_up_homepage(page)
    log_event(
        "discovery_homepage_result",
        discovery_run_id=discovery_run_id,
        http_status=step.get("http_status"),
        classification=step.get("classification"),
        error=step.get("error"),
    )
    if homepage_session_ok(step):
        return

    http_status = step.get("http_status")
    classification = step.get("classification")
    if http_status in _DENIAL_STATUSES or classification in DENIAL_CLASSIFICATIONS:
        raise SourceDenied(f"{http_status} at {HOMEPAGE_URL}")
    raise RuntimeError(
        f"homepage did not establish a usable session at {HOMEPAGE_URL}: "
        f"http_status={http_status!r} classification={classification!r} "
        f"error={step.get('error')!r}"
    )


def discover_and_persist(
    session: Session,
    page,
    slugs: list[str],
    *,
    max_products_per_slug: int = MAX_PRODUCTS_PER_SLUG,
    max_pages_per_slug: int = DEFAULT_MAX_PAGES_PER_SLUG,
    timeout_s: int = 90,
) -> dict[str, Any]:
    """Enumerate and persist every requested slug. Returns the run report.

    One run row is written up front so a crashed run is visible as `running`
    rather than absent, and each slug is committed as it completes, so a denial
    part-way through keeps the sets already enumerated.
    """
    run = YuyuteiDiscoveryRun(status="running", requested_set_slugs=list(slugs))
    session.add(run)
    session.commit()

    per_slug: dict[str, Any] = {}
    stopped_reason: str | None = None
    status = "completed"
    error_message: str | None = None
    capped: list[str] = []

    try:
        # ONE HOMEPAGE NAVIGATION, ON THIS SAME PAGE, BEFORE ANY LISTING URL.
        # Discovery used to open with a cold hit on the first category page and
        # was answered 403 on staging (run 3, 2026-09-02) while the warmed
        # posture the collector already used reached the same pages with 200.
        # A denial here ends the run before a single listing is requested.
        try:
            _warm_up_session(page, discovery_run_id=run.id)
            session_established = True
        except SourceDenied as exc:
            status = "denied"
            stopped_reason = f"source_denied: {exc}"[:255]
            session_established = False

        for index, slug in enumerate(slugs if session_established else []):
            if index:
                time.sleep(settings.YUYUTEI_REQUEST_DELAY_MS / 1000)
            try:
                enumeration = enumerate_slug(
                    page,
                    slug,
                    max_products=max_products_per_slug,
                    max_pages=max_pages_per_slug,
                    timeout_s=timeout_s,
                )
            except SourceDenied as exc:
                # The source declined. Stop the whole run - not just this slug -
                # and never retry.
                status = "denied"
                stopped_reason = f"source_denied: {exc}"[:255]
                break

            # Counted across the WHOLE own-series result before anything is
            # classified: a per-product decision cannot know it has a sibling
            # until every row of the slug has been read.
            code_counts = own_series_code_counts(enumeration)

            statuses: list[str] = []
            written = 0
            for product in enumeration.products:
                classification = classify_card_code(
                    session,
                    product.detected_card_code,
                    source_product_count=code_counts.get(product.detected_card_code, 1),
                    source_listing_complete=enumeration.enumeration_complete,
                )
                upsert_candidate(session, run.id, product, classification)
                statuses.append(classification.match_status)
                written += 1
            session.commit()

            per_slug[slug] = _slug_metrics(enumeration, statuses, written)
            if enumeration.budget_exhausted:
                capped.append(slug)
    except Exception as exc:  # noqa: BLE001 - recorded on the run, then re-raised
        status = "failed"
        error_message = str(exc)[:2000]
        _finalize(run, session, status, stopped_reason, error_message, per_slug)
        raise

    if status == "completed" and capped:
        stopped_reason = ("max_products_per_slug_reached: " + ",".join(capped))[:255]
    _finalize(run, session, status, stopped_reason, error_message, per_slug)

    return {
        "discovery_run_id": run.id,
        "status": run.status,
        "requested_set_slugs": list(slugs),
        "max_products_per_slug": max_products_per_slug,
        "max_pages_per_slug": max_pages_per_slug,
        "request_delay_ms": settings.YUYUTEI_REQUEST_DELAY_MS,
        "stopped_reason": stopped_reason,
        "error_message": error_message,
        "totals": {
            "pages_fetched": run.pages_fetched,
            "products_seen": run.products_seen,
            "candidates_written": run.candidates_written,
            "foreign_series_filtered": run.foreign_series_filtered,
            "duplicate_products": run.duplicate_products,
            "unparseable_codes": run.unparseable_codes,
        },
        "per_slug": per_slug,
    }


def _finalize(
    run: YuyuteiDiscoveryRun,
    session: Session,
    status: str,
    stopped_reason: str | None,
    error_message: str | None,
    per_slug: dict[str, Any],
) -> None:
    """Roll the per-slug measurements up onto the run row and close it."""
    run.status = status
    run.stopped_reason = stopped_reason
    run.error_message = error_message
    run.finished_at = datetime.now(timezone.utc)
    run.pages_fetched = sum(m["pages_fetched"] for m in per_slug.values())
    run.products_seen = sum(m["own_series_products"] for m in per_slug.values())
    run.candidates_written = sum(m["candidates_written"] for m in per_slug.values())
    run.foreign_series_filtered = sum(m["foreign_series_filtered"] for m in per_slug.values())
    run.duplicate_products = sum(m["duplicate_products"] for m in per_slug.values())
    run.unparseable_codes = sum(m["unparseable_codes"] for m in per_slug.values())
    # Reassigned rather than mutated in place: a plain dict assignment into a
    # JSON column that was already loaded would not always be seen as dirty.
    run.per_slug_metrics_json = dict(per_slug)
    session.commit()


def main() -> None:
    from playwright.sync_api import sync_playwright

    from yuyutei_collector.db import SessionLocal

    parser = argparse.ArgumentParser(
        description="Yuyu-Tei listing discovery. Writes candidates only - never mappings, "
        "observations or approvals."
    )
    parser.add_argument("--slugs", required=True, help="comma-separated, e.g. op01,op13,eb01")
    parser.add_argument("--max-products-per-slug", type=int, default=MAX_PRODUCTS_PER_SLUG)
    parser.add_argument("--max-pages-per-slug", type=int, default=DEFAULT_MAX_PAGES_PER_SLUG)
    args = parser.parse_args()

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    if not slugs:
        parser.error("--slugs must name at least one category slug")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
        )
        context = browser.new_context()
        page = context.new_page()
        session = SessionLocal()
        try:
            report = discover_and_persist(
                session,
                page,
                slugs,
                max_products_per_slug=args.max_products_per_slug,
                max_pages_per_slug=args.max_pages_per_slug,
            )
        finally:
            session.close()
            context.close()
            browser.close()

    # One compact summary line per slug, then one machine-readable object -
    # Railway ships each stdout line as its own log entry.
    for metrics in report["per_slug"].values():
        log_event("discovery_set_complete", **metrics)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
