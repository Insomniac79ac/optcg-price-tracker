"""Bounded discovery of SNKRDUNK One Piece listings, via their published sitemap.

WHY THE SITEMAP, AND ONLY AS A FALLBACK. The seed this project shipped with -
`/trading-cards/search?category=one-piece-card-game` - now returns 404, which
is why `snkrdunk_candidates` sat at zero. The 2026-08-27 survey looked for a
replacement in this order and found:

  A. a working public One Piece browse/search page - NONE. `/en/search` returns
     200 but is a client-rendered shell: no results, no embedded payload, no
     card codes in the HTML. Its data comes from `/en/v1/*`, which their
     robots.txt disallows, so it is out of bounds.
  B. listing URLs discoverable from other public HTML - NONE. A listing page
     links to no other listing.
  C. the published sitemap - available, and used here.

WHAT THE SITEMAP DOES AND DOES NOT GIVE. `sitemap-index-en-product-trading-card
-single.xml` indexes roughly 270,000 listing URLs across EVERY card game, as
opaque numeric ids with no category. There is no way to tell a One Piece
listing from a Pokemon one without fetching it. That is the whole reason this
module is built around limits rather than completeness.

THE BOUNDS ARE THE POINT. Every run is capped on four independent axes - URLs
inspected, candidates produced, per-request delay, and wall-clock runtime - and
whichever binds first stops the run. A run is expected to end truncated; that
is the normal outcome, not an error. Progress is reported as a `SitemapCursor`
so the next run resumes where this one stopped instead of re-walking the same
prefix, which is what makes a small cap per run add up over time.

This is emphatically NOT sequential-id probing: the only URLs ever fetched are
ones the publisher lists in their own sitemap, in the order they list them.
"""

from __future__ import annotations

import gzip
import io
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

import httpx

logger = logging.getLogger(__name__)

ALLOWED_HOST = "snkrdunk.com"
SITEMAP_INDEX_URL = (
    "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"
)

# Statuses that mean SNKRDUNK declined to serve the page. Never worked around -
# recorded, and that URL is abandoned.
BLOCKED_STATUS_CODES = frozenset({401, 403, 429})

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


class SnkrdunkSitemapError(Exception):
    """Raised when a fetch would leave snkrdunk.com."""


def _is_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).netloc or "").lower()
    return host == ALLOWED_HOST or host.endswith(f".{ALLOWED_HOST}")


@dataclass(frozen=True)
class SitemapCursor:
    """Where the previous run stopped: shard index, and offset within it.

    Stored by the caller and handed back next time. Plain integers rather than
    a URL so a re-published sitemap shard cannot silently change its meaning.
    """

    shard_index: int = 0
    url_offset: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"shard_index": self.shard_index, "url_offset": self.url_offset}

    @classmethod
    def from_dict(cls, data: dict | None) -> "SitemapCursor":
        if not data:
            return cls()
        return cls(
            shard_index=int(data.get("shard_index", 0)),
            url_offset=int(data.get("url_offset", 0)),
        )


@dataclass
class CrawlBounds:
    """Four independent caps. Whichever binds first ends the run.

    Defaults are deliberately small: a discovery run is a sample, and the
    catalogue is walked across many runs rather than in one sitting.
    """

    max_urls_inspected: int = 200
    max_candidates: int = 50
    request_delay_ms: int = 1500
    max_runtime_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_urls_inspected <= 0:
            raise ValueError("max_urls_inspected must be positive")
        if self.max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if self.request_delay_ms < 0:
            raise ValueError("request_delay_ms must not be negative")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive")


@dataclass
class FetchedPage:
    url: str
    http_status: int
    body: str


@dataclass
class CrawlOutcome:
    """What a bounded run did, including why it stopped."""

    pages_fetched: int = 0
    urls_inspected: int = 0
    blocked_responses: int = 0
    stop_reason: str = "exhausted"
    cursor: SitemapCursor = field(default_factory=SitemapCursor)


