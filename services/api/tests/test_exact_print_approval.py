"""The exact-print gate on new source-mapping approvals.

The fixtures below are the real shape of the staging catalogue, not a
convenient simplification. OP02-013 genuinely is five active verified prints -
the OP-02 base, an OP-02 `p1` and `p2`, an `r1` reprint carried in PRB-01, and
an `SPカード` `p3` from OP-08 - and that is exactly the case a card-code-only
approval gets wrong. OP01-016 spans six products for one code. Both are used
here because a mapping approved against either from the code alone is a claim
nobody can substantiate.
"""

import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.seed import SOURCES
from app.services.exact_print_approval import (
    REFUSAL_AMBIGUOUS,
    REFUSAL_CARD_CODE_MISMATCH,
    REFUSAL_EVIDENCE_CONTRADICTS,
    REFUSAL_NO_SOURCE_CARD_CODE,
    REFUSAL_PRINT_INACTIVE,
    REFUSAL_PRINT_NOT_FOUND,
    REFUSAL_PRINT_REQUIRED,
    REFUSAL_PRINT_UNVERIFIED,
    REFUSAL_UNRESOLVED_SOURCE_PRODUCT,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
)


def _product(db, code: str) -> ReleaseProduct:
    row = ReleaseProduct(
        source_catalogue="jp",
        official_code=code,
        display_name=code,
        first_seen_name=code,
        source_series_id=code.replace("-", ""),
        source_url=f"https://example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _canonical(db, card_code: str, **kw) -> CanonicalCard:
    row = CanonicalCard(
        card_code=card_code,
        name_en=kw.pop("name_en", "Portgas.D.Ace"),
        name_jp=kw.pop("name_jp", "ポートガス・D・エース"),
        card_type=kw.pop("card_type", "Character"),
        rarity=kw.pop("rarity", "SR"),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _print(db, canonical, product, variant, **kw) -> CardPrint:
    row = CardPrint(
        canonical_card_id=canonical.id,
        language=kw.pop("language", "jp"),
        release_product_code=product.official_code if product else None,
        release_product_id=product.id if product else None,
        artwork_key=kw.pop("artwork_key", f"sha256:{canonical.card_code}-{variant}"),
        official_asset_variant=variant,
        verification_status=kw.pop("verification_status", "verified"),
        is_active=kw.pop("is_active", True),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def catalogue(db_session):
    """OP02-013 as staging holds it: one card code, five distinct printings."""
    db = db_session
    for data in SOURCES:
        db.add(Source(**data))
    # The legacy card the mapping's NOT NULL card_id still points at.
    db.add(
        Card(
            card_code="OP02-013",
            name_en="Portgas.D.Ace",
            name_jp="ポートガス・D・エース",
            set_code="OP-02",
            rarity="SR",
            language="jp",
        )
    )

    op02 = _product(db, "OP-02")
    op08 = _product(db, "OP-08")
    prb01 = _product(db, "PRB-01")

    ace = _canonical(db, "OP02-013")
    prints = {
        "base": _print(db, ace, op02, "base"),
        "p1": _print(db, ace, op02, "p1"),
        "p2": _print(db, ace, op02, "p2"),
        "r1": _print(db, ace, prb01, "r1"),
        "sp_p3": _print(db, ace, op08, "p3", official_rarity="SPカード"),
    }

    # A second code with exactly one printing, for the unambiguous case.
    solo_card = _canonical(db, "OP01-999", name_en="Solo Print", rarity="R")
    prints["solo"] = _print(db, solo_card, op02, "base")

    db.commit()
    return {"db": db, "prints": prints, "canonical": ace}


def _evidence(**kw) -> SourceEvidence:
    base = {
        "source_name": "snkrdunk",
        "source_url": "https://snkrdunk.com/cards/ace-1",
        "card_code": "OP02-013",
    }
    base.update(kw)
    return SourceEvidence(**base)


# --- the gate itself ---------------------------------------------------------


def test_exact_print_approval_succeeds_when_evidence_names_product_and_variant(catalogue):
    """The only shape that is allowed through: the source said which product
    and which official asset, and exactly one print answers to both."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_evidence(set_code="OP-02", variant="p2"),
    )
    assert decision.card_print.id == catalogue["prints"]["p2"].id
    assert decision.canonical.card_code == "OP02-013"
    assert "product OP-02" in decision.evidence_used
    assert "asset variant p2" in decision.evidence_used


def test_missing_card_print_id_refuses(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(catalogue["db"], card_print_id=None, evidence=_evidence())
    assert exc.value.code == REFUSAL_PRINT_REQUIRED


def test_nonexistent_print_refuses(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(catalogue["db"], card_print_id=999_999, evidence=_evidence())
    assert exc.value.code == REFUSAL_PRINT_NOT_FOUND


def test_inactive_print_refuses(catalogue):
    db = catalogue["db"]
    row = catalogue["prints"]["p1"]
    row.is_active = False
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db, card_print_id=row.id, evidence=_evidence(set_code="OP-02", variant="p1")
        )
    assert exc.value.code == REFUSAL_PRINT_INACTIVE


def test_unverified_print_refuses(catalogue):
    db = catalogue["db"]
    row = catalogue["prints"]["p1"]
    row.verification_status = "needs_review"
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db, card_print_id=row.id, evidence=_evidence(set_code="OP-02", variant="p1")
        )
    assert exc.value.code == REFUSAL_PRINT_UNVERIFIED


def test_card_code_alone_cannot_select_among_products(catalogue):
    """OP02-013 spans OP-02, OP-08 and PRB-01. A listing that says only
    "OP02-013" is consistent with all five printings and identifies none."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(),
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert exc.value.needs_review is True
    assert len(exc.value.alternatives) == 5


def test_product_evidence_alone_cannot_select_among_artworks(catalogue):
    """Narrowing to OP-02 still leaves base, p1 and p2. Three artworks, one
    product: the product is not enough either."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(set_code="OP-02"),
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert sorted(exc.value.alternatives) == sorted(
        [
            catalogue["prints"]["base"].id,
            catalogue["prints"]["p1"].id,
            catalogue["prints"]["p2"].id,
        ]
    )


def test_variant_evidence_alone_can_be_enough_when_it_is_unique(catalogue):
    """`p3` occurs once across the whole code, so the asset address alone
    does distinguish it. Sufficiency is measured, never assumed by field."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["sp_p3"].id,
        evidence=_evidence(variant="p3"),
    )
    assert decision.card_print.id == catalogue["prints"]["sp_p3"].id


def test_single_print_card_code_needs_no_further_evidence(catalogue):
    """When the code has exactly one active verified print there is nothing
    left to be ambiguous about."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["solo"].id,
        evidence=_evidence(card_code="OP01-999"),
    )
    assert decision.card_print.id == catalogue["prints"]["solo"].id


def test_evidence_that_contradicts_the_operators_choice_refuses(catalogue):
    """The operator picked the PRB-01 reprint; the source described an OP-02
    printing. An explicit human choice is required but never self-justifying."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["r1"].id,
            evidence=_evidence(set_code="OP-02", variant="p1"),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS
    assert exc.value.alternatives == [catalogue["prints"]["p1"].id]


def test_card_code_mismatch_refuses(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(card_code="OP03-001"),
        )
    assert exc.value.code == REFUSAL_CARD_CODE_MISMATCH


def test_missing_source_card_code_refuses(catalogue):
    """No anchor at all. Inferring a code from the free-text title is exactly
    the inference this forbids."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(card_code=None, title="Ace SR parallel"),
        )
    assert exc.value.code == REFUSAL_NO_SOURCE_CARD_CODE


def test_separator_variation_is_not_a_difference_in_fact(catalogue):
    """Sources write OP-02 / OP02 / op 02 interchangeably."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_evidence(card_code="op02013", set_code="op 02", variant="P2"),
    )
    assert decision.card_print.id == catalogue["prints"]["p2"].id


def test_evidence_matching_no_print_at_all_refuses(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(set_code="OP-99"),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS


def test_unverified_sibling_is_not_counted_as_a_rival(catalogue):
    """Only active verified prints can be priced, so only they can make a
    decision ambiguous."""
    db = catalogue["db"]
    for key in ("p1", "p2", "r1", "sp_p3"):
        catalogue["prints"][key].verification_status = "unverified"
    db.commit()
    decision = resolve_exact_print(
        db, card_print_id=catalogue["prints"]["base"].id, evidence=_evidence()
    )
    assert decision.card_print.id == catalogue["prints"]["base"].id


# --- the approval endpoints --------------------------------------------------


@pytest.fixture()
def candidate(catalogue):
    db = catalogue["db"]
    row = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/cards/ace-1",
        title="OP02-013 ポートガス・D・エース SR",
        price_jpy=1500,
        detected_card_code="OP02-013",
        match_status="suggested",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _card_id(catalogue) -> int:
    return catalogue["db"].query(Card).filter_by(card_code="OP02-013").one().id


def test_approve_match_writes_the_exact_print(client, catalogue, candidate):
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p2"
    catalogue["db"].commit()

    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={
            "card_id": _card_id(catalogue),
            "card_print_id": catalogue["prints"]["p2"].id,
        },
    )
    assert response.status_code == 200, response.text

    mapping = catalogue["db"].query(SourceCardMapping).one()
    assert mapping.card_print_id == catalogue["prints"]["p2"].id
    assert mapping.review_status == "approved"
    # The legacy pointer is still written, because the column is NOT NULL.
    assert mapping.card_id == _card_id(catalogue)


def test_approve_match_without_card_print_id_is_rejected_by_the_schema(
    client, catalogue, candidate
):
    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_id": _card_id(catalogue)},
    )
    assert response.status_code == 422
    assert catalogue["db"].query(SourceCardMapping).count() == 0


