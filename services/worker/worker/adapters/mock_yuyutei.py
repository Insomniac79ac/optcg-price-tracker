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

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "yuyutei_sample.json"


class MockYuyuTeiAdapter(SourceAdapter):
    source_name = "yuyutei"

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
            parser_version="mock-yuyutei-v1",
        )

    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        data = json.loads(snapshot.raw_content)
        if not data:
            return []

        observations = []
        stock_status = data.get("stock_status")

        if "sell_price" in data:
            observations.append(
                PriceObservationData(
                    price_type="sell",
                    price_jpy=data["sell_price"],
                    observed_at=snapshot.fetched_at,
                    stock_status=stock_status,
                )
            )

        if "buy_price" in data:
            observations.append(
                PriceObservationData(
                    price_type="buy",
                    price_jpy=data["buy_price"],
                    observed_at=snapshot.fetched_at,
                    stock_status=stock_status,
                )
            )

        return observations
