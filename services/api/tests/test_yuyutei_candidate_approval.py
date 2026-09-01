"""Yuyu-Tei candidate review and approval: the guards, and what approval writes.

WHAT THESE TESTS ARE PROTECTING. Approval is the moment a discovery
observation becomes a thing the collector will go and price. Everything here
is about the two ways that can go wrong: approving a candidate whose
`print_matched` claim is no longer trustworthy (a truncated or unfinished or
superseded enumeration), and approving one twice so a single Yuyu-Tei listing
ends up with two mappings pointing at different printings.

The database is the real schema (Base.metadata), so the constraints asserted
here - the candidate's match-status CHECK, the mapping's
(source_id, source_url) uniqueness - are the ones production has.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.models.yuyutei_candidate import YuyuteiCandidate
from app.models.yuyutei_discovery_run import YuyuteiDiscoveryRun

BASE = "/admin/yuyutei-candidates"


def listing(slug, product_id):
    return f"https://yuyu-tei.jp/sell/opc/card/{slug}/{product_id}"


def make_print(db, card_code, *, active=True, verified=True, product_code="OP01"):
    """One canonical card and one print of it.

    `release_product_id` is not decoration: ck_card_prints_verified_requires_fields
    refuses to let a print be `verified` without a product, an asset variant
    and an artwork key. The fixture's single ReleaseProduct is reused for all
    of them - the product only has to exist, because a Yuyu-Tei listing names
    no product and so never narrows on one.
    """
    product = db.scalars(select(ReleaseProduct)).first()
    canonical = CanonicalCard(card_code=card_code, name_en=card_code, card_type="Character")
    db.add(canonical)
    db.flush()
    row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code=product_code,
        release_product_id=product.id if product is not None else None,
        artwork_key=f"sha256:{card_code}-base",
        official_asset_variant="base",
        verification_status="verified" if verified else "unverified",
        is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def make_run(db, *, slugs=("op01",), status="completed", complete=True):
    """A discovery run whose per-slug metrics say what the enumeration was."""
    run = YuyuteiDiscoveryRun(
        status=status,
        requested_set_slugs=list(slugs),
        per_slug_metrics_json={
            slug: {
                "slug": slug,
                "enumeration_complete": complete,
                "budget_exhausted": not complete,
                "page_budget_exhausted": False,
                "own_series_products": 1,
            }
            for slug in slugs
        },
    )
    db.add(run)
    db.flush()
    return run


def make_candidate(
    db,
    run,
    *,
    slug="op01",
    product_id="10001",
    card_code="OP01-001",
    status="print_matched",
    card_print=None,
    source_url=None,
):
    candidate = YuyuteiCandidate(
        discovery_run_id=run.id if run else None,
        set_slug=slug,
        product_id=product_id,
        source_url=source_url or listing(slug, product_id),
        detected_card_code=card_code,
        detected_rarity="L",
        name_jp="モンキー・D・ルフィ",
        image_url=f"https://card.yuyu-tei.jp/opc/100_140/{slug}/{product_id}.jpg",
        price_jpy=320,
        availability="in_stock",
        raw_listing_text=f"{card_code} モンキー・D・ルフィ 320 円 在庫 : 3 点",
        match_status=status,
        matched_card_print_id=card_print.id if card_print is not None else None,
        match_explanation_json={
            "reason": "unique_source_product_and_active_print",
            "card_code": card_code,
            "source_product_count": 1,
            "active_print_count": 1,
            "source_listing_complete": True,
        },
    )
    db.add(candidate)
    db.flush()
    return candidate


@pytest.fixture()
def seeded(db_session):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.add(
        ReleaseProduct(
            source_catalogue="jp",
            official_code="OP01",
            display_name="OP-01",
            first_seen_name="OP-01",
            source_series_id="OP01",
            source_url="https://example.test/OP-01",
            verification_status="verified",
        )
    )
    db_session.flush()
    print_row = make_print(db_session, "OP01-001")
    run = make_run(db_session)
    candidate = make_candidate(db_session, run, card_print=print_row)
    db_session.commit()
    return {
        "source": source,
        "print": print_row,
        "run": run,
        "candidate": candidate,
        "db": db_session,
    }


def approve(client, candidate_id, **body):
    return client.post(f"{BASE}/{candidate_id}/approve", json=body)


def refusal(response):
    """The refusal code from the shared error envelope."""
    return response.json()["detail"]["code"]


# --------------------------------------------------------------------------
# The happy path, and exactly what it writes
# --------------------------------------------------------------------------


def test_a_print_matched_candidate_can_be_approved(client, seeded, db_session):
    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 200
    body = response.json()

    assert body["mapping_created"] is True
    assert body["card_print_id"] == seeded["print"].id
    # The collector compares source_card_id to the displayed code with a bare
    # `!=` and no normalisation (yuyutei_collector/writer.py), so this must be
    # the parsed card code verbatim - never the URL.
    assert body["source_card_id"] == "OP01-001"
    assert body["source_url"] == listing("op01", "10001")
    assert body["candidate"]["approved"] is True

    mapping = db_session.scalars(select(SourceCardMapping)).one()
    assert mapping.card_print_id == seeded["print"].id
    assert mapping.review_status == "approved"
    assert mapping.is_active is True
    assert mapping.manual_verified is True
    # Print-authoritative: there is no legacy card to name, and card_prints
    # carries no link to `cards` from which one could be derived.
    assert mapping.card_id is None
    assert "OP01-001" in (mapping.review_notes or "")


def test_approval_creates_a_mapping_and_nothing_else(client, seeded, db_session):
    approve(client, seeded["candidate"].id)

    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 1
    # The candidate carried a listing price. It is evidence of what the shelf
    # said, not a measurement anyone made, and turning it into one here would
    # invent a price the collector never collected.
    assert db_session.scalar(select(func.count()).select_from(PriceObservation)) == 0
    assert db_session.scalar(select(func.count()).select_from(YuyuteiDiscoveryRun)) == 1


def test_the_candidate_row_is_not_mutated_by_approval(client, seeded, db_session):
    before = seeded["candidate"]
    original = (before.match_status, before.matched_card_print_id, before.price_jpy)

    approve(client, before.id)

    db_session.expire_all()
    after = db_session.get(YuyuteiCandidate, before.id)
    # Approval state is DERIVED from the mapping, so the candidate keeps its
    # cardinality vocabulary intact - it has no approval member to move to.
    assert (after.match_status, after.matched_card_print_id, after.price_jpy) == original


def test_approval_neither_invokes_the_collector_nor_market_index(client, seeded, monkeypatch):
    """A structural guard: the approval modules cannot reach either, because
    the names are not imported at all."""
    import ast
    import pathlib

    from app.api import yuyutei_candidates
    from app.services import yuyutei_candidate_approval, yuyutei_urls

    forbidden = {
        "market_index",
        "print_market_index",
        "snapshot_market_index",
        "run_batch",
        "run_market_workflow",
        "collect",
    }
    for module in (yuyutei_candidates, yuyutei_candidate_approval, yuyutei_urls):
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            (alias.asname or alias.name).split(".")[-1]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not (imported & forbidden), f"{module.__name__} imports {imported & forbidden}"
        assert "PriceObservation" not in imported


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_repeat_approval_is_idempotent(client, seeded, db_session):
    first = approve(client, seeded["candidate"].id)
    second = approve(client, seeded["candidate"].id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["mapping_created"] is True
    # The difference between a new priced listing and a no-op, reported rather
    # than hidden behind a second 200.
    assert second.json()["mapping_created"] is False
    assert second.json()["mapping_id"] == first.json()["mapping_id"]
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 1


def test_a_mapping_stored_with_a_query_string_is_the_same_listing(
    client, seeded, db_session
):
    """Idempotency is keyed on the parsed (set_slug, product_id), not on URL
    equality. A `source_url ==` filter would miss this row, create a SECOND
    mapping for one listing without tripping the unique constraint - because
    the stored strings genuinely differ - and the collector would price both.
    """
    db_session.add(
        SourceCardMapping(
            source_id=seeded["source"].id,
            card_print_id=seeded["print"].id,
            source_card_id="OP01-001",
            source_url=listing("op01", "10001") + "?ref=search",
            review_status="approved",
            is_active=True,
        )
    )
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 200
    assert response.json()["mapping_created"] is False
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 1


# --------------------------------------------------------------------------
# Candidate-status guards
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["family_matched", "unmatched", "identity_conflict"])
def test_only_print_matched_may_be_approved(client, seeded, db_session, status):
    # These statuses cannot carry a print id at all - the CHECK constraint
    # forbids it - so the candidate is built without one, which is exactly how
    # discovery writes them.
    candidate = make_candidate(
        db_session,
        seeded["run"],
        product_id="20001",
        status=status,
        card_print=None,
    )
    db_session.commit()

    response = approve(client, candidate.id)
    assert response.status_code == 409
    assert refusal(response) == "candidate_not_print_matched"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_a_print_matched_candidate_with_no_print_id_is_refused(client, seeded, db_session):
    """Unreachable through the DB constraint, so it is forced here directly:
    the service must still refuse rather than dereference a None."""
    candidate = seeded["candidate"]
    candidate.matched_card_print_id = None
    db_session.flush()

    response = approve(client, candidate.id)
    assert response.status_code == 400
    assert refusal(response) == "card_print_id_required"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


# --------------------------------------------------------------------------
# Print guards - reused wholesale from the shared exact-print contract
# --------------------------------------------------------------------------


def test_an_inactive_print_is_refused(client, seeded, db_session):
    seeded["print"].is_active = False
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 400
    assert refusal(response) == "print_inactive"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_an_unverified_print_is_refused(client, seeded, db_session):
    seeded["print"].verification_status = "unverified"
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 400
    assert refusal(response) == "print_unverified"


def test_a_nonexistent_print_is_refused(client, seeded, db_session):
    # The FK is ON DELETE SET NULL, so a deleted print cannot be pointed at
    # from a live row; the reachable shape is a stale id on a detached row.
    seeded["candidate"].matched_card_print_id = 999999
    db_session.flush()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 404
    assert refusal(response) == "print_not_found"


def test_a_print_for_a_different_card_code_is_refused(client, seeded, db_session):
    other = make_print(db_session, "OP01-999")
    seeded["candidate"].matched_card_print_id = other.id
    db_session.flush()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 400
    assert refusal(response) == "card_code_mismatch"


# --------------------------------------------------------------------------
# Discovery provenance - the guards SNKRDUNK does not need
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["running", "failed", "denied"])
def test_a_candidate_from_an_unfinished_run_is_refused(client, seeded, db_session, status):
    seeded["run"].status = status
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "discovery_run_incomplete"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_a_candidate_from_a_truncated_enumeration_is_refused(client, seeded, db_session):
    """The classification says one product carries this code. A truncated
    enumeration makes that a floor, not a total - the parallel may be on the
    page that was never fetched - so the 1:1 is unproven."""
    metrics = dict(seeded["run"].per_slug_metrics_json)
    metrics["op01"] = {**metrics["op01"], "enumeration_complete": False, "budget_exhausted": True}
    seeded["run"].per_slug_metrics_json = metrics
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "source_listing_truncated"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_a_candidate_whose_slug_has_no_recorded_metrics_is_refused(client, seeded, db_session):
    seeded["run"].per_slug_metrics_json = {}
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "source_listing_truncated"


def test_a_stale_candidate_from_an_older_run_of_the_same_slug_is_refused(
    client, seeded, db_session
):
    """The set was enumerated again and this row was NOT refreshed, which
    means the newest look at the source did not find this product. Its
    print_matched claim cannot be confirmed against the current listing."""
    make_run(db_session, slugs=("op01",))
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "candidate_superseded_by_newer_run"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_a_newer_run_of_a_DIFFERENT_slug_does_not_supersede(client, seeded, db_session):
    """Only a re-enumeration of the candidate's OWN slug can stale it. A
    later run over eb01 says nothing about op01."""
    make_run(db_session, slugs=("eb01",))
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 200


def test_a_refreshed_candidate_on_the_newest_run_is_approvable(client, seeded, db_session):
    """The other side of the staleness rule: re-discovery moves the candidate
    onto the new run, and that row is current."""
    newer = make_run(db_session, slugs=("op01",))
    seeded["candidate"].discovery_run_id = newer.id
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 200
    assert response.json()["mapping_created"] is True


# --------------------------------------------------------------------------
# Source identity
# --------------------------------------------------------------------------


def test_a_url_that_disagrees_with_the_natural_key_is_refused(client, seeded, db_session):
    """Product ids repeat across category slugs - 10152-10154 exist in both
    op01 and op13 - so a URL whose slug has drifted from the column means the
    row and the page are about different products."""
    seeded["candidate"].source_url = listing("op13", "10001")
    db_session.flush()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 400
    assert refusal(response) == "source_url_not_canonical"
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


def test_a_legacy_card_code_url_is_not_a_listing(client, seeded, db_session):
    """Two approved staging mappings predate product pages and end in a card
    code rather than a product id. That is not a listing, and a candidate
    carrying one cannot be approved."""
    seeded["candidate"].source_url = "https://yuyu-tei.jp/sell/opc/card/OP01-001"
    db_session.flush()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 400
    assert refusal(response) == "source_url_not_canonical"


# --------------------------------------------------------------------------
# Existing-mapping conflicts
# --------------------------------------------------------------------------


def test_a_mapping_naming_another_print_is_refused(client, seeded, db_session):
    other = make_print(db_session, "OP01-777")
    db_session.add(
        SourceCardMapping(
            source_id=seeded["source"].id,
            card_print_id=other.id,
            source_card_id="OP01-777",
            source_url=listing("op01", "10001"),
            review_status="approved",
            is_active=True,
        )
    )
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "existing_mapping_names_another_print"
    # The existing row is left exactly as it was.
    assert db_session.scalars(select(SourceCardMapping)).one().card_print_id == other.id


def test_a_rejected_mapping_is_not_silently_overturned(client, seeded, db_session):
    db_session.add(
        SourceCardMapping(
            source_id=seeded["source"].id,
            card_print_id=seeded["print"].id,
            source_card_id="OP01-001",
            source_url=listing("op01", "10001"),
            review_status="rejected",
            review_notes="wrong product, checked 2026-08-30",
            is_active=True,
        )
    )
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "existing_mapping_was_rejected"
    assert db_session.scalars(select(SourceCardMapping)).one().review_status == "rejected"


def test_two_mappings_for_one_listing_are_reported_not_chosen_between(
    client, seeded, db_session
):
    for suffix in ("", "?ref=a"):
        db_session.add(
            SourceCardMapping(
                source_id=seeded["source"].id,
                card_print_id=seeded["print"].id,
                source_card_id="OP01-001",
                source_url=listing("op01", "10001") + suffix,
                review_status="approved",
                is_active=True,
            )
        )
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 409
    assert refusal(response) == "multiple_mappings_for_listing"
    assert len(response.json()["detail"]["alternatives"]) == 2


def test_a_mapping_for_another_product_in_the_same_set_is_not_a_conflict(
    client, seeded, db_session
):
    """The pre-filter is keyed on `/slug/product_id`, not on the bare id, so a
    different product in the same set is a different listing."""
    other = make_print(db_session, "OP01-002")
    db_session.add(
        SourceCardMapping(
            source_id=seeded["source"].id,
            card_print_id=other.id,
            source_card_id="OP01-002",
            source_url=listing("op01", "10002"),
            review_status="approved",
            is_active=True,
        )
    )
    db_session.commit()

    response = approve(client, seeded["candidate"].id)
    assert response.status_code == 200
    assert response.json()["mapping_created"] is True
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 2


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


@pytest.fixture()
def raw_client():
    """No X-Admin-Token header."""
    return TestClient(app)


@pytest.mark.parametrize(
    "method,path",
    [("get", BASE), ("get", f"{BASE}/1"), ("post", f"{BASE}/1/approve")],
)
def test_anonymous_access_is_refused(raw_client, seeded, method, path):
    response = getattr(raw_client, method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", [("get", BASE), ("post", f"{BASE}/1/approve")])
def test_a_wrong_admin_token_is_refused(raw_client, seeded, method, path):
    response = getattr(raw_client, method)(
        path,
        headers={"X-Admin-Token": "not-the-token"},
        **({"json": {}} if method == "post" else {}),
    )
    assert response.status_code == 401


def test_an_unauthorized_approval_writes_nothing(raw_client, seeded, db_session):
    raw_client.post(f"{BASE}/{seeded['candidate'].id}/approve", json={})
    assert db_session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0


# --------------------------------------------------------------------------
# The review surface
# --------------------------------------------------------------------------


def test_the_queue_defaults_to_print_matched(client, seeded, db_session):
    make_candidate(
        db_session, seeded["run"], product_id="30001", status="family_matched", card_print=None
    )
    make_candidate(
        db_session, seeded["run"], product_id="30002", status="unmatched", card_print=None
    )
    db_session.commit()

    body = client.get(BASE).json()
    assert body["total"] == 1
    assert {item["match_status"] for item in body["items"]} == {"print_matched"}


def test_every_review_field_reaches_the_queue(client, seeded):
    item = client.get(BASE).json()["items"][0]
    for field in (
        "set_slug",
        "product_id",
        "detected_card_code",
        "name_jp",
        "detected_rarity",
        "price_jpy",
        "availability",
        "image_url",
        "match_status",
        "matched_card_print_id",
        "match_explanation_json",
    ):
        assert item[field] is not None, field
    assert item["matched_print"]["card_code"] == "OP01-001"
    assert item["matched_print"]["verification_status"] == "verified"
    assert item["match_explanation_json"]["reason"] == "unique_source_product_and_active_print"


def test_the_queue_filters_by_set_and_status(client, seeded, db_session):
    other_run = seeded["run"]
    other_run.requested_set_slugs = ["op01", "eb01"]
    metrics = dict(other_run.per_slug_metrics_json)
    metrics["eb01"] = {**metrics["op01"], "slug": "eb01"}
    other_run.per_slug_metrics_json = metrics
    make_candidate(
        db_session, other_run, slug="eb01", product_id="40001", card_code="EB01-001",
        card_print=make_print(db_session, "EB01-001", product_code="EB01"),
    )
    db_session.commit()

    assert client.get(BASE, params={"set_slug": "eb01"}).json()["total"] == 1
    assert client.get(BASE, params={"set_slug": "op01"}).json()["total"] == 1
    assert client.get(BASE, params={"match_status": ""}).json()["total"] == 2
    assert client.get(BASE, params={"match_status": "nonsense"}).status_code == 400


def test_the_queue_filters_on_derived_approval_state(client, seeded, db_session):
    make_candidate(db_session, seeded["run"], product_id="50001", card_code="OP01-001",
                   card_print=seeded["print"])
    db_session.commit()

    assert client.get(BASE, params={"approved": False}).json()["total"] == 2
    assert client.get(BASE, params={"approved": True}).json()["total"] == 0

    approve(client, seeded["candidate"].id)

    assert client.get(BASE, params={"approved": True}).json()["total"] == 1
    assert client.get(BASE, params={"approved": False}).json()["total"] == 1


def test_a_missing_candidate_is_404(client, seeded):
    assert client.get(f"{BASE}/999999").status_code == 404
    assert approve(client, 999999).status_code == 404