def test_approve_match_refuses_an_ambiguous_card_code(client, catalogue, candidate):
    """The candidate carries only the card code, which OP02-013 shares across
    five printings. Nothing is written."""
    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={
            "card_id": _card_id(catalogue),
            "card_print_id": catalogue["prints"]["base"].id,
        },
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == REFUSAL_AMBIGUOUS
    assert body["needs_review"] is True
    assert len(body["alternatives"]) == 5
    assert catalogue["db"].query(SourceCardMapping).count() == 0


def test_approve_match_refuses_an_unverified_print(client, catalogue, candidate):
    db = catalogue["db"]
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p2"
    catalogue["prints"]["p2"].verification_status = "unverified"
    db.commit()

    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={
            "card_id": _card_id(catalogue),
            "card_print_id": catalogue["prints"]["p2"].id,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == REFUSAL_PRINT_UNVERIFIED
    assert db.query(SourceCardMapping).count() == 0


def test_approve_match_refuses_a_nonexistent_print(client, catalogue, candidate):
    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_id": _card_id(catalogue), "card_print_id": 999_999},
    )
    assert response.status_code == 404
    assert catalogue["db"].query(SourceCardMapping).count() == 0


def test_manual_match_endpoint_also_requires_the_exact_print(client, catalogue, candidate):
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p1"
    catalogue["db"].commit()

    refused = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": _card_id(catalogue)},
    )
    assert refused.status_code == 422

    ok = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={
            "card_id": _card_id(catalogue),
            "card_print_id": catalogue["prints"]["p1"].id,
        },
    )
    assert ok.status_code == 200, ok.text
    mapping = catalogue["db"].query(SourceCardMapping).one()
    assert mapping.card_print_id == catalogue["prints"]["p1"].id


