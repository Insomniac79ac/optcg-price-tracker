from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from worker.adapters.base import PriceObservationData, RawSnapshotData
from worker.adapters.yuyutei import YuyuTeiAdapter, YuyuTeiFetchError
from worker.jobs.refresh_prices import refresh_prices
from worker.models import Card, PriceObservation, RawSnapshot, Source, SourceCardMapping

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "yuyutei_product_sample.html"
FIXTURE_HTML = FIXTURE_PATH.read_text(encoding="utf-8")

NO_BUY_PRICE_HTML = """
<div class="pdt_detail">
  <div class="price_box sell_price_box">
    <p class="price_value"><span class="num">450</span>円(税込)</p>
    <p class="stock_status">残り1点</p>
  </div>
</div>
"""

SOLD_OUT_HTML = """
<div class="pdt_detail">
  <div class="price_box sell_price_box">
    <p class="price_value"><span class="num">1,200</span>円(税込)</p>
    <p class="stock_status">売り切れ</p>
  </div>
</div>
"""


def make_mapping(source_url: str = "https://yuyu-tei.jp/sell/opc/card/op01/10001"):
    return SimpleNamespace(source_card_id="OP01-001", source_url=source_url)


def make_adapter(handler, **kwargs) -> YuyuTeiAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return YuyuTeiAdapter(client=client, **kwargs)


def html_handler(html: str, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=html)

    return handler


def test_fetch_and_parse_extracts_sell_buy_price_and_stock_status():
    adapter = make_adapter(html_handler(FIXTURE_HTML))
    mapping = make_mapping()

    snapshot = adapter.fetch_card(mapping)
    assert snapshot.http_status == 200
    assert snapshot.source_url == mapping.source_url
    assert snapshot.parser_version == "yuyutei-live-v1"

    observations = adapter.parse_snapshot(snapshot)
    by_type = {obs.price_type: obs for obs in observations}

    assert by_type["sell"].price_jpy == 1200
    assert by_type["sell"].stock_status == "in_stock"
    assert by_type["buy"].price_jpy == 800
    assert by_type["buy"].stock_status == "in_stock"


def test_parse_snapshot_handles_missing_buy_price():
    adapter = make_adapter(html_handler(NO_BUY_PRICE_HTML))
    snapshot = adapter.fetch_card(make_mapping())

    observations = adapter.parse_snapshot(snapshot)

    assert len(observations) == 1
    assert observations[0].price_type == "sell"
    assert observations[0].price_jpy == 450


def test_parse_snapshot_detects_sold_out_stock_status():
    adapter = make_adapter(html_handler(SOLD_OUT_HTML))
    snapshot = adapter.fetch_card(make_mapping())

    observations = adapter.parse_snapshot(snapshot)

    assert observations[0].stock_status == "out_of_stock"


def test_parse_snapshot_returns_no_observations_for_non_200_status():
    adapter = make_adapter(html_handler(FIXTURE_HTML, status_code=404))
    snapshot = adapter.fetch_card(make_mapping())

    assert snapshot.http_status == 404
    assert adapter.parse_snapshot(snapshot) == []


def test_fetch_card_raises_when_mapping_has_no_source_url():
    adapter = make_adapter(html_handler(FIXTURE_HTML))
    mapping = make_mapping(source_url=None)

    with pytest.raises(YuyuTeiFetchError):
        adapter.fetch_card(mapping)


def test_fetch_card_does_not_sleep_on_first_request():
    sleep_calls = []
    adapter = make_adapter(
        html_handler(FIXTURE_HTML),
        request_delay_ms=100,
        sleep_fn=sleep_calls.append,
        monotonic_fn=iter([1000.0, 1000.0]).__next__,
    )

    adapter.fetch_card(make_mapping())

    assert sleep_calls == []


