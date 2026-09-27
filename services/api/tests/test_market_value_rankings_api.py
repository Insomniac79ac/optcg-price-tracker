"""Public typed API contracts and explicit request-time isolation guards."""

import importlib
import socket

import httpx
import pytest
from sqlalchemy import event

from app.models import CardPrint
from app.services import market_value_rankings as service
from tests._market_value_ranking_helpers import AS_OF, PRIOR, seed_rankings

BASE = "/analytics/market-value"


@pytest.fixture
def seeded(db_session, client):
    seed_rankings(db_session)
    client.headers.clear()
    return db_session


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
@pytest.mark.parametrize("release_id", [None, 1])
def test_public_response_identity_and_no_internal_metadata(
    seeded, client, route, release_id
):
    response = client.get(
        f"{BASE}/{route}",
        params={} if release_id is None else {"release_product_id": release_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope_kind"] == ("overall" if release_id is None else "release")
    assert body["release_product_id"] == release_id
    assert body["methodology_version"] == 1
    assert body["release_code"] == ("OP-01" if release_id else None)
    assert body["release_name"] == ("Release OP-01" if release_id else None)
    for forbidden in (
        "membership_revision",
        "version_pairs",
        "snapshot_id",
        "confidence",
        "approx_index_points",
        "performance_factor",
        "source_values",
    ):
        assert forbidden not in response.text
    if route == "movers":
        assert body["order"] == "gainers"
        assert body["step_date"] == body["scope_as_of"] == AS_OF.isoformat()
        assert body["prior_date"] == PRIOR.isoformat()
        assert isinstance(body["movers"][0]["move_pct"], str)
        assert isinstance(body["movers"][0]["delta_jpy"], int)
    else:
        assert len(body["items"]) == body["limit"] == 10 and body["offset"] == 0
        assert body["as_of"] == AS_OF.isoformat()
        assert all(r["calculated_at"] == body["calculated_at"] for r in body["items"])


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 51},
        {"limit": -1},
        {"release_product_id": 0},
        {"release_product_id": -1},
        {"release_product_id": "bad"},
    ],
)
def test_invalid_shared_parameters(client, route, params):
    assert client.get(f"{BASE}/{route}", params=params).status_code == 422


@pytest.mark.parametrize(
    "route,params",
    [
        ("movers", {"order": "7d"}),
        ("movers", {"order": "cpi"}),
        ("most-valuable", {"offset": -1}),
    ],
)
def test_invalid_ranking_parameters(client, route, params):
    assert client.get(f"{BASE}/{route}", params=params).status_code == 422


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
@pytest.mark.parametrize(
    "release_id,status,detail",
    [
        (99999, 404, "release_product_not_found"),
        (5, 503, "market_value_not_seeded"),
        (17, 503, "market_value_not_seeded"),
    ],
)
def test_unknown_and_unseeded_release(
    seeded, client, route, release_id, status, detail
):
    response = client.get(f"{BASE}/{route}", params={"release_product_id": release_id})
    assert response.status_code == status and response.json() == {"detail": detail}


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
def test_empty_overall_is_503(db_session, client, route):
    response = client.get(f"{BASE}/{route}")
    assert response.status_code == 503 and response.json() == {
        "detail": "market_value_not_seeded"
    }


def test_maximum_and_stable_pagination(seeded, client):
    first = client.get(f"{BASE}/most-valuable?limit=50").json()
    second = client.get(f"{BASE}/most-valuable?limit=50&offset=50").json()
    assert len(first["items"]) == len(second["items"]) == 50
    assert first["total_eligible"] == second["total_eligible"] == 300
    assert {r["card_print_id"] for r in first["items"]}.isdisjoint(
        r["card_print_id"] for r in second["items"]
    )
    assert second == client.get(f"{BASE}/most-valuable?limit=50&offset=50").json()


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
def test_typed_integrity_503_contains_no_ranking(seeded, client, route):
    seeded.get(CardPrint, 300).is_active = False
    seeded.commit()
    response = client.get(f"{BASE}/{route}")
    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "market_value_integrity_mismatch",
            "reason": "membership_revision_mismatch",
        }
    }


