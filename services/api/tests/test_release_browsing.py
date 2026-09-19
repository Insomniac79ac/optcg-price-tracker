"""Release membership is independent of a canonical card's code prefix.

Fixture identities reflect OP01-016 occurrences in the stored Bandai JP
2026-08-22 catalogue (and staging): OP-01 base/p2, OP-05 p4, PRB-01 p7.
"""
from test_prints import make_canonical, make_print


def test_release_membership_keeps_exact_prints_and_intersects(client, db_session):
    card = make_canonical(db_session, card_code="OP01-016", name_en="Nami", rarity="R")
    prints = []
    for release, variant, rarity in [
        ("OP-01", "base", "R"), ("OP-01", "p2", "R"),
        ("OP-05", "p4", "SPカード"), ("PRB-01", "p7", "R"),
    ]:
        prints.append(make_print(db_session, card, release_product_code=release,
            official_asset_variant=variant, official_rarity=rarity, artwork_key=variant))

    def query(**params):
        response = client.get("/prints", params=params)
        assert response.status_code == 200
        return response.json()["items"]

    assert len(query(q="OP01-016")) == 4
    own_release = query(set="OP-01")
    assert {p["card_print_id"] for p in own_release} == {prints[0].id, prints[1].id}
    assert {p["official_asset_variant"] for p in own_release} == {"base", "p2"}
    assert all(p["release_product_code"] == "OP-01" for p in own_release)
    assert {p["card_print_id"] for p in query(set="OP-01", rarity="R", q="Nami")} == {prints[0].id, prints[1].id}
    assert query(set="OP-01", rarity="SP CARD") == []
    assert query(set="OP-01", q="Sanji") == []
    assert [p["card_print_id"] for p in query(set="OP-05", rarity="SP CARD", q="OP01")] == [prints[2].id]
