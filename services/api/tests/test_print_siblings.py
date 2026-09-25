"""Version-strip identity follows each exact physical product, never a code prefix."""

import pytest

from app.schemas import CardPrintSiblingOut
from tests.test_prints import make_canonical, make_print, make_release_product


@pytest.mark.parametrize("card_code,rarity,variant", [
    ("OP01-021", "SPカード", "p1"),
    ("EB04-007", "TR", "p2"),
    ("ST01-010", "C", "r1"),
])
def test_sibling_matches_own_detail_identity(client, db_session, card_code, rarity, variant):
    canonical = make_canonical(
        db_session, card_code=card_code, name_en="Franky", name_jp="フランキー",
        rarity="C", original_set_code="OP-01",
    )
    origin = make_release_product(db_session, "OP-01")
    physical = make_release_product(db_session, "OP-17")
    physical.display_name = "ブースターパック 世界最強の戦士【OP-17】"
    db_session.commit()
    current = make_print(db_session, canonical, release_product_id=origin.id, official_asset_variant="base")
    sibling = make_print(
        db_session, canonical, release_product_id=physical.id,
        # Deliberately misleading denormalized code: the FK alone is authority.
        release_product_code="OP-01", official_rarity=rarity,
        official_asset_variant=variant, treatment=None,
        image_url="https://images.example.com/exact-sibling.png", artwork_key="sibling-art",
    )
    make_print(db_session, canonical, official_asset_variant="p9", is_active=False)
    response = client.get(f"/prints/{current.id}")
    assert response.status_code == 200
    versions = response.json()["siblings"]
    assert len(versions) == 1
    version = versions[0]
    assert version["card_print_id"] == sibling.id
    assert version["canonical_card_id"] == canonical.id
    assert version["card_code"] == card_code
    assert (version["name_en"], version["name_jp"]) == ("Franky", "フランキー")
    assert version["release_product_id"] == physical.id
    assert version["release_code"] == "OP-17"
    assert version["release_name"] == physical.display_name
    assert version["rarity"] == rarity
    assert version["canonical_rarity"] == "C"
    assert version["official_asset_variant"] == variant
    assert version["image_url"] == sibling.image_url
    assert version["display_image"]["url"] == sibling.image_url
    own_detail = client.get(f"/prints/{sibling.id}").json()
    assert version == {key: own_detail[key] for key in version}
    # Pin the lightweight contract so prices cannot slip in with this extension.
    assert set(version) == {
        "card_print_id", "canonical_card_id", "card_code", "name_en", "name_jp",
        "release_product_id", "release_code", "release_name", "rarity", "canonical_rarity",
        "official_asset_variant", "treatment", "language", "verification_status",
        "image_url", "display_image",
    } == set(CardPrintSiblingOut.model_fields)


def test_franky_uncoded_product_and_missing_product_stay_distinct(client, db_session):
    canonical = make_canonical(db_session, card_code="ST01-010", name_en="Franky", rarity="C")
    starter = make_release_product(db_session, "ST-01")
    anniversary = make_release_product(db_session, "ANNIVERSARY-FIXTURE")
    anniversary.official_code = None
    anniversary.display_name = "プレミアムカードコレクション 25周年エディション"
    db_session.commit()
    base = make_print(db_session, canonical, release_product_id=starter.id, official_asset_variant="base")
    alt = make_print(db_session, canonical, release_product_id=anniversary.id,
                     release_product_code=None, official_asset_variant="p1", treatment=None)
    missing = make_print(db_session, canonical, release_product_id=None,
                         release_product_code="ST-01", official_asset_variant="p2",
                         verification_status="unverified")
    versions = {v["card_print_id"]: v for v in client.get(f"/prints/{base.id}").json()["siblings"]}
    assert versions[alt.id]["release_product_id"] == anniversary.id
    assert versions[alt.id]["release_code"] is None
    assert versions[alt.id]["release_name"] == anniversary.display_name
    assert versions[missing.id]["release_product_id"] is None
    assert versions[missing.id]["release_code"] is None
    assert versions[missing.id]["release_name"] is None