# --- duplicate protection ----------------------------------------------------


def test_one_listing_cannot_be_approved_to_two_prints(client, catalogue, candidate):
    """The existing contract is UNIQUE (source_id, source_url). Approving the
    same listing again moves that ONE row; it never creates a second mapping
    pointing at a different print. This asserts the repository's existing
    uniqueness semantics rather than adding a new rule."""
    db = catalogue["db"]
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p1"
    db.commit()

    first = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_id": _card_id(catalogue), "card_print_id": catalogue["prints"]["p1"].id},
    )
    assert first.status_code == 200, first.text

    candidate.detected_variant = "p2"
    db.commit()
    second = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_id": _card_id(catalogue), "card_print_id": catalogue["prints"]["p2"].id},
    )
    assert second.status_code == 200, second.text

    mappings = db.query(SourceCardMapping).all()
    assert len(mappings) == 1, "a second row would be a second claim about one listing"
    assert mappings[0].card_print_id == catalogue["prints"]["p2"].id


def test_two_distinct_listings_may_map_to_two_prints_of_one_card(client, catalogue):
    """The constraint is per listing, not per card: SNKRDUNK legitimately
    sells the base print and the p2 as separate items."""
    db = catalogue["db"]
    made = []
    for url, variant, key in [
        ("https://snkrdunk.com/cards/ace-base", "base", "base"),
        ("https://snkrdunk.com/cards/ace-p2", "p2", "p2"),
    ]:
        row = SnkrdunkCandidate(
            source_url=url,
            title=f"OP02-013 {variant}",
            detected_card_code="OP02-013",
            detected_set_code="OP-02",
            detected_variant=variant,
            match_status="suggested",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        response = client.post(
            f"/admin/snkrdunk-candidates/{row.id}/approve-match",
            json={"card_id": _card_id(catalogue), "card_print_id": catalogue["prints"][key].id},
        )
        assert response.status_code == 200, response.text
        made.append(catalogue["prints"][key].id)

    mappings = db.query(SourceCardMapping).all()
    assert len(mappings) == 2
    assert sorted(m.card_print_id for m in mappings) == sorted(made)


# --- what approval must NOT do ----------------------------------------------


def test_approval_creates_no_price_observation(client, catalogue, candidate):
    """Approval establishes identity, not price. Observations are the
    collectors' job, and this task does not run them."""
    from app.models import PriceObservation

    db = catalogue["db"]
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p2"
    db.commit()

    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_id": _card_id(catalogue), "card_print_id": catalogue["prints"]["p2"].id},
    )
    assert response.status_code == 200, response.text
    assert db.query(PriceObservation).count() == 0


