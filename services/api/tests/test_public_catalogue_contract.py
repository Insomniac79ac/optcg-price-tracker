"""Public UX 1A read contracts: composable filters and release identity.

These fixtures deliberately attach mixed card-code families to physical
products through CardPrint.release_product_id. No assertion infers membership
from a CanonicalCard code or from a denormalized release-product code.
"""

import json
from datetime import datetime, timedelta, timezone

from app.models import ReleaseProduct
from app.services.rarity_facets import SP_CARD
from test_prints import (  # noqa: F401  (five_prints is used by fixture name)
    five_prints,
    make_canonical,
    make_print,
)


def _items(response):
    assert response.status_code == 200, response.text
    return response.json()


def _release(
    db_session,
    *,
    code: str | None,
    name: str,
    series: str,
    catalogue: str = "bandai_jp",
    verification_status: str = "verified",
) -> ReleaseProduct:
    product = ReleaseProduct(
        source_catalogue=catalogue,
        official_code=code,
        display_name=name,
        first_seen_name=name,
        source_series_id=series,
        source_url=f"https://catalogue.example/{catalogue}/{series}",
        verification_status=verification_status,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _print_for_release(
    db_session,
    release: ReleaseProduct,
    *,
    card_code: str,
    rarity: str = "SR",
    treatment: str | None = "parallel",
    language: str = "jp",
    verification_status: str = "verified",
    is_active: bool = True,
    created_at: datetime | None = None,
):
    canonical = make_canonical(
        db_session,
        card_code=card_code,
        name_en=f"Card {card_code}",
        rarity=rarity,
        original_set_code=card_code.split("-")[0],
    )
    values = {
        "release_product_id": release.id,
        "release_product_code": release.official_code,
        "official_rarity": rarity,
        "treatment": treatment,
        "language": language,
        "verification_status": verification_status,
        "is_active": is_active,
        "artwork_key": f"art-{release.id}-{card_code}-{language}-{verification_status}",
    }
    if created_at is not None:
        values["created_at"] = created_at
    return make_print(db_session, canonical, **values)


# --- repeated collector filters -------------------------------------------


def test_single_rarity_and_treatment_urls_remain_compatible(client, five_prints):
    rarity = _items(client.get("/prints", params={"rarity": "SR", "limit": 100}))
    treatment = _items(
        client.get("/prints", params={"treatment": "parallel", "limit": 100})
    )

    assert rarity["total"] == 3
    assert {item["rarity"] for item in rarity["items"]} == {"SR"}
    assert treatment["total"] == 3
    assert {item["treatment"] for item in treatment["items"]} == {"parallel"}


def test_repeated_rarities_are_or_and_duplicates_do_not_duplicate_rows(
    client, db_session, five_prints
):
    release = db_session.get(ReleaseProduct, five_prints["sanji_base"].release_product_id)
    assert release is not None
    sec = _print_for_release(
        db_session, release, card_code="OP01-777", rarity="SEC", treatment="sp"
    )

    body = _items(
        client.get(
            "/prints",
            params=[
                ("rarity", "SR"),
                ("rarity", "SEC"),
                ("rarity", "SR"),
                ("sort", "card_code_asc"),
                ("limit", "100"),
            ],
        )
    )

    assert body["total"] == 4
    ids = [item["card_print_id"] for item in body["items"]]
    assert sec.id in ids
    assert len(ids) == len(set(ids))
    assert {item["rarity"] for item in body["items"]} == {"SR", "SEC"}


def test_repeated_treatments_are_or(client, db_session, five_prints):
    release = db_session.get(ReleaseProduct, five_prints["sanji_base"].release_product_id)
    assert release is not None
    special = _print_for_release(
        db_session, release, card_code="OP01-778", rarity="SEC", treatment="sp"
    )

    body = _items(
        client.get(
            "/prints",
            params=[
                ("treatment", "parallel"),
                ("treatment", "sp"),
                ("limit", "100"),
            ],
        )
    )

    assert body["total"] == 4
    assert special.id in {item["card_print_id"] for item in body["items"]}
    assert {item["treatment"] for item in body["items"]} == {"parallel", "sp"}


def test_rarity_or_and_treatment_or_compose_with_and_semantics(
    client, db_session, five_prints
):
    release = db_session.get(ReleaseProduct, five_prints["sanji_base"].release_product_id)
    assert release is not None
    sec_sp = _print_for_release(
        db_session, release, card_code="OP01-779", rarity="SEC", treatment="sp"
    )

    body = _items(
        client.get(
            "/prints",
            params=[
                ("rarity", "SR"),
                ("rarity", "SEC"),
                ("treatment", "parallel"),
                ("treatment", "sp"),
                ("sort", "name"),
                ("limit", "100"),
            ],
        )
    )

    assert body["total"] == 3
    assert {item["card_print_id"] for item in body["items"]} == {
        five_prints["zoro_parallel"].id,
        five_prints["law_parallel"].id,
        sec_sp.id,
    }


def test_multi_rarity_expands_and_unions_existing_facets(client, db_session):
    release = _release(
        db_session, code="OP-17", name="Booster OP-17", series="550117"
    )
    jp_sp = _print_for_release(
        db_session, release, card_code="OP12-001", rarity="SPカード", treatment="parallel"
    )
    en_sp = _print_for_release(
        db_session, release, card_code="OP13-001", rarity="SP P", treatment="sp"
    )
    sr = _print_for_release(
        db_session, release, card_code="OP14-001", rarity="SR", treatment="base"
    )

    body = _items(
        client.get(
            "/prints",
            params=[("rarity", SP_CARD), ("rarity", "SR"), ("limit", "100")],
        )
    )

    assert body["total"] == 3
    assert {item["card_print_id"] for item in body["items"]} == {jp_sp.id, en_sp.id, sr.id}
    assert body["facets"]["rarities"].count(SP_CARD) == 1
    assert "SR" in body["facets"]["rarities"]


def test_multi_filter_totals_and_adjacent_offset_pages_are_stable(
    client, db_session, five_prints
):
    release = db_session.get(ReleaseProduct, five_prints["sanji_base"].release_product_id)
    assert release is not None
    _print_for_release(
        db_session, release, card_code="OP01-780", rarity="SEC", treatment="sp"
    )
    params = [
        ("rarity", "SR"),
        ("rarity", "SEC"),
        ("sort", "card_code_asc"),
        ("limit", "2"),
    ]
    first = _items(client.get("/prints", params=params))
    second = _items(client.get("/prints", params=[*params, ("offset", "2")]))
    full = _items(
        client.get(
            "/prints",
            params=[("rarity", "SR"), ("rarity", "SEC"), ("limit", "100")],
        )
    )

    assert first["total"] == second["total"] == full["total"] == 4
    adjacent = [item["card_print_id"] for item in first["items"] + second["items"]]
    assert len(adjacent) == len(set(adjacent)) == 4


# --- authoritative physical-product identity ------------------------------


def test_mixed_code_print_is_selected_by_release_id_and_authoritative_set_code(
    client, db_session
):
    op17 = _release(db_session, code="OP-17", name="World's Strongest", series="550117")
    op16 = _release(db_session, code="OP-16", name="Decisive Battle", series="550116")
    mixed = _print_for_release(
        db_session, op17, card_code="EB04-001", rarity="SR", treatment="parallel"
    )
    prefix_decoy = _print_for_release(
        db_session, op16, card_code="OP17-001", rarity="SR", treatment="parallel"
    )

    by_id = _items(client.get("/prints", params={"release_product_id": op17.id}))
    by_code = _items(client.get("/prints", params={"set": "OP-17"}))

    assert [item["card_print_id"] for item in by_id["items"]] == [mixed.id]
    assert [item["card_print_id"] for item in by_code["items"]] == [mixed.id]
    assert prefix_decoy.id not in {item["card_print_id"] for item in by_id["items"]}


def test_matching_set_and_release_id_compose_and_conflicts_return_400(client, db_session):
    op17 = _release(db_session, code="OP-17", name="World's Strongest", series="550117")
    op16 = _release(db_session, code="OP-16", name="Decisive Battle", series="550116")
    print_row = _print_for_release(db_session, op17, card_code="OP12-099")

    matching = client.get(
        "/prints", params={"set": "OP-17", "release_product_id": op17.id}
    )
    conflict = client.get(
        "/prints", params={"set": "OP-17", "release_product_id": op16.id}
    )

    assert matching.status_code == 200
    assert [item["card_print_id"] for item in matching.json()["items"]] == [print_row.id]
    assert conflict.status_code == 400
    assert "different release products" in conflict.json()["detail"]


def test_uncoded_release_is_filterable_by_authoritative_id(client, db_session):
    promo = _release(
        db_session, code=None, name="Limited product cards", series="550801"
    )
    print_row = _print_for_release(db_session, promo, card_code="P-099", rarity="P")

    body = _items(client.get("/prints", params={"release_product_id": promo.id}))

    assert [item["card_print_id"] for item in body["items"]] == [print_row.id]
    assert body["items"][0]["release_code"] is None
    assert body["items"][0]["release_name"] == "Limited product cards"


def test_catalogue_and_detail_expose_authoritative_release_identity(client, db_session):
    op17 = _release(db_session, code="OP-17", name="World's Strongest", series="550117")
    print_row = _print_for_release(db_session, op17, card_code="OP12-099")

    item = _items(client.get("/prints", params={"release_product_id": op17.id}))["items"][0]
    detail = _items(client.get(f"/prints/{print_row.id}"))

    for payload in (item, detail):
        assert payload["release_product_id"] == op17.id
        assert payload["release_code"] == "OP-17"
        assert payload["release_name"] == "World's Strongest"
        assert payload["created_at"] is not None
    assert item["card_code"] == "OP12-099"


# --- public release navigation --------------------------------------------


def test_releases_include_only_products_used_by_active_verified_jp_prints(
    client, db_session
):
    op17 = _release(db_session, code="OP-17", name="OP17", series="550117")
    inactive = _release(db_session, code="OP-16", name="OP16", series="550116")
    unverified = _release(db_session, code="OP-15", name="OP15", series="550115")
    english_only = _release(db_session, code="OP-14", name="OP14", series="550114")
    foreign = _release(
        db_session,
        code="OP-13",
        name="English OP13",
        series="en-op13",
        catalogue="bandai_en",
    )
    first = _print_for_release(db_session, op17, card_code="EB04-001")
    second = _print_for_release(db_session, op17, card_code="OP12-002")
    _print_for_release(db_session, inactive, card_code="OP16-001", is_active=False)
    _print_for_release(
        db_session,
        unverified,
        card_code="OP15-001",
        verification_status="unverified",
    )
    _print_for_release(db_session, english_only, card_code="OP14-001", language="en")
    _print_for_release(db_session, foreign, card_code="OP13-001")

    body = _items(client.get("/releases"))

    assert [item["release_product_id"] for item in body["items"]] == [op17.id]
    assert body["items"][0]["print_count"] == 2
    assert body["items"][0]["official_code"] == "OP-17"
    assert "source_url" not in body["items"][0]
    assert first.id != second.id


def test_release_order_is_deterministic_and_explicitly_not_chronology(
    client, db_session
):
    op17 = _release(db_session, code="OP-17", name="OP17", series="550117")
    eb04 = _release(db_session, code="EB-04", name="EB04", series="550204")
    promo = _release(db_session, code=None, name="Promotional cards", series="550901")
    _print_for_release(db_session, op17, card_code="EB04-001")
    _print_for_release(db_session, eb04, card_code="OP17-001")
    _print_for_release(db_session, promo, card_code="P-001")

    first = _items(client.get("/releases"))
    second = _items(client.get("/releases"))

    assert first == second
    assert first["chronology_available"] is False
    assert first["ordering_basis"] == "deterministic_catalogue_fallback"
    assert [item["official_code"] for item in first["items"]] == [
        "EB-04",
        "OP-17",
        None,
    ]
    counts = {item["release_product_id"]: item["print_count"] for item in first["items"]}
    assert counts == {op17.id: 1, eb04.id: 1, promo.id: 1}


# --- recently added to Atlas ----------------------------------------------


def test_created_desc_uses_created_at_then_descending_print_id_and_stable_pages(
    client, db_session
):
    release = _release(db_session, code="OP-17", name="OP17", series="550117")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    oldest = _print_for_release(
        db_session, release, card_code="OP12-001", created_at=now - timedelta(days=1)
    )
    tied_low = _print_for_release(
        db_session, release, card_code="OP13-001", created_at=now
    )
    tied_high = _print_for_release(
        db_session, release, card_code="OP14-001", created_at=now
    )
    _print_for_release(
        db_session,
        release,
        card_code="OP15-001",
        created_at=now + timedelta(days=1),
        is_active=False,
    )

    full = _items(client.get("/prints", params={"sort": "created_desc", "limit": 100}))
    first = _items(client.get("/prints", params={"sort": "created_desc", "limit": 2}))
    second = _items(
        client.get(
            "/prints", params={"sort": "created_desc", "limit": 2, "offset": 2}
        )
    )

    expected = [tied_high.id, tied_low.id, oldest.id]
    assert [item["card_print_id"] for item in full["items"]] == expected
    paged = [item["card_print_id"] for item in first["items"] + second["items"]]
    assert paged == expected
    assert first["total"] == second["total"] == 3
    assert len(paged) == len(set(paged))
    assert all(item["release_product_id"] == release.id for item in full["items"])


# --- generated contract ----------------------------------------------------


def test_openapi_describes_repeated_filters_release_id_recent_sort_and_releases(client):
    document = client.get("/openapi.json").json()
    parameters = {
        parameter["name"]: parameter
        for parameter in document["paths"]["/prints"]["get"]["parameters"]
    }

    assert '"type": "array"' in json.dumps(parameters["rarity"]["schema"])
    assert '"type": "array"' in json.dumps(parameters["treatment"]["schema"])
    assert '"type": "integer"' in json.dumps(parameters["release_product_id"]["schema"])
    assert "created_desc" in json.dumps(parameters["sort"]["schema"])
    assert "/releases" in document["paths"]
