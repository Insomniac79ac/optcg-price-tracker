"""One SNKRDUNK listing may never end up with two mappings.

THE HISTORICAL SHAPE THIS DEFENDS, verbatim from staging. Mapping 8 holds

    https://snkrdunk.com/en/trading-cards/94915?slide=right&query_id=9d4a...

and a person set it to `rejected` on 2026-08-09. Both human approval paths
used to look an existing mapping up by matching `source_url` against the two
CANONICAL spellings of the listing. That query does not find the row above -
the stored string genuinely differs - so approving candidate 2 found nothing,
created a SECOND mapping at the canonical URL (no
`uq_source_card_mappings_source_url` collision, for the same reason), and the
human's rejection was overturned by a row nobody looked at. The collector's
eligibility filter would then have priced the new one.

The batch approval job already keyed on listing identity. These tests hold the
two HUMAN paths to the same contract, which is where the defect actually was.
"""

import pytest
from sqlalchemy import select

from app.models import (
    CanonicalCard,
    CardPrint,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.seed import SOURCES
from app.services.exact_print_approval import (
    REFUSAL_MAPPING_WAS_REJECTED,
    REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
    ExactPrintApprovalError,
)
from app.services.snkrdunk_candidate_approval import find_mapping_for_listing

LISTING = "94915"
JP_URL = f"https://snkrdunk.com/apparels/{LISTING}"
EN_URL = f"https://snkrdunk.com/en/trading-cards/{LISTING}"
# The exact shape staging stores on mapping 8.
DISCOVERY_URL = f"{EN_URL}?slide=right&query_id=9d4ae32c-490f-4835-80ba-933c41cbfc29"


@pytest.fixture()
def world(db_session):
    db = db_session
    for data in SOURCES:
        db.add(Source(**data))
    product = ReleaseProduct(
        source_catalogue="jp",
        official_code="OP-01",
        display_name="OP-01",
        first_seen_name="OP-01",
        source_series_id="OP01",
        source_url="https://example.test/OP-01",
        verification_status="verified",
    )
    db.add(product)
    db.flush()
    canonical = CanonicalCard(
        card_code="OP01-001",
        name_en="Roronoa Zoro",
        name_jp="ロロノア・ゾロ",
        card_type="Character",
        rarity="L",
    )
    db.add(canonical)
    db.flush()
    print_row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key="sha256:op01-001-base",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    db.add(print_row)
    db.flush()
    candidate = SnkrdunkCandidate(
        source_url=EN_URL,
        title="Roronoa Zoro L [OP01-001] (Booster Pack ROMANCE DAWN)",
        normalized_title="roronoa zoro l [op01-001]",
        price_jpy=2500,
        image_url="https://static.snkrdunk.com/OPC-EN-TCG-OP01-001-of.webp",
        detected_card_code="OP01-001",
        detected_set_code="OP-01",
        match_status="unmatched",
    )
    db.add(candidate)
    db.commit()
    return {
        "db": db,
        "candidate": candidate,
        "print": print_row,
        "source": db.query(Source).filter_by(name="snkrdunk").one(),
    }


def _mapping(db, source, url, **kw):
    row = SourceCardMapping(
        source_id=source.id,
        source_card_id="OP01-001",
        source_url=url,
        is_active=True,
        review_status=kw.pop("review_status", "approved"),
        manual_verified=kw.pop("manual_verified", True),
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def _all_mappings(db):
    return db.scalars(select(SourceCardMapping)).all()


# --- A. the lookup itself -----------------------------------------------------


@pytest.mark.parametrize("stored", [JP_URL, EN_URL, DISCOVERY_URL, f"{JP_URL}#gallery", f"{EN_URL}/"])
def test_every_published_spelling_of_one_listing_is_found(world, stored):
    """Query string, fragment, trailing slash and both language paths are one
    identity. Each is looked up by the OTHER language's canonical form."""
    db, source = world["db"], world["source"]
    existing = _mapping(db, source, stored, card_print_id=world["print"].id)
    assert find_mapping_for_listing(db, source=source, url=JP_URL) is existing
    assert find_mapping_for_listing(db, source=source, url=EN_URL) is existing
    assert find_mapping_for_listing(db, source=source, url=DISCOVERY_URL) is existing


def test_a_different_listing_is_not_matched(world):
    """The LIKE is only a pre-filter; the parsed id decides. `9491` and
    `949150` both appear inside `94915`-ish strings and must not match."""
    db, source = world["db"], world["source"]
    _mapping(db, source, "https://snkrdunk.com/apparels/949150", card_print_id=world["print"].id)
    _mapping(db, source, "https://snkrdunk.com/apparels/9491", card_print_id=world["print"].id)
    assert find_mapping_for_listing(db, source=source, url=JP_URL) is None


def test_an_unrecognised_url_matches_nothing(world):
    db, source = world["db"], world["source"]
    assert find_mapping_for_listing(db, source=source, url="https://example.test/x") is None
    assert find_mapping_for_listing(db, source=source, url=None) is None


# --- C. duplicates fail closed ------------------------------------------------


def test_two_mappings_for_one_listing_raise_rather_than_pick_one(world):
    db, source = world["db"], world["source"]
    _mapping(db, source, JP_URL, card_print_id=world["print"].id)
    _mapping(db, source, DISCOVERY_URL, card_print_id=world["print"].id)
    with pytest.raises(ExactPrintApprovalError) as exc:
        find_mapping_for_listing(db, source=source, url=EN_URL)
    assert exc.value.code == REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING
    assert exc.value.needs_review is True
    assert len(exc.value.alternatives) == 2


# --- the two human endpoints --------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/snkrdunk-candidates/{cid}/approve-match",
        "/snkrdunk/candidates/{cid}/match",
    ],
)
def test_approving_a_rejected_equivalent_url_mapping_is_refused(world, client, endpoint):
    """B. The 94915 case, end to end, on BOTH human paths.

    The rejection must survive, and - the part the old code got wrong - no
    second mapping may appear.
    """
    db, source = world["db"], world["source"]
    rejected = _mapping(
        db,
        source,
        DISCOVERY_URL,
        review_status="rejected",
        manual_verified=False,
        card_print_id=None,
        review_notes="2026-08-09 quarantine: live product 94915 title disagrees",
    )
    response = client.post(
        endpoint.format(cid=world["candidate"].id),
        json={"card_print_id": world["print"].id, "manual_verified": True},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == REFUSAL_MAPPING_WAS_REJECTED

    db.expire_all()
    rows = _all_mappings(db)
    assert len(rows) == 1, "a second mapping was created for one listing"
    assert rows[0].id == rejected.id
    assert rows[0].review_status == "rejected"
    assert rows[0].card_print_id is None
    assert world["candidate"].match_status == "unmatched"


@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/snkrdunk-candidates/{cid}/approve-match",
        "/snkrdunk/candidates/{cid}/match",
    ],
)
def test_approving_updates_the_equivalent_url_mapping_instead_of_duplicating(
    world, client, endpoint
):
    """A. The ordinary case the same fix has to keep working: an existing
    mapping stored under the other language path (with discovery's query
    string) is UPDATED and canonicalised, not duplicated."""
    db, source = world["db"], world["source"]
    existing = _mapping(
        db,
        source,
        DISCOVERY_URL,
        review_status="needs_review",
        manual_verified=False,
        card_print_id=world["print"].id,
    )
    response = client.post(
        endpoint.format(cid=world["candidate"].id),
        json={"card_print_id": world["print"].id, "manual_verified": True},
    )
    assert response.status_code == 200, response.text

    db.expire_all()
    rows = _all_mappings(db)
    assert len(rows) == 1
    assert rows[0].id == existing.id
    # Canonicalised to the JP path, because the print is a jp print.
    assert rows[0].source_url == JP_URL
    assert rows[0].review_status == "approved"
    assert rows[0].manual_verified is True
    assert rows[0].card_print_id == world["print"].id


