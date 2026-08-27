"""No path may walk a print-less mapping into `approved`.

4F-1 closed the endpoints that CREATE a mapping. A row can also become
approved by having its review state flipped, and those endpoints never looked
at `card_print_id` - so a legacy row could reach `approved` without ever
passing the exact-print contract. Staging holds fourteen such rows.

The rule under test is narrow: entering `approved` requires a card_print_id
naming an active, verified print. Leaving `approved` alone, rejecting,
deactivating and reading are all untouched, and rows that are ALREADY approved
are grandfathered rather than demoted.
"""

import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.seed import SOURCES
from app.services.exact_print_approval import (
    REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT,
    REFUSAL_PRINT_INACTIVE,
    REFUSAL_PRINT_UNVERIFIED,
)


@pytest.fixture()
def fixtures(db_session):
    db = db_session
    for data in SOURCES:
        db.add(Source(**data))
    db.add(
        Card(
            card_code="OP01-001",
            name_en="Monkey D. Luffy",
            name_jp="モンキー・D・ルフィ",
            set_code="OP-01",
            rarity="L",
            language="jp",
        )
    )
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
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        card_type="Leader",
        rarity="L",
    )
    db.add(canonical)
    db.flush()
    print_row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key="sha256:OP01-001-base",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    db.add(print_row)
    db.commit()
    db.refresh(print_row)
    return {
        "db": db,
        "card": db.query(Card).filter_by(card_code="OP01-001").one(),
        "source": db.query(Source).filter_by(name="yuyutei").one(),
        "print": print_row,
    }


def _mapping(fixtures, *, review_status: str, card_print_id: int | None, url: str, **kw):
    row = SourceCardMapping(
        card_id=fixtures["card"].id,
        source_id=fixtures["source"].id,
        source_card_id="OP01-001",
        source_url=url,
        card_print_id=card_print_id,
        review_status=review_status,
        **kw,
    )
    fixtures["db"].add(row)
    fixtures["db"].commit()
    fixtures["db"].refresh(row)
    return row


def _snapshot(row: SourceCardMapping) -> dict:
    """Every field an approval could plausibly touch, so 'unchanged' is a
    claim about the row rather than about review_status alone."""
    return {
        "review_status": row.review_status,
        "is_active": row.is_active,
        "card_print_id": row.card_print_id,
        "card_id": row.card_id,
        "manual_verified": row.manual_verified,
        "last_verified_at": row.last_verified_at,
        "review_notes": row.review_notes,
        "source_url": row.source_url,
    }


# --- 1 & 2: approval refused for a print-less row ----------------------------


@pytest.mark.parametrize("status", ["needs_review", "rejected"])
def test_approve_refuses_a_mapping_with_no_card_print(client, fixtures, status):
    row = _mapping(
        fixtures, review_status=status, card_print_id=None,
        url=f"https://yuyu-tei.jp/legacy/{status}", is_active=(status != "rejected"),
    )
    before = _snapshot(row)

    response = client.post(f"/admin/source-mappings/{row.id}/approve")

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
    assert body["needs_review"] is True

    fixtures["db"].refresh(row)
    assert _snapshot(row) == before, "a refused approval must leave the row untouched"