def test_a_legacy_card_id_only_mapping_still_reads_correctly(client, catalogue):
    """The 74 rows already on staging keep working: card_print_id is NULL,
    and nothing here rewrites or migrates them."""
    db = catalogue["db"]
    source = db.query(Source).filter_by(name="yuyutei").one()
    legacy = SourceCardMapping(
        card_id=_card_id(catalogue),
        source_id=source.id,
        source_card_id="OP02-013",
        source_url="https://yuyu-tei.jp/legacy/1",
        review_status="approved",
        is_active=True,
    )
    db.add(legacy)
    db.commit()
    db.refresh(legacy)
    assert legacy.card_print_id is None

    response = client.get(f"/admin/source-mappings/{legacy.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["card_print_id"] is None
    assert body["card_id"] == _card_id(catalogue)
    assert body["review_status"] == "approved"


def test_patch_cannot_reassign_the_exact_print(client, catalogue):
    """Reassignment has to go through an approval path that runs the gate, so
    the PATCH schema deliberately has no card_print_id and silently ignores
    one rather than writing it."""
    db = catalogue["db"]
    source = db.query(Source).filter_by(name="yuyutei").one()
    mapping = SourceCardMapping(
        card_id=_card_id(catalogue),
        source_id=source.id,
        source_card_id="OP02-013",
        source_url="https://yuyu-tei.jp/legacy/2",
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}",
        json={"card_print_id": catalogue["prints"]["p2"].id, "review_notes": "hand edit"},
    )
    assert response.status_code == 200, response.text
    db.refresh(mapping)
    assert mapping.card_print_id is None
    assert mapping.review_notes == "hand edit"


