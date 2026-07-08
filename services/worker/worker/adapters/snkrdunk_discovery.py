import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from worker.adapters.base import RawSnapshotData
from worker.settings import settings

logger = logging.getLogger(__name__)

PARSER_VERSION = "snkrdunk-discovery-v1"
ALLOWED_HOST = "snkrdunk.com"

# Statuses that indicate SNKRDUNK blocked or rate-limited the request rather
# than serving the page. We never try to work around these - just record and
# stop trying that page.
BLOCKED_STATUS_CODES = frozenset({401, 403, 429})


def is_blocked_response(status_code: int) -> bool:
    return status_code in BLOCKED_STATUS_CODES


class SnkrdunkDiscoveryError(Exception):
    """Raised when a discovery request would leave the allowed snkrdunk.com domain."""


@dataclass
class SnkrdunkCandidateData:
    """A single public listing/product link parsed off a SNKRDUNK page."""

    source_url: str
    title: str | None
    price_jpy: int | None
    image_url: str | None
    listing_count: int | None
    condition_label: str | None
    raw_text: str


@dataclass
class SnkrdunkPageResult:
    candidates: list[SnkrdunkCandidateData]
    next_page_url: str | None


def _is_allowed_host(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return host == ALLOWED_HOST or host.endswith(f".{ALLOWED_HOST}")


def _extract_digits(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


class SnkrdunkDiscoveryAdapter:
    """Fetches SNKRDUNK pages that are already known-good seed/pagination URLs
    and parses out public product links. Does not discover or crawl beyond
    the seed list and any pagination links explicitly present on the page,
    and refuses to fetch anything outside snkrdunk.com."""

    source_name = "snkrdunk"

    def __init__(
        self,
        client: httpx.Client | None = None,
        request_delay_ms: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ):
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=True)
        self._request_delay_ms = (
            request_delay_ms if request_delay_ms is not None else settings.SNKRDUNK_REQUEST_DELAY_MS
        )
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        delay_seconds = self._request_delay_ms / 1000
        elapsed = self._monotonic_fn() - self._last_request_at
        remaining = delay_seconds - elapsed
        if remaining > 0:
            self._sleep_fn(remaining)

    def fetch_page(self, url: str) -> RawSnapshotData:
        if not _is_allowed_host(url):
            raise SnkrdunkDiscoveryError(f"refusing to fetch off-domain url: {url!r}")

        self._throttle()
        try:
            response = self._client.get(url)
        finally:
            self._last_request_at = self._monotonic_fn()

        raw_content = response.text
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

        return RawSnapshotData(
            source_url=url,
            fetched_at=datetime.now(timezone.utc),
            http_status=response.status_code,
            content_hash=content_hash,
            raw_content=raw_content,
            parser_version=PARSER_VERSION,
        )

    def parse_search_page(self, snapshot: RawSnapshotData) -> SnkrdunkPageResult:
        if snapshot.http_status != 200 or not snapshot.raw_content:
            return SnkrdunkPageResult(candidates=[], next_page_url=None)

        soup = BeautifulSoup(snapshot.raw_content, "html.parser")
        candidates: list[SnkrdunkCandidateData] = []

        for item in soup.select(".item-card"):
            link = item.select_one("a.item-link")
            href = link.get("href") if link else None
            if not href:
                continue

            source_url = urljoin(snapshot.source_url, href)
            if not _is_allowed_host(source_url):
                logger.info("Skipping off-domain candidate link %s", source_url)
                continue

            title_el = item.select_one(".item-title")
            price_el = item.select_one(".item-price")
            image_el = item.select_one(".item-image")
            listing_el = item.select_one(".item-listing-count")
            condition_el = item.select_one(".item-condition")

            candidates.append(
                SnkrdunkCandidateData(
                    source_url=source_url,
                    title=title_el.get_text(strip=True) if title_el else None,
                    price_jpy=_extract_digits(price_el.get_text()) if price_el else None,
                    image_url=image_el.get("src") if image_el else None,
                    listing_count=_extract_digits(listing_el.get_text()) if listing_el else None,
                    condition_label=condition_el.get_text(strip=True) if condition_el else None,
                    raw_text=item.get_text(" ", strip=True),
                )
            )

        next_page_url = None
        next_link = soup.select_one("a.pagination-next")
        if next_link and next_link.get("href"):
            candidate_next_url = urljoin(snapshot.source_url, next_link["href"])
            if _is_allowed_host(candidate_next_url):
                next_page_url = candidate_next_url
            else:
                logger.info("Ignoring off-domain pagination link %s", candidate_next_url)

        return SnkrdunkPageResult(candidates=candidates, next_page_url=next_page_url)

    def close(self) -> None:
        self._client.close()
