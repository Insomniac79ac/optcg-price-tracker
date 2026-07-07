import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from worker.adapters.base import (
    CardMappingLike,
    PriceObservationData,
    RawSnapshotData,
    SourceAdapter,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "snkrdunk_sample.json"


class MockSnkrdunkAdapter(SourceAdapter):
    source_name = "snkrdunk"

    def __init__(self, fixture_path: Path = FIXTURE_PATH):
        self._fixtures = json.loads(fixture_path.read_text())

    def fetch_card(self, mapping: CardMappingLike) -> RawSnapshotData:
        data = self._fixtures.get(mapping.source_card_id)
        raw_content = json.dumps(data) if data is not None else "{}"
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()

        return RawSnapshotData(
            source_url=mapping.source_url or "",
            fetched_at=datetime.now(timezone.utc),
            http_status=200 if data is not None else 404,
            content_hash=content_hash,
            raw_content=raw_content,
            parser_version="mock-snkrdunk-v1",
        )

    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        data = json.loads(snapshot.raw_content)
        if not data:
            return []

        observations = []

        if "floor_price" in data:
            observations.append(
                PriceObservationData(
                    price_type="floor",
                    price_jpy=data["floor_price"],
                    observed_at=snapshot.fetched_at,
                    listing_count=data.get("listing_count"),
                )
            )

        for sold in data.get("sold_prices", []):
            observations.append(
                PriceObservationData(
                    price_type="sold",
                    price_jpy=sold["price_jpy"],
                    observed_at=datetime.fromisoformat(sold["observed_at"].replace("Z", "+00:00")),
                )
            )

        return observations
