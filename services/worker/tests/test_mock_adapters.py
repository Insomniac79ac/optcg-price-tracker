from types import SimpleNamespace

from worker.adapters.mock_snkrdunk import MockSnkrdunkAdapter
from worker.adapters.mock_yuyutei import MockYuyuTeiAdapter


def make_mapping(source_card_id: str, source_url: str = "https://example.com/card"):
    return SimpleNamespace(source_card_id=source_card_id, source_url=source_url)


def test_mock_yuyutei_parses_sell_buy_and_stock_status():
    adapter = MockYuyuTeiAdapter()
    mapping = make_mapping("OP01-001")

    snapshot = adapter.fetch_card(mapping)
    assert snapshot.http_status == 200
    assert snapshot.source_url == mapping.source_url

    observations = adapter.parse_snapshot(snapshot)
    by_type = {obs.price_type: obs for obs in observations}

    assert by_type["sell"].price_jpy == 1200
    assert by_type["sell"].stock_status == "in_stock"
    assert by_type["buy"].price_jpy == 800
    assert by_type["buy"].stock_status == "in_stock"


def test_mock_yuyutei_unknown_card_returns_404_and_no_observations():
    adapter = MockYuyuTeiAdapter()
    mapping = make_mapping("UNKNOWN-CODE")

    snapshot = adapter.fetch_card(mapping)
    assert snapshot.http_status == 404

    observations = adapter.parse_snapshot(snapshot)
    assert observations == []


def test_mock_snkrdunk_parses_floor_price_listing_count_and_sold_prices():
    adapter = MockSnkrdunkAdapter()
    mapping = make_mapping("OP01-001")

    snapshot = adapter.fetch_card(mapping)
    observations = adapter.parse_snapshot(snapshot)

    floor = next(obs for obs in observations if obs.price_type == "floor")
    assert floor.price_jpy == 1500
    assert floor.listing_count == 12

    sold = [obs for obs in observations if obs.price_type == "sold"]
    assert len(sold) == 2
    assert {obs.price_jpy for obs in sold} == {1400, 1450}


def test_mock_snkrdunk_handles_no_sold_prices_in_fixture():
    adapter = MockSnkrdunkAdapter()
    mapping = make_mapping("OP01-013")

    snapshot = adapter.fetch_card(mapping)
    observations = adapter.parse_snapshot(snapshot)

    assert all(obs.price_type != "sold" for obs in observations)
    floor = next(obs for obs in observations if obs.price_type == "floor")
    assert floor.price_jpy == 600
    assert floor.listing_count == 3


def test_mock_snkrdunk_unknown_card_returns_404_and_no_observations():
    adapter = MockSnkrdunkAdapter()
    mapping = make_mapping("UNKNOWN-CODE")

    snapshot = adapter.fetch_card(mapping)
    assert snapshot.http_status == 404

    observations = adapter.parse_snapshot(snapshot)
    assert observations == []
