"""Pin existing consumers to payloads generated from staging b8ecdf70.

The fixtures were generated with that commit's route and read-service code,
using the existing five_prints and archive datasets. Only the two explicitly
additive fields may differ; every pre-existing value and row order is pinned.
"""

import json
from pathlib import Path

import pytest

from test_analytics_card_pirate_index_movers import archive  # noqa: F401
from test_prints import five_prints  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures" / "market_contract_1b"


@pytest.mark.parametrize("basis", ["market_index", "source:yuyutei", "source:not_configured"])
def test_overview_existing_fields_equal_staging_payload(client, five_prints, basis):
    params = {} if basis == "market_index" else {"price_basis": basis}
    response = client.get("/analytics/market/overview", params=params)
    assert response.status_code == 200
    body = response.json()
    assert body["scope"].pop("release_product_id") is None
    assert body == json.loads((FIXTURES / "overview.json").read_text())[basis]


def test_default_movers_existing_fields_equal_staging_payload(client, archive):
    response = client.get("/analytics/index/movers")
    assert response.status_code == 200
    body = response.json()
    assert body.pop("order") == "move"
    assert body == json.loads((FIXTURES / "movers.json").read_text())