# --- the operator's decision aid ---------------------------------------------


def test_print_options_shows_every_rival_printing_with_collector_facts(
    client, catalogue, candidate
):
    response = client.get(f"/admin/snkrdunk-candidates/{candidate.id}/print-options")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["candidate"]["source"] == "snkrdunk"
    assert body["candidate"]["source_url"] == candidate.source_url
    assert body["candidate"]["detected_card_code"] == "OP02-013"

    assert len(body["options"]) == 5
    assert body["resolvable_card_print_id"] is None
    assert "0 of 5" in body["ambiguity_reason"]

    by_id = {o["card_print_id"]: o for o in body["options"]}
    sp = by_id[catalogue["prints"]["sp_p3"].id]
    assert sp["special_print"] == "SP Card"
    assert sp["printing"] == "Alt Art"
    assert sp["found_in_product"] == "OP-08"
    assert sp["name_en"] == "Portgas.D.Ace"
    assert sp["name_jp"] == "ポートガス・D・エース"

    reprint = by_id[catalogue["prints"]["r1"].id]
    assert reprint["printing"] == "Reprint"
    assert reprint["found_in_product"] == "PRB-01"

    base = by_id[catalogue["prints"]["base"].id]
    assert base["printing"] is None
    assert base["special_print"] is None

    # Raw published tokens never reach the operator as the label.
    assert "SPカード" not in response.text


def test_print_options_marks_the_single_approvable_option(client, catalogue, candidate):
    candidate.detected_set_code = "OP-02"
    candidate.detected_variant = "p2"
    catalogue["db"].commit()

    body = client.get(f"/admin/snkrdunk-candidates/{candidate.id}/print-options").json()
    assert body["resolvable_card_print_id"] == catalogue["prints"]["p2"].id
    assert body["ambiguity_reason"] is None
    approvable = [o for o in body["options"] if o["approvable"]]
    assert [o["card_print_id"] for o in approvable] == [catalogue["prints"]["p2"].id]
    # The rivals are still listed, each saying why it cannot be chosen.
    refused = [o for o in body["options"] if not o["approvable"]]
    assert len(refused) == 4
    assert all(o["refusal_code"] for o in refused)


def test_print_options_assigns_an_art_ordinal_only_where_it_disambiguates(
    client, catalogue, candidate
):
    body = client.get(f"/admin/snkrdunk-candidates/{candidate.id}/print-options").json()
    by_id = {o["card_print_id"]: o for o in body["options"]}
    # Three OP-02 prints share product+language, so they get ordinals.
    assert by_id[catalogue["prints"]["base"].id]["art_ordinal"] == 1
    assert by_id[catalogue["prints"]["p1"].id]["art_ordinal"] == 2
    assert by_id[catalogue["prints"]["p2"].id]["art_ordinal"] == 3
    # The PRB-01 and OP-08 prints are alone in their product and need none.
    assert by_id[catalogue["prints"]["r1"].id]["art_ordinal"] is None
    assert by_id[catalogue["prints"]["sp_p3"].id]["art_ordinal"] is None


# --- 4F-3C: unresolved product evidence is not absent evidence ----------------
#
# The 2026-08-27 staging replay found four of six "exact" SNKRDUNK candidates
# were exact only because Atlas holds no print of the product the listing
# named, leaving one unrelated printing standing unopposed. These pin the four
# cases apart: no label, resolved label, unresolved label, contradicting label.
#
# Labels are verbatim from discovery run 1.

