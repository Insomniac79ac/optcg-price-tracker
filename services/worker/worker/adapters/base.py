from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class CardMappingLike(Protocol):
    """Structural type for a source_card_mappings row (or anything shaped like one)."""

    source_card_id: str
    source_url: str | None


@dataclass
class RawSnapshotData:
    """Raw snapshot-like data returned by `fetch_card`, prior to persistence."""

    source_url: str
    fetched_at: datetime
    http_status: int
    content_hash: str
    raw_content: str
    parser_version: str


@dataclass
class PriceObservationData:
    """A single normalized price observation returned by `parse_snapshot`."""

    price_type: str
    price_jpy: int
    observed_at: datetime
    condition_label: str | None = None
    stock_status: str | None = None
    listing_count: int | None = None


class SourceAdapter(ABC):
    source_name: str

    @abstractmethod
    def fetch_card(self, mapping: CardMappingLike) -> RawSnapshotData:
        """Fetch (or, in mock mode, look up) raw data for a single card mapping."""
        raise NotImplementedError

    @abstractmethod
    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        """Turn a raw snapshot into normalized price observations."""
        raise NotImplementedError