def test_fetch_card_rate_limits_between_consecutive_requests():
    sleep_calls = []
    # First request finishes at t=1000.0. The second request's throttle check
    # fires 10ms later, so with a 100ms delay we expect a ~90ms sleep.
    clock = iter([1000.0, 1000.01, 1000.02])
    adapter = make_adapter(
        html_handler(FIXTURE_HTML),
        request_delay_ms=100,
        sleep_fn=sleep_calls.append,
        monotonic_fn=lambda: next(clock),
    )
    mapping = make_mapping()

    adapter.fetch_card(mapping)
    adapter.fetch_card(mapping)

    assert sleep_calls == [pytest.approx(0.09)]


class StubAdapter:
    """Minimal SourceAdapter stand-in for exercising the refresh job without
    real network calls."""

    def __init__(self, source_name: str, fail_for: set[str] | None = None):
        self.source_name = source_name
        self._fail_for = fail_for or set()

    def fetch_card(self, mapping) -> RawSnapshotData:
        if mapping.source_card_id in self._fail_for:
            raise YuyuTeiFetchError(f"boom: {mapping.source_card_id}")
        return RawSnapshotData(
            source_url=mapping.source_url or "",
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            content_hash="deadbeef",
            raw_content="<html></html>",
            parser_version="stub-v1",
        )

    def parse_snapshot(self, snapshot: RawSnapshotData) -> list[PriceObservationData]:
        return [
            PriceObservationData(
                price_type="sell",
                price_jpy=1000,
                observed_at=snapshot.fetched_at,
                stock_status="in_stock",
            )
        ]


def seed_source_and_card(db_session, source_name: str, card_code: str) -> tuple[Source, Card]:
    source = Source(name=source_name, base_url=f"https://{source_name}.example")
    card = Card(
        card_code=card_code, name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(source)
    db_session.add(card)
    db_session.flush()
    return source, card


def make_source_card_mapping(db_session, source: Source, card: Card, source_card_id: str) -> SourceCardMapping:
    mapping = SourceCardMapping(
        card_id=card.id,
        source_id=source.id,
        source_card_id=source_card_id,
        source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{source_card_id}",
    )
    db_session.add(mapping)
    db_session.flush()
    return mapping


def test_live_mode_skips_unsupported_sources_safely(db_session):
    yuyutei_source, yuyutei_card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    snkrdunk_source, snkrdunk_card = seed_source_and_card(db_session, "snkrdunk", "OP01-002")
    make_source_card_mapping(db_session, yuyutei_source, yuyutei_card, "OP01-001")
    make_source_card_mapping(db_session, snkrdunk_source, snkrdunk_card, "OP01-002")

    # Simulates SCRAPING_MODE=live, where only yuyutei has a live adapter.
    adapters = {"yuyutei": StubAdapter("yuyutei")}

    processed = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert processed == 1
    observations = db_session.query(PriceObservation).all()
    assert len(observations) == 1
    assert observations[0].card_id == yuyutei_card.id


def test_failed_fetch_does_not_crash_refresh_job(db_session):
    source, card_ok = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    card_fail = Card(
        card_code="OP01-002", name_en="Test Card 2", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(card_fail)
    db_session.flush()
    make_source_card_mapping(db_session, source, card_fail, "OP01-002")
    make_source_card_mapping(db_session, source, card_ok, "OP01-001")

    adapters = {"yuyutei": StubAdapter("yuyutei", fail_for={"OP01-002"})}

    processed = refresh_prices(limit=10, db=db_session, adapters=adapters)

    assert processed == 1
    observations = db_session.query(PriceObservation).all()
    assert len(observations) == 1
    assert observations[0].card_id == card_ok.id


def test_dry_run_creates_no_database_rows(db_session):
    source, card = seed_source_and_card(db_session, "yuyutei", "OP01-001")
    make_source_card_mapping(db_session, source, card, "OP01-001")

    adapters = {"yuyutei": StubAdapter("yuyutei")}

    processed = refresh_prices(limit=10, db=db_session, adapters=adapters, dry_run=True)

    assert processed == 1
    assert db_session.query(RawSnapshot).count() == 0
    assert db_session.query(PriceObservation).count() == 0
