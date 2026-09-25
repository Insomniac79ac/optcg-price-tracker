"""Physical product scope must agree with /prints, even when codes disagree."""

import pytest

from app.services.market_analytics import scoped_print_ids
from test_prints import (
    NOW, make_canonical, make_legacy_card, make_mapping, make_observation,
    make_print, make_release_product, make_source,
)


@pytest.fixture
def releases(db_session):
    op17 = make_release_product(db_session, "OP-17")
    eb04 = make_release_product(db_session, "EB-04")
    source = make_source(db_session)
    rows = []
    for code, rarity, product, stale_code, price in [
        ("EB04-007", "SEC", op17, "EB-04", 100),
        ("OP17-002", "R", op17, None, 300),
        ("OP17-003", "SEC", op17, None, None),
        ("EB04-008", "SEC", eb04, "OP-17", 900),
    ]:
        canonical = make_canonical(
            db_session, card_code=code, rarity=rarity, original_set_code="EB-04"
        )
        row = make_print(
            db_session, canonical, release_product_id=product.id,
            release_product_code=stale_code, artwork_key=code,
        )
        if price is not None:
            legacy = make_legacy_card(db_session, card_code=code, rarity=rarity)
            mapping = make_mapping(db_session, legacy, source, row)
            make_observation(
                db_session, legacy, source, mapping, row, price_jpy=price, observed_at=NOW
            )
        rows.append(row)
    return op17, eb04, rows


def overview(client, **params):
    response = client.get("/analytics/market/overview", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("selector", ["id", "set", "both"])
def test_authoritative_mixed_code_scope(client, db_session, releases, selector):
    op17, eb04, rows = releases
    params = {}
    if selector != "set":
        params["release_product_id"] = op17.id
    if selector != "id":
        params["set"] = "OP-17"
    body = overview(client, **params)
    assert body["scope"] == {
        "active_prints": 3, "set": params.get("set"), "rarity": None,
        "release_product_id": op17.id,
    }
    assert set(scoped_print_ids(
        db_session, release_product_id=params.get("release_product_id"),
        set_code=params.get("set"),
    )) == {row.id for row in rows[:3]}
    assert body["coverage"]["usable_priced_prints"] == 2
    assert body["coverage"]["coverage_pct"] == 66.67
    assert body["current_price"]["median_jpy"] == 200
    assert overview(client, release_product_id=eb04.id)["scope"]["active_prints"] == 1
    catalogue = client.get("/prints", params=params).json()
    assert {row["card_print_id"] for row in catalogue["items"]} == {r.id for r in rows[:3]}
    assert next(row for row in catalogue["items"] if row["card_print_id"] == rows[0].id)["card_code"] == "EB04-007"


@pytest.mark.parametrize("basis", ["market_index", "source:yuyutei"])
@pytest.mark.parametrize("rarity,count,priced,median", [(None, 3, 2, 200), ("SEC", 2, 1, 100), ("R", 1, 1, 300)])
def test_release_rarity_and_basis_intersect(client, releases, basis, rarity, count, priced, median):
    op17, _, _ = releases
    params = {"release_product_id": op17.id, "price_basis": basis}
    if rarity:
        params["rarity"] = rarity
    body = overview(client, **params)
    assert body["scope"]["active_prints"] == count
    assert body["scope"]["rarity"] == rarity
    assert body["scope"]["release_product_id"] == op17.id
    assert body["coverage"]["usable_priced_prints"] == priced
    assert body["current_price"]["median_jpy"] == median
    assert sum(b["count"] for b in body["distribution"]) == priced
    assert client.get("/prints", params=params).json()["total"] == priced


def test_no_release_filter_keeps_all_active_prints(client, releases):
    body = overview(client)
    assert body["scope"] == {
        "active_prints": 4, "set": None, "rarity": None, "release_product_id": None,
    }
    assert body["coverage"]["usable_priced_prints"] == 3
    assert body["current_price"]["median_jpy"] == 300


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_invalid_id_matches_prints_validation(client, releases, value):
    params = {"release_product_id": value}
    assert client.get("/analytics/market/overview", params=params).status_code == 422
    assert client.get("/prints", params=params).status_code == 422


@pytest.mark.parametrize("set_code", ["EB-04", "OP17", "", "UNKNOWN"])
def test_conflicting_forms_match_prints_refusal(client, releases, set_code):
    op17, _, _ = releases
    params = {"release_product_id": op17.id, "set": set_code}
    market = client.get("/analytics/market/overview", params=params)
    catalogue = client.get("/prints", params=params)
    assert market.status_code == catalogue.status_code == 400
    assert market.json() == catalogue.json()


@pytest.mark.parametrize("params", [{"release_product_id": 999999}, {"set": "UNKNOWN"}])
def test_unknown_scope_is_empty_never_broad(client, releases, params):
    body = overview(client, **params)
    assert body["scope"]["active_prints"] == 0
    assert body["scope"]["release_product_id"] == params.get("release_product_id")
    assert body["coverage"]["coverage_pct"] is None
    assert body["current_price"]["median_jpy"] is None
    assert client.get("/prints", params=params).json()["total"] == 0


def test_unknown_id_with_set_is_conflict(client, releases):
    params = {"release_product_id": 999999, "set": "OP-17"}
    assert client.get("/analytics/market/overview", params=params).status_code == 400
    assert client.get("/prints", params=params).status_code == 400


def test_uncoded_product_is_selectable_by_identity(client, db_session, releases):
    product = make_release_product(db_session, None)
    canonical = make_canonical(db_session, card_code="ST01-010")
    make_print(db_session, canonical, release_product_id=product.id, release_product_code=None)
    body = overview(client, release_product_id=product.id)
    assert body["scope"]["active_prints"] == 1
    assert body["scope"]["release_product_id"] == product.id


def test_release_scope_preserves_unavailable_basis(client, releases):
    op17, _, _ = releases
    body = overview(client, release_product_id=op17.id, price_basis="source:not_configured")
    assert body["scope"]["active_prints"] == 3
    assert body["available"] is False
    assert body["unavailable_reason"] == "source_not_configured"
    assert body["coverage"]["usable_priced_prints"] == 0
    assert body["current_price"]["median_jpy"] is None


def test_openapi_exposes_release_id(client):
    parameters = client.get("/openapi.json").json()["paths"]["/analytics/market/overview"]["get"]["parameters"]
    schema = next(p["schema"] for p in parameters if p["name"] == "release_product_id")
    assert {"type": "integer", "minimum": 1} in schema["anyOf"]
