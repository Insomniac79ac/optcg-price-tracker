import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Callable

import httpx
from bs4 import BeautifulSoup

from worker.adapters.base import (
    CardMappingLike,
    PriceObservationData,
    RawSnapshotData,
    SourceAdapter,
)
from worker.settings import settings

logger = logging.getLogger(__name__)

PARSER_VERSION = "yuyutei-live-v1"

SOLD_OUT_MARKERS = ("売り切れ", "在庫なし", "sold out")


class YuyuTeiFetchError(Exception):
    """Raised when a Yuyu-Tei product page cannot be fetched."""


def _extract_price(soup: BeautifulSoup, box_class: str) -> int | None:
    box = soup.select_one(f".{box_class} .num")
    if box is None:
        return None
    digits = re.sub(r"[^\d]", "", box.get_text())
    return int(digits) if digits else None


def _extract_stock_status(soup: BeautifulSoup) -> str | None:
    el = soup.select_one(".stock_status")
    if el is None:
        return None
    text = el.get_text(strip=True)
    if not text:
        return None
    if any(marker in text for marker in SOLD_OUT_MARKERS):
        return "out_of_stock"
    return "in_stock"


class YuyuTeiAdapter(SourceAdapter):
    """Fetches and parses Yuyu-Tei product pages for URLs already stored in
    source_card_mappings. Does not discover or crawl new URLs."""

    source_name = "yuyutei"

    def __init__(
        self,
        client: httpx.Client | None = None,
        request_delay_ms: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ):
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=True)
        self._request_delay_ms = (
            request_delay_ms if request_delay_ms is not None else settings.YUYUTEI_REQUEST_DELAY_MS
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

    def fetch_card(self, mapping: CardMappingLike) -> RawSnapshotData:
        if not mapping.source_url:
            raise YuyuTeiFetchError(f"mapping {mapping!r} has no source_url")

        self._throttle()
        try:
            response = self._client.get(mapping.source_url)
        finally:
            self._last_request_at = self._monotonic_fn()

        raw_content = response.text
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

        return RawSnapshotData(
            source_url=mapping.source_url,
            fetched_at=datetime.now(timezone.utc),
            http_status=response.status_code,
            content_hash=content_hash,
            raw_content=raw_content,
            parser_version=PARSER_VERSION,
        )

    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        if snapshot.http_status != 200 or not snapshot.raw_content:
            return []

        soup = BeautifulSoup(snapshot.raw_content, "html.parser")
        stock_status = _extract_stock_status(soup)
        observations: list[PriceObservationData] = []

        sell_price = _extract_price(soup, "sell_price_box")
        if sell_price is not None:
            observations.append(
                PriceObservationData(
                    price_type="sell",
                    price_jpy=sell_price,
                    observed_at=snapshot.fetched_at,
                    stock_status=stock_status,
                )
            )

        buy_price = _extract_price(soup, "buy_price_box")
        if buy_price is not None:
            observations.append(
                PriceObservationData(
                    price_type="buy",
                    price_jpy=buy_price,
                    observed_at=snapshot.fetched_at,
                    stock_status=stock_status,
                )
            )

        return observations

    def close(self) -> None:
        self._client.close()