def test_patch_cannot_walk_a_print_less_row_into_approved(client, fixtures):
    """PATCH sets review_status directly, so it is a transition into approved
    too - and a refused PATCH must not apply its other fields either."""
    row = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/legacy/patch",
    )
    before = _snapshot(row)

    response = client.patch(
        f"/admin/source-mappings/{row.id}",
        json={"review_status": "approved", "review_notes": "should not stick"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
    fixtures["db"].refresh(row)
    assert _snapshot(row) == before


# --- 3: rejecting still works ------------------------------------------------


def test_a_print_less_mapping_can_still_be_rejected(client, fixtures):
    row = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/legacy/reject-me",
    )

    response = client.post(f"/admin/source-mappings/{row.id}/reject")

    assert response.status_code == 200
    fixtures["db"].refresh(row)
    assert row.review_status == "rejected"
    assert row.is_active is False
    assert row.card_print_id is None


def test_a_print_less_mapping_can_still_be_patched_to_a_non_approved_status(client, fixtures):
    row = _mapping(
        fixtures, review_status="approved", card_print_id=None,
        url="https://yuyu-tei.jp/legacy/demote-by-hand",
    )

    response = client.patch(
        f"/admin/source-mappings/{row.id}",
        json={"review_status": "needs_review", "review_notes": "operator demoted"},
    )

    assert response.status_code == 200
    fixtures["db"].refresh(row)
    assert row.review_status == "needs_review"
    assert row.review_notes == "operator demoted"


# --- 4: a real exact-print mapping approves normally -------------------------


def test_approve_succeeds_for_a_mapping_naming_an_active_verified_print(client, fixtures):
    row = _mapping(
        fixtures, review_status="needs_review", card_print_id=fixtures["print"].id,
        url="https://yuyu-tei.jp/exact/1",
    )

    response = client.post(f"/admin/source-mappings/{row.id}/approve")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "approved"
    assert body["card_print_id"] == fixtures["print"].id
    fixtures["db"].refresh(row)
    assert row.is_active is True
    assert row.last_verified_at is not None


def test_patch_to_approved_succeeds_for_an_exact_print_mapping(client, fixtures):
    row = _mapping(
        fixtures, review_status="needs_review", card_print_id=fixtures["print"].id,
        url="https://yuyu-tei.jp/exact/2",
    )

    response = client.patch(
        f"/admin/source-mappings/{row.id}", json={"review_status": "approved"}
    )

    assert response.status_code == 200, response.text
    fixtures["db"].refresh(row)
    assert row.review_status == "approved"


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda p: setattr(p, "is_active", False), REFUSAL_PRINT_INACTIVE),
        (
            lambda p: setattr(p, "verification_status", "needs_review"),
            REFUSAL_PRINT_UNVERIFIED,
        ),
    ],
)
def test_approve_refuses_when_the_named_print_is_no_longer_priceable(
    client, fixtures, mutate, expected
):
    """Naming a print is not enough if that print has since been deactivated
    or un-verified - the same three facts are checked here as at creation."""
    row = _mapping(
        fixtures, review_status="needs_review", card_print_id=fixtures["print"].id,
        url="https://yuyu-tei.jp/exact/stale",
    )
    mutate(fixtures["print"])
    fixtures["db"].commit()
    before = _snapshot(row)

    response = client.post(f"/admin/source-mappings/{row.id}/approve")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == expected
    fixtures["db"].refresh(row)
    assert _snapshot(row) == before


# --- 5: already-approved legacy rows are grandfathered, not rewritten --------


def test_an_already_approved_print_less_row_is_not_demoted_by_reading_it(client, fixtures):
    """The six approved Yuyu-Tei rows on staging predate exact prints. They
    stay readable and keep their status; the guard stops the set growing, it
    does not rewrite history."""
    row = _mapping(
        fixtures, review_status="approved", card_print_id=None,
        url="https://yuyu-tei.jp/legacy/grandfathered", manual_verified=True,
    )
    before = _snapshot(row)

    listed = client.get("/admin/source-mappings")
    assert listed.status_code == 200
    entry = next(i for i in listed.json()["items"] if i["id"] == row.id)
    assert entry["review_status"] == "approved"
    assert entry["card_print_id"] is None

    single = client.get(f"/admin/source-mappings/{row.id}")
    assert single.status_code == 200
    assert single.json()["review_status"] == "approved"

    fixtures["db"].refresh(row)
    assert _snapshot(row) == before, "reading must never rewrite a legacy row"