class SnkrdunkSitemapSource:
    """Walks the published sitemap and yields listing pages, under hard caps."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        bounds: CrawlBounds | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        sitemap_index_url: str = SITEMAP_INDEX_URL,
    ):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                # A plain, honest browser UA. No cookie replay, no captcha
                # handling, nothing that works around a protection.
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/151.0 Safari/537.36"
                ),
                "Accept-Language": "en",
            },
        )
        self.bounds = bounds or CrawlBounds()
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._sitemap_index_url = sitemap_index_url
        self._last_request_at: float | None = None

    # --- fetching -----------------------------------------------------------

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        remaining = (self.bounds.request_delay_ms / 1000) - (
            self._monotonic_fn() - self._last_request_at
        )
        if remaining > 0:
            self._sleep_fn(remaining)

    def _get(self, url: str) -> httpx.Response:
        if not _is_allowed(url):
            raise SnkrdunkSitemapError(f"refusing to fetch off-domain url: {url!r}")
        self._throttle()
        try:
            return self._client.get(url)
        finally:
            self._last_request_at = self._monotonic_fn()

    # --- sitemap ------------------------------------------------------------

    def shard_urls(self) -> list[str]:
        """The child sitemap shards, in the order the publisher lists them."""
        response = self._get(self._sitemap_index_url)
        if response.status_code != 200:
            logger.warning("sitemap index returned %s", response.status_code)
            return []
        return [u for u in _LOC_RE.findall(response.text) if _is_allowed(u)]

    def listing_urls_in_shard(self, shard_url: str) -> list[str]:
        """Listing URLs in one shard. Shards are served gzipped."""
        response = self._get(shard_url)
        if response.status_code != 200:
            logger.warning("sitemap shard %s returned %s", shard_url, response.status_code)
            return []
        raw = response.content
        if shard_url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except OSError:
                logger.warning("shard %s is not valid gzip", shard_url)
                return []
        text = raw.decode("utf-8", "replace")
        return [u for u in _LOC_RE.findall(text) if _is_allowed(u)]

    # --- the bounded walk ---------------------------------------------------

    def crawl(
        self, cursor: SitemapCursor | None = None
    ) -> Iterator[tuple[FetchedPage, CrawlOutcome]]:
        """Yield (page, outcome) for each listing fetched, until a cap binds.

        The outcome carried alongside each page is live: its `cursor` always
        points at the NEXT unvisited URL, so a caller that stops consuming
        early still has a correct checkpoint.
        """
        cursor = cursor or SitemapCursor()
        outcome = CrawlOutcome(cursor=cursor)
        started = self._monotonic_fn()

        shards = self.shard_urls()
        if not shards:
            outcome.stop_reason = "no sitemap shards available"
            return

        shard_index = cursor.shard_index
        url_offset = cursor.url_offset

        while shard_index < len(shards):
            if self._monotonic_fn() - started >= self.bounds.max_runtime_seconds:
                outcome.stop_reason = "runtime cap"
                outcome.cursor = SitemapCursor(shard_index, url_offset)
                return

            urls = self.listing_urls_in_shard(shards[shard_index])
            if url_offset >= len(urls):
                shard_index += 1
                url_offset = 0
                continue

            for index in range(url_offset, len(urls)):
                if outcome.urls_inspected >= self.bounds.max_urls_inspected:
                    outcome.stop_reason = "url cap"
                    outcome.cursor = SitemapCursor(shard_index, index)
                    return
                if self._monotonic_fn() - started >= self.bounds.max_runtime_seconds:
                    outcome.stop_reason = "runtime cap"
                    outcome.cursor = SitemapCursor(shard_index, index)
                    return

                url = urls[index]
                outcome.urls_inspected += 1
                response = self._get(url)
                if response.status_code in BLOCKED_STATUS_CODES:
                    # Recorded and abandoned - never retried harder.
                    outcome.blocked_responses += 1
                    logger.info("snkrdunk declined %s (%s)", url, response.status_code)
                    outcome.cursor = SitemapCursor(shard_index, index + 1)
                    continue

                outcome.pages_fetched += 1
                outcome.cursor = SitemapCursor(shard_index, index + 1)
                yield FetchedPage(url=url, http_status=response.status_code,
                                  body=response.text if response.status_code == 200 else ""), outcome

            shard_index += 1
            url_offset = 0

        outcome.stop_reason = "exhausted"
        outcome.cursor = SitemapCursor(shard_index, 0)

    def crawl_urls(self, urls: list[str]) -> Iterator[tuple[FetchedPage, CrawlOutcome]]:
        """Fetch an explicit, already-chosen list of listing URLs.

        Same throttle, same caps, same blocked-response handling as `crawl` -
        only the choice of URLs differs, and that choice must come from the
        published sitemap (see snkrdunk_anchor_plan). The sequential walk above
        is untouched and remains the fallback when no anchors exist.
        """
        outcome = CrawlOutcome()
        started = self._monotonic_fn()

        for url in urls:
            if outcome.urls_inspected >= self.bounds.max_urls_inspected:
                outcome.stop_reason = "url cap"
                return
            if self._monotonic_fn() - started >= self.bounds.max_runtime_seconds:
                outcome.stop_reason = "runtime cap"
                return

            outcome.urls_inspected += 1
            response = self._get(url)
            if response.status_code in BLOCKED_STATUS_CODES:
                outcome.blocked_responses += 1
                logger.info("snkrdunk declined %s (%s)", url, response.status_code)
                continue
            outcome.pages_fetched += 1
            yield FetchedPage(
                url=url,
                http_status=response.status_code,
                body=response.text if response.status_code == 200 else "",
            ), outcome

        outcome.stop_reason = "plan exhausted"

    def close(self) -> None:
        self._client.close()