PCC = "Premium Card Collection 25th Anniversary Edition"
WSJ = "Weekly Shonen Jump 2023 6th and 7th issue All applicants service Recafig"


def _solo_evidence(**kw) -> SourceEvidence:
    """Evidence for OP01-999, the card code with exactly ONE active verified
    print - the shape that produced every exact-by-absence verdict."""
    base = {
        "source_name": "snkrdunk",
        "source_url": "https://snkrdunk.com/cards/solo-1",
        "card_code": "OP01-999",
    }
    base.update(kw)
    return SourceEvidence(**base)


def test_no_product_label_still_resolves_a_lone_print_exactly(catalogue):
    """Case A, unchanged. Silence narrows nothing, and a card code with one
    printing is genuinely unambiguous."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["solo"].id,
        evidence=_solo_evidence(),
    )
    assert decision.card_print.id == catalogue["prints"]["solo"].id
    assert decision.evidence_used == ["card code OP01-999"]


def test_an_unresolved_product_label_refuses_even_a_lone_print(catalogue):
    """Case C, and the whole point of the tranche.

    Before this rule the same call returned exact. One survivor under a label
    Atlas cannot read usually means Atlas holds no print of the named product -
    the survivor is not the answer, it is the only wrong answer available."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["solo"].id,
            evidence=_solo_evidence(product_label=PCC),
        )
    assert err.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT
    assert err.value.needs_review
    # The operator still sees what Atlas does hold.
    assert err.value.alternatives == [catalogue["prints"]["solo"].id]


def test_an_unresolved_product_label_refuses_when_many_prints_survive(catalogue):
    """The refusal replaces the ambiguity verdict rather than hiding behind it.

    'Five printings, indistinguishable' implies one of them is right. When the
    named product could not be read, that implication is unearned."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(product_label=PCC),
        )
    assert err.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT
    assert len(err.value.alternatives) == 5


def test_an_applicant_service_label_is_refused_the_same_way(catalogue):
    """A mail-in premium names a distribution context Atlas has no product
    for. It is unresolved product evidence, not absent product evidence -
    even when the source also supplied an exact asset variant."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["solo"].id,
            evidence=_solo_evidence(product_label=WSJ, variant="base"),
        )
    assert err.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_a_resolved_product_that_uniquely_narrows_still_approves(catalogue):
    """Case B. OP-08 carries exactly one printing of this code."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["sp_p3"].id,
        evidence=_evidence(product_label="Booster Pack Two Legends", set_code="OP-08"),
    )
    assert decision.card_print.id == catalogue["prints"]["sp_p3"].id
    assert "product OP-08" in decision.evidence_used


def test_a_resolved_product_with_several_artwork_variants_stays_ambiguous(catalogue):
    """Case B, and existing ambiguity handling is untouched: knowing the
    product does not tell you which of its three artworks was sold."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(product_label="Booster Pack Paramount War", set_code="OP-02"),
        )
    assert err.value.code == REFUSAL_AMBIGUOUS
    assert err.value.alternatives == sorted(
        catalogue["prints"][k].id for k in ("base", "p1", "p2")
    )


def test_a_resolved_product_that_rules_the_print_out_is_incompatible(catalogue):
    """Case D, unchanged."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(
                product_label="Premium Booster ONE PIECE CARD THE BEST", set_code="PRB-01"
            ),
        )
    assert err.value.code == REFUSAL_EVIDENCE_CONTRADICTS


def test_a_contradiction_is_reported_ahead_of_an_unresolved_label(catalogue):
    """Ordering. A print the source's own artwork evidence rules out is a
    harder, more specific error than a label we could not map, so the operator
    hears about that one first."""
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["base"].id,
            evidence=_evidence(product_label=PCC, variant="p1"),
        )
    assert err.value.code == REFUSAL_EVIDENCE_CONTRADICTS


def test_an_exact_asset_variant_still_resolves_without_a_product_label(catalogue):
    """Control case: artwork evidence that genuinely discriminates, with no
    product label in play, is still enough on its own."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_evidence(variant="p2"),
    )
    assert decision.card_print.id == catalogue["prints"]["p2"].id


