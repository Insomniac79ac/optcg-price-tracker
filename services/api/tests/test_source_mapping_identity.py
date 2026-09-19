from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.services.source_mapping_identity import (
    BROKEN,
    EXACT,
    LEGACY_COMPATIBILITY,
    classify_mapping_identity,
    load_source_mapping_identities,
)
from tests.exact_reporting_helpers import (
    make_canonical,
    make_compatibility_card,
    make_exact_mapping,
    make_legacy_mapping,
    make_print,
    make_source,
)


def test_exact_mapping_with_null_compatibility_card_is_exact(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-001"))
    mapping = make_exact_mapping(db_session, print_row, source)

    identity = next(
        item
        for item in load_source_mapping_identities(db_session)
        if item.mapping.id == mapping.id
    )

    assert identity.classification == EXACT
    assert identity.card_print_id == print_row.id
    assert identity.compatibility_card_id is None
    assert identity.canonical_card_id == print_row.canonical_card_id
    assert identity.release_product_id == print_row.release_product_id


def test_grandfathered_card_only_mapping_is_legacy_compatibility(db_session):
    source = make_source(db_session)
    card = make_compatibility_card(db_session, "OP01-001")
    mapping = make_legacy_mapping(db_session, card, source)

    identity = next(
        item
        for item in load_source_mapping_identities(db_session)
        if item.mapping.id == mapping.id
    )

    assert identity.classification == LEGACY_COMPATIBILITY
    assert identity.card_print_id is None
    assert identity.compatibility_card_id == card.id


def test_mapping_with_unresolved_print_lineage_is_broken():
    source = Source(id=1, name="yuyutei", base_url="https://example.test")
    mapping = SourceCardMapping(
        id=1,
        source_id=source.id,
        card_print_id=999,
        card_id=None,
        source_card_id="listing",
    )

    result = classify_mapping_identity(
        mapping,
        source=source,
        card_print=None,
        canonical_card=None,
        release_product=None,
        compatibility_card=None,
    )

    assert result == BROKEN