@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/snkrdunk-candidates/{cid}/approve-match",
        "/snkrdunk/candidates/{cid}/match",
    ],
)
def test_duplicate_listing_identity_fails_closed_on_both_endpoints(world, client, endpoint):
    """C. end to end."""
    db, source = world["db"], world["source"]
    _mapping(db, source, JP_URL, card_print_id=world["print"].id)
    _mapping(db, source, DISCOVERY_URL, card_print_id=world["print"].id)
    response = client.post(
        endpoint.format(cid=world["candidate"].id),
        json={"card_print_id": world["print"].id, "manual_verified": True},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING
    db.expire_all()
    assert len(_all_mappings(db)) == 2


@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/snkrdunk-candidates/{cid}/approve-match",
        "/snkrdunk/candidates/{cid}/match",
    ],
)
def test_a_non_canonicalisable_candidate_url_fails_closed(world, client, endpoint):
    """An unknown URL shape is refused rather than guessed at, and writes
    nothing - on both paths."""
    db = world["db"]
    world["candidate"].source_url = "https://snkrdunk.com/something-else/94915"
    db.commit()
    response = client.post(
        endpoint.format(cid=world["candidate"].id),
        json={"card_print_id": world["print"].id, "manual_verified": True},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == REFUSAL_SOURCE_URL_NOT_CANONICAL
    db.expire_all()
    assert _all_mappings(db) == []