# --- reading the label off the stored candidate row --------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        # Verbatim run-1 titles.
        ("Usopp R [OP01-004] (Booster Pack ROMANCE DAWN)", "Booster Pack ROMANCE DAWN"),
        ('Shanks SEC-SP (Comic Parallel) [OP01-120](Booster Pack "ROMANCE DAWN")',
         'Booster Pack "ROMANCE DAWN"'),
        ("Charlotte Compote C [EB01-055] (Extra Booster Memorial Collection)",
         "Extra Booster Memorial Collection"),
        ("Jimbe C Parallel [ST01-005] (Premium Card Collection 25th Anniversary Edition)",
         PCC),
        # No trailing group: the source named no product.
        ("OP02-013 ポートガス・D・エース SR", None),
        ("", None),
        (None, None),
    ],
)
def test_the_product_label_is_read_off_the_stored_title(title, expected):
    """The gate must be able to tell 'no label' from 'label we could not
    resolve', and `detected_set_code` is NULL for both. The label is recovered
    from the title the row already stores - no migration, and it works on rows
    written before any of this existed."""
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/cards/x",
        title=title,
        detected_card_code="OP01-004",
    )
    assert SourceEvidence.from_snkrdunk_candidate(candidate).product_label == expected


def test_a_label_resolved_at_parse_time_is_treated_as_resolved(catalogue):
    """The EB-01 control case in the shape a candidate row actually carries:
    once discovery has re-parsed with the alias present, `detected_set_code` is
    populated and the same label is narrowing evidence, not a refusal."""
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/cards/compote",
        title="Charlotte Compote C [OP01-999] (Extra Booster Memorial Collection)",
        detected_card_code="OP01-999",
        detected_set_code="OP-02",  # the fixture's product for the solo print
    )
    evidence = SourceEvidence.from_snkrdunk_candidate(candidate)
    assert evidence.product_label == "Extra Booster Memorial Collection"
    assert not evidence.has_unresolved_product

    decision = resolve_exact_print(
        catalogue["db"], card_print_id=catalogue["prints"]["solo"].id, evidence=evidence
    )
    assert "product OP-02" in decision.evidence_used


def test_a_stale_row_whose_label_never_resolved_is_refused(catalogue):
    """The converse, and the reason the staging rows all moved: a row parsed
    before the alias existed carries a NULL detected_set_code, so its label is
    unresolved and it fails closed until discovery re-parses it."""
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/cards/compote-stale",
        title="Charlotte Compote C [OP01-999] (Extra Booster Memorial Collection)",
        detected_card_code="OP01-999",
        detected_set_code=None,
    )
    evidence = SourceEvidence.from_snkrdunk_candidate(candidate)
    assert evidence.has_unresolved_product
    with pytest.raises(ExactPrintApprovalError) as err:
        resolve_exact_print(
            catalogue["db"], card_print_id=catalogue["prints"]["solo"].id, evidence=evidence
        )
    assert err.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_print_options_explains_an_unresolved_product_rather_than_blaming_the_source(
    client, catalogue, candidate
):
    """The operator screen must not tell someone to find product evidence the
    listing already supplied."""
    candidate.title = f"Portgas.D.Ace SR [OP02-013] ({PCC})"
    catalogue["db"].commit()

    body = client.get(f"/admin/snkrdunk-candidates/{candidate.id}/print-options").json()
    assert body["resolvable_card_print_id"] is None
    assert PCC in body["ambiguity_reason"]
    assert "does not resolve" in body["ambiguity_reason"]
    assert all(o["approvable"] is False for o in body["options"])
    assert {o["refusal_code"] for o in body["options"]} == {
        REFUSAL_UNRESOLVED_SOURCE_PRODUCT
    }