@pytest.mark.parametrize(
    "route,dates",
    [
        ("movers", (PRIOR.isoformat(), AS_OF.isoformat())),
        ("most-valuable", (AS_OF.isoformat(),)),
    ],
)
def test_http_select_only_bounded_archive_and_no_external_calls(
    seeded, client, monkeypatch, route, dates
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Forbidden request-time replay/write/source/current-price/CPI call"
        )

    for module, names in (
        (
            "app.services.market_value_replay",
            (
                "load_market_value_replay_input",
                "build_market_value_point_drafts",
                "replay_market_value",
            ),
        ),
        ("app.market_value_writer", ("run_writer", "_execute")),
        ("app.services.market_value_persistence", ("persist_market_value_points",)),
        (
            "app.services.print_market_index",
            ("get_market_index_for_prints", "get_market_index_for_print"),
        ),
        ("app.services.card_pirate_index_movers", ("get_index_movers",)),
        ("app.services.job_locks", ("acquire_lock",)),
    ):
        target = importlib.import_module(module)
        for name in names:
            monkeypatch.setattr(target, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    statements = []

    def guard(_conn, _cursor, statement, parameters, *_args):
        assert statement.lstrip().upper().startswith("SELECT")
        for table in (
            "price_observations",
            "raw_snapshots",
            "job_locks",
            "card_pirate_index_points",
        ):
            assert table not in statement.lower()
        statements.append((statement, parameters))

    event.listen(seeded.get_bind(), "before_cursor_execute", guard)
    try:
        assert client.get(f"{BASE}/{route}").status_code == 200
    finally:
        event.remove(seeded.get_bind(), "before_cursor_execute", guard)
    archive = [
        (sql, params)
        for sql, params in statements
        if "FROM market_index_snapshots" in sql
    ]
    assert len(archive) == 1
    assert "snapshot_date IN" in archive[0][0]
    assert tuple(archive[0][1][: len(dates)]) == dates
    assert len(statements) <= 7
    assert sum("source_card_mappings" in sql for sql, _ in statements) == 1


@pytest.mark.parametrize(
    "fn", [service.get_market_value_movers, service.get_market_value_most_valuable]
)
def test_even_dirty_caller_session_does_not_autoflush(seeded, fn):
    seeded.autoflush = True
    p = seeded.get(CardPrint, 1)
    p.treatment = "parallel"

    def select_only(_conn, _cursor, sql, *_args):
        assert sql.lstrip().upper().startswith("SELECT")

    event.listen(seeded.get_bind(), "before_cursor_execute", select_only)
    try:
        fn(seeded)
        assert p in seeded.dirty
    finally:
        event.remove(seeded.get_bind(), "before_cursor_execute", select_only)
        seeded.rollback()


@pytest.mark.parametrize("route", ["movers", "most-valuable"])
def test_missing_image_metadata_is_null_not_ranking_failure(seeded, client, route):
    for pid in (1, 2, 3):
        seeded.get(CardPrint, pid).image_url = None
    seeded.commit()
    response = client.get(f"{BASE}/{route}")
    assert response.status_code == 200
    rows = response.json()["movers" if route == "movers" else "items"]
    assert all(
        r["display_image"] is None for r in rows if r["card_print_id"] in (1, 2, 3)
    )


@pytest.mark.parametrize(
    "fn", [service.get_market_value_movers, service.get_market_value_most_valuable]
)
def test_unexpected_image_enrichment_error_propagates_like_print_catalogue(
    seeded, monkeypatch, fn
):
    def fail(*args):
        raise RuntimeError("stored display read failed")

    monkeypatch.setattr(service, "get_display_images_for_prints", fail)
    with pytest.raises(RuntimeError, match="stored display read failed"):
        fn(seeded)


def test_openapi_documents_daily_only_and_persisted_valuation(client):
    spec = client.get("/openapi.json").json()
    movers = spec["paths"][f"{BASE}/movers"]["get"]
    valuable = spec["paths"][f"{BASE}/most-valuable"]["get"]
    assert "window" not in {p["name"] for p in movers["parameters"]}
    assert "DAILY" in movers["description"] and "persisted" in valuable["description"]
    assert not movers.get("security") and not valuable.get("security")
    assert "503" in movers["responses"] and "503" in valuable["responses"]
    order = next(p for p in movers["parameters"] if p["name"] == "order")
    assert order["schema"]["enum"] == ["gainers", "losers", "impact"]