def test_re_approving_an_already_approved_legacy_row_is_not_a_transition(client, fixtures):
    """Re-running approve on a row that is already approved is a no-op in
    review terms, so it is allowed rather than refused - the guard governs
    entering `approved`, and this row is already there."""
    row = _mapping(
        fixtures, review_status="approved", card_print_id=None,
        url="https://yuyu-tei.jp/legacy/re-approve",
    )

    response = client.post(f"/admin/source-mappings/{row.id}/approve")

    assert response.status_code == 200
    fixtures["db"].refresh(row)
    assert row.review_status == "approved"
    assert row.card_print_id is None, "and no print was invented for it"


# --- 6: no alternate approval endpoint bypasses the rule ---------------------


def test_bulk_approve_refuses_print_less_rows_and_still_applies_the_rest(client, fixtures):
    legacy = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/bulk/legacy",
    )
    exact = _mapping(
        fixtures, review_status="needs_review", card_print_id=fixtures["print"].id,
        url="https://yuyu-tei.jp/bulk/exact",
    )
    before = _snapshot(legacy)

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [legacy.id, exact.id], "action": "approve"},
    )

    assert response.status_code == 200, response.text
    results = {r["mapping_id"]: r for r in response.json()["results"]}
    assert results[legacy.id]["ok"] is False
    assert results[legacy.id]["error"] == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
    assert results[exact.id]["ok"] is True

    fixtures["db"].refresh(legacy)
    fixtures["db"].refresh(exact)
    assert _snapshot(legacy) == before
    assert exact.review_status == "approved"


def test_bulk_reject_still_works_on_a_print_less_row(client, fixtures):
    legacy = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/bulk/reject",
    )

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [legacy.id], "action": "reject"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["ok"] is True
    fixtures["db"].refresh(legacy)
    assert legacy.review_status == "rejected"


def test_replace_card_cannot_approve_a_print_less_row(client, fixtures):
    """replace-card reassigns the legacy card pointer and can approve in the
    same call. It resolves no exact print, so approving through it is refused
    - and the card reassignment must not land either."""
    legacy = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/replace/legacy",
    )
    before = _snapshot(legacy)

    response = client.post(
        f"/admin/source-mappings/{legacy.id}/replace-card",
        json={"card_id": fixtures["card"].id, "approve": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
    fixtures["db"].refresh(legacy)
    assert _snapshot(legacy) == before


def test_replace_card_without_approving_still_works(client, fixtures):
    """Reassigning the legacy card pointer without claiming approval is
    unaffected - the guard is about entering `approved`, nothing else."""
    legacy = _mapping(
        fixtures, review_status="needs_review", card_print_id=None,
        url="https://yuyu-tei.jp/replace/no-approve",
    )

    response = client.post(
        f"/admin/source-mappings/{legacy.id}/replace-card",
        json={"card_id": fixtures["card"].id, "approve": False},
    )

    assert response.status_code == 200, response.text
    fixtures["db"].refresh(legacy)
    assert legacy.review_status != "approved"
    assert legacy.card_id == fixtures["card"].id


def test_every_route_that_can_write_approved_runs_the_guard():
    """A structural check, so a NEW approval endpoint cannot quietly appear
    without one.

    Greps the router layer for writes of review_status = "approved" and
    asserts each module containing one also imports the guard. It is a
    tripwire, not a proof - but it fails loudly the next time someone adds a
    fifth approval surface.
    """
    import pathlib

    api_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    offenders = []
    for path in api_dir.glob("*.py"):
        text = path.read_text()
        writes_approved = any(
            line.strip().startswith(("mapping.review_status =", "review_status="))
            and '"approved"' in line
            for line in text.splitlines()
        )
        if writes_approved and "guard_transition_to_approved" not in text:
            # The candidate approval paths resolve an exact print themselves,
            # which is a stronger check than the guard, so they are exempt.
            if "resolve_exact_print" not in text:
                offenders.append(path.name)
    assert offenders == [], f"approval written without the exact-print guard in: {offenders}"
