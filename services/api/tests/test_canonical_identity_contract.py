from opcg_source_identity import canonical_source_listing_identity
from opcg_source_identity.vectors import verify_contract

from app.services.canonical_listing_identity import canonical_source_listing_identity as api_identity
from app.services.snkrdunk_urls import listing_id
from app.services.yuyutei_urls import listing_identity


def test_shared_and_api_contract():
    verify_contract(canonical_source_listing_identity)
    verify_contract(api_identity)
    assert listing_id("https://snkrdunk.com/apparels/104428") == "104428"
    assert listing_identity("https://yuyu-tei.jp/sell/opc/card/st11/10002") == ("st11", "10002")
