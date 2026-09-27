import ast
import inspect
import socket
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.main import app
from app.services import market_value_read
from tests._market_value_read_helpers import END, frozen_census, release, seed

URL = "/analytics/market-value"


def test_public_default_contract_and_decimal_serialization(db_session, client):
    seed(db_session, physical=400, last_pair=(30000, 27000))
    client.headers.clear()
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "scope_kind",
        "release_product_id",
        "release_code",
        "release_name",
        "methodology_version",
        "as_of",
        "tracked_value",
        "movement",
        "series",
    }
    assert body["scope_kind"] == "overall"
    assert (
        body["release_product_id"]
        is body["release_code"]
        is body["release_name"]
        is None
    )
    assert body["as_of"] == "2026-09-26"
    assert body["tracked_value"] == {
        "value_jpy": 30000,
        "priced_print_count": 300,
        "total_physical_print_count": 400,
        "physical_coverage_pct": "75.00",
        "is_partial": True,
    }
    assert body["movement"] == {
        "window": "7d",
        "available": True,
        "from_date": "2026-09-19",
        "to_date": "2026-09-26",
        "fraction": "-0.1",
        "pct": "-10.0",
        "reason": "publishable",
    }
    assert set(body["series"][0]) == {
        "date",
        "tracked_value_jpy",
        "priced_print_count",
        "total_physical_print_count",
        "performance_pct",
        "step_publication_eligible",
        "publication_reason",
    }
    assert Decimal(body["series"][-1]["performance_pct"]) == -10


def test_release_uses_authoritative_metadata_without_any_card_rows(db_session, client):
    seed(db_session)
    release(db_session, display_name="Awakening of the New Era")
    seed(db_session, release_id=174)
    body = client.get(URL, params={"release_product_id": 174}).json()
    assert body["release_product_id"] == 174
    assert body["release_code"] == "OP-05"
    assert body["release_name"] == "Awakening of the New Era"
    assert body["scope_kind"] == "release"


@pytest.mark.parametrize(
    "query",
    [
        "window=bad",
        "window=7D",
        "window=",
        "release_product_id=0",
        "release_product_id=-1",
        "release_product_id=abc",
    ],
)
def test_invalid_parameters_are_rejected(db_session, client, query):
    assert client.get(URL + "?" + query).status_code == 422


def test_unknown_positive_release_returns_404_even_when_unseeded(db_session, client):
    response = client.get(URL + "?release_product_id=999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "release_product_not_found"}


@pytest.mark.parametrize("suffix", ["", "/releases", "?release_product_id=174"])
def test_unseeded_returns_consistent_503_without_fake_zeros(db_session, client, suffix):
    release(db_session)
    response = client.get(URL + suffix)
    assert response.status_code == 503
    assert response.json() == {"detail": "market_value_not_seeded"}


def test_known_release_without_points_is_503(db_session, client):
    seed(db_session)
    release(db_session)
    assert client.get(URL + "?release_product_id=174").status_code == 503


def test_unavailable_movement_remains_json_null(db_session, client):
    seed(db_session, breaks={END: "insufficient_physical_coverage"})
    body = client.get(URL).json()
    assert body["movement"]["available"] is False
    assert body["movement"]["pct"] is body["movement"]["fraction"] is None
    assert body["movement"]["reason"] == "insufficient_physical_coverage"
    assert body["series"][-1]["performance_pct"] is None


def test_release_list_public_sparse_and_frozen_contract(db_session, client):
    frozen_census(db_session)
    client.headers.clear()
    response = client.get(URL + "/releases")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 59
    assert sum(item["seven_day"]["available"] for item in items) == 9
    assert sum(item["thirty_day"]["available"] for item in items) == 0
    sparse = next(item for item in items if item["release_code"] == "OP-05")
    assert set(sparse) == {
        "release_product_id",
        "release_code",
        "release_name",
        "as_of",
        "tracked_value",
        "seven_day",
        "thirty_day",
        "methodology_version",
    }
    assert sparse["as_of"] == "2026-09-26"
    assert sparse["tracked_value"]["value_jpy"] == 480
    assert sparse["seven_day"]["pct"] is None
    assert sparse["thirty_day"]["pct"] is None


def test_openapi_typed_public_contract():
    schema = app.openapi()
    endpoint = schema["paths"][URL]["get"]
    parameters = {p["name"]: p for p in endpoint["parameters"]}
    assert parameters["window"]["schema"]["enum"] == ["7d", "30d", "all"]
    assert parameters["window"]["schema"]["default"] == "7d"
    assert parameters["release_product_id"]["schema"]["anyOf"][0]["minimum"] == 1
    assert not endpoint.get("security")
    assert "404" in endpoint["responses"] and "503" in endpoint["responses"]
    contract = schema["components"]["schemas"]["MarketValueOut"]["properties"]
    assert "not a live" in contract["as_of"]["description"]
    tracked = schema["components"]["schemas"]["MarketValueTrackedOut"]
    assert "Literal partial JPY" in tracked["description"]
    movement = schema["components"]["schemas"]["MarketValueMovementOut"]["properties"]
    assert {kind["type"] for kind in movement["pct"]["anyOf"]} == {"string", "null"}


def test_http_reads_only_persisted_tables_never_writes_or_contacts_sources(
    db_session, client, monkeypatch
):
    from app import market_value_writer
    from app.services import market_value_replay, market_value, print_market_index

    seed(db_session)
    release(db_session)
    seed(db_session, release_id=174)

    def forbidden(*args, **kwargs):
        pytest.fail("HTTP read invoked a writer, replay, raw calculation or network")

    for module in (market_value_writer, market_value_replay, print_market_index):
        for name, obj in vars(module).items():
            if inspect.isfunction(obj):
                monkeypatch.setattr(module, name, forbidden)
    for name in (
        "replay_market_value",
        "compute_monetary_step",
        "current_tracked_value",
        "evaluate_market_value_window",
        "evaluate_market_value_publication",
    ):
        monkeypatch.setattr(market_value, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    statements = []

    def read_only(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
        assert statement.lstrip().upper().startswith("SELECT"), statement
        lowered = statement.lower()
        for table in (
            "market_index_snapshots",
            "card_pirate_index_points",
            "price_observations",
            "card_prints",
            "sources",
            "job_locks",
        ):
            assert table not in lowered, statement

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", read_only)
    try:
        client.headers.clear()
        for suffix in ("", "?window=all", "?release_product_id=174", "/releases"):
            response = client.get(URL + suffix)
            assert response.status_code == 200
            for private in (
                "membership_revision",
                "performance_factor",
                "current_version_pairs",
                "prior_version_pairs",
                "created_at",
                "job_lock",
            ):
                assert private not in response.text
        assert statements
    finally:
        event.remove(engine, "before_cursor_execute", read_only)


def test_read_module_has_no_replay_writer_source_or_pricing_imports():
    source = ast.parse(inspect.getsource(market_value_read))
    imports = [
        node.module for node in ast.walk(source) if isinstance(node, ast.ImportFrom)
    ]
    assert set(imports) <= {
        "collections",
        "datetime",
        "decimal",
        "sqlalchemy",
        "sqlalchemy.orm",
        "app.market_value_schemas",
        "app.models.market_value_point",
        "app.models.release_product",
        "app.services.market_value",
        "app.services.release_ordering",
    }
    engine_import = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.services.market_value"
    )
    assert {alias.name for alias in engine_import.names} == {
        "CALCULATION_DECIMAL_PRECISION",
        "METHODOLOGY_VERSION",
        "PublicationReason",
    }
