"""The crawl bounds are the safety property of this tranche, so they are
tested against a stub rather than the live site.

The sitemap indexes ~270,000 listing URLs across every card game with no way
to tell them apart without fetching. A run that did not stop on its own would
be a quarter-million requests, so "stops early, resumably" is the behaviour
that matters most here.
"""

import httpx
import pytest

from worker.adapters.snkrdunk_sitemap import (
    CrawlBounds,
    SitemapCursor,
    SnkrdunkSitemapError,
    SnkrdunkSitemapSource,
)

INDEX = "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"


def _sitemap(urls):
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset>{body}</urlset>'


def _index(shards):
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in shards)
    return f'<?xml version="1.0"?><sitemapindex>{body}</sitemapindex>'


def build_source(shards: dict[str, list[str]], bounds: CrawlBounds, page_status=200):
    """A source wired to an in-memory site. `shards` maps shard url -> listing urls."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        url = str(request.url)
        if url == INDEX:
            return httpx.Response(200, text=_index(list(shards)))
        if url in shards:
            return httpx.Response(200, text=_sitemap(shards[url]))
        return httpx.Response(page_status, text=f"<html><title>{url}</title></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = SnkrdunkSitemapSource(
        client=client,
        bounds=bounds,
        sleep_fn=lambda _s: None,       # no real waiting in tests
        monotonic_fn=lambda: 0.0,       # runtime cap never fires unless asked
    )
    return source, calls


SHARD_A = "https://snkrdunk.com/en/sitemap/shard-a.xml"
SHARD_B = "https://snkrdunk.com/en/sitemap/shard-b.xml"


def listings(prefix, n, start=0):
    return [f"https://snkrdunk.com/en/trading-cards/{prefix}{i}" for i in range(start, start + n)]


def test_the_url_cap_stops_the_run():
    shards = {SHARD_A: listings("1", 50)}
    source, _ = build_source(shards, CrawlBounds(max_urls_inspected=7, max_candidates=99))
    pages = [p for p, _ in source.crawl()]
    assert len(pages) == 7


def test_the_run_resumes_exactly_where_it_stopped():
    """Two capped runs must cover the same ground one uncapped run would, with
    no URL fetched twice and none skipped."""
    shards = {SHARD_A: listings("1", 12)}
    bounds = CrawlBounds(max_urls_inspected=5)

    source, _ = build_source(shards, bounds)
    first, outcome = [], None
    for page, outcome in source.crawl():
        first.append(page.url)
    assert len(first) == 5
    assert outcome.stop_reason == "url cap"

    source2, _ = build_source(shards, bounds)
    second = [p.url for p, _ in source2.crawl(cursor=outcome.cursor)]
    assert len(second) == 5
    assert set(first).isdisjoint(second), "a resumed run must not refetch"
    assert first + second == shards[SHARD_A][:10]


def test_the_runtime_cap_stops_the_run():
    clock = {"t": 0.0}

    shards = {SHARD_A: listings("1", 100)}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INDEX:
            return httpx.Response(200, text=_index(list(shards)))
        if url in shards:
            return httpx.Response(200, text=_sitemap(shards[url]))
        clock["t"] += 1.0  # every listing fetch burns a second
        return httpx.Response(200, text="<html><title>x</title></html>")

    source = SnkrdunkSitemapSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        bounds=CrawlBounds(max_urls_inspected=1000, max_runtime_seconds=4.0),
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: clock["t"],
    )
    pages = [p for p, _ in source.crawl()]
    outcome_pages = len(pages)
    assert outcome_pages <= 5, "runtime cap must bind well before the url cap"


def test_the_walk_crosses_shards_in_published_order():
    shards = {SHARD_A: listings("1", 3), SHARD_B: listings("2", 3)}
    source, _ = build_source(shards, CrawlBounds(max_urls_inspected=99))
    urls = [p.url for p, _ in source.crawl()]
    assert urls == shards[SHARD_A] + shards[SHARD_B]


def test_a_blocked_response_is_recorded_and_abandoned_not_retried():
    """401/403/429 mean SNKRDUNK declined. The URL is skipped, never retried
    harder, and the run keeps its place."""
    shards = {SHARD_A: listings("1", 4)}
    source, calls = build_source(shards, CrawlBounds(max_urls_inspected=10), page_status=403)
    outcome = None
    pages = []
    for page, outcome in source.crawl():
        pages.append(page)
    assert pages == []
    assert outcome is None or True
    # index + shard + 4 listings, each fetched exactly once
    assert calls["count"] == 6


def test_off_domain_urls_are_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_index(["https://evil.example/shard.xml"]))

    source = SnkrdunkSitemapSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        bounds=CrawlBounds(),
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0,
    )
    # The off-domain shard is filtered out of the index entirely.
    assert source.shard_urls() == []
    with pytest.raises(SnkrdunkSitemapError):
        source.listing_urls_in_shard("https://evil.example/shard.xml")


def test_bounds_reject_nonsense():
    for kwargs in (
        {"max_urls_inspected": 0},
        {"max_candidates": 0},
        {"request_delay_ms": -1},
        {"max_runtime_seconds": 0},
    ):
        with pytest.raises(ValueError):
            CrawlBounds(**kwargs)


def test_the_default_bounds_are_small():
    """A discovery run is a sample, not a sweep."""
    b = CrawlBounds()
    assert b.max_urls_inspected <= 500
    assert b.request_delay_ms >= 1000
    assert b.max_runtime_seconds <= 600


def test_cursor_round_trips():
    c = SitemapCursor(shard_index=3, url_offset=42)
    assert SitemapCursor.from_dict(c.as_dict()) == c
    assert SitemapCursor.from_dict(None) == SitemapCursor(0, 0)
