"""The exact-print gate narrowing on an UNCODED product.

The case: a card code Atlas holds several printings of, one of which shipped
in a promotional product Bandai publishes no code for. Before this tranche the
listing's product label resolved to nothing and the gate refused it as
`source_product_unresolved`; the fix is that the label resolves to the
product's surrogate identity through a `source_rendering` alias, and narrowing
happens on `card_prints.release_product_id` - never on an invented code.
"""

import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    ReleaseProductAlias,
    Source,
)
from app.seed import SOURCES
from app.services.exact_print_approval import (
    REFUSAL_AMBIGUOUS,
    REFUSAL_EVIDENCE_CONTRADICTS,
    REFUSAL_UNRESOLVED_SOURCE_PRODUCT,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
    resolve_uncoded_product_id,
)

LABEL = "Premium Card Collection -Best Selection vol.1-"
JP_NAME = "プレミアムカードコレクション - ベストセレクションvol.1 -"


def _product(db, code, name=None, series="550801"):
    row = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=code,
        display_name=name or code,
        first_seen_name=name or code,
        source_series_id=series,
        source_url=f"https://example.test/{series}",
        verification_status="verified",
    )
    db.add(row); db.flush(); return row


def _print(db, canonical, product, variant):
    row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        # The whole point: an uncoded product's prints carry NO code.
        release_product_code=product.official_code,
        release_product_id=product.id,
        artwork_key=f"sha256:{canonical.card_code}-{variant}",
        official_asset_variant=variant,
        verification_status="verified",
        is_active=True,
    )
    db.add(row); db.flush(); return row


@pytest.fixture()
def catalogue(db_session):
    db = db_session
    for data in SOURCES:
        db.add(Source(**data))
    db.add(Card(card_code="OP01-029", name_en="Nami", name_jp="ナミ",
                set_code="OP-01", rarity="UC", language="jp"))
    op01 = _product(db, "OP-01")
    prb01 = _product(db, "PRB-01")
    pcc = _product(db, None, JP_NAME)          # uncoded: official_code IS NULL
    nami = CanonicalCard(card_code="OP01-029", name_en="Nami", name_jp="ナミ",
                         card_type="Character", rarity="UC")
    db.add(nami); db.flush()
    prints = {
        "op01_base": _print(db, nami, op01, "base"),
        "prb_p3": _print(db, nami, prb01, "p3"),
        "prb_r1": _print(db, nami, prb01, "r1"),
        "pcc_p2": _print(db, nami, pcc, "p2"),
    }
    db.add(ReleaseProductAlias(product_id=pcc.id, alias_name=LABEL,
                               alias_kind="source_rendering", source_url=None))
    db.commit()
    return {"db": db, "prints": prints, "pcc": pcc, "op01": op01, "nami": nami}


def _ev(**kw):
    base = dict(source_name="snkrdunk", card_code="OP01-029",
                title=f"Nami UC [OP01-029] ({LABEL})", product_label=LABEL)
    base.update(kw)
    return SourceEvidence(**base)


# --- 4. exact resolver narrowing using an uncoded product -------------------
def test_an_uncoded_product_label_narrows_to_its_single_print(catalogue):
    """Four printings share OP01-029. The label identifies one of them."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["pcc_p2"].id,
        evidence=_ev(),
    )
    assert decision.card_print.id == catalogue["prints"]["pcc_p2"].id
    assert any("uncoded product" in line for line in decision.evidence_used)


def test_the_narrowed_print_carries_no_release_product_code(catalogue):
    """No invented code anywhere on the path that made this exact."""
    decision = resolve_exact_print(
        catalogue["db"], card_print_id=catalogue["prints"]["pcc_p2"].id, evidence=_ev()
    )
    assert decision.card_print.release_product_code is None
    assert decision.card_print.release_product_id == catalogue["pcc"].id


# --- 5. multi-print products stay ambiguous where appropriate ---------------
def test_an_uncoded_product_holding_two_prints_of_one_code_stays_ambiguous(catalogue):
    """Narrowing to a product is not narrowing to a printing. A second print
    of the same code inside the same product must still refuse."""
    db = catalogue["db"]
    second = _print(db, catalogue["nami"], catalogue["pcc"], "p5")
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(db, card_print_id=second.id, evidence=_ev())
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert sorted(exc.value.alternatives) == sorted(
        [catalogue["prints"]["pcc_p2"].id, second.id]
    )


# --- 6. a product with no matching print fails closed -----------------------
def test_a_label_whose_product_holds_no_print_of_this_code_fails_closed(catalogue):
    """The failure the audit predicted if products were imported WITHOUT their
    prints: the survivor set empties and the gate refuses. It must never
    approve, and it must never silently fall back to ignoring the product."""
    db = catalogue["db"]
    empty = _product(db, None, "プレミアムカードコレクション-ウタ-")
    db.add(ReleaseProductAlias(product_id=empty.id, alias_name="Premium Card Collection -Uta-",
                               alias_kind="source_rendering", source_url=None))
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=catalogue["prints"]["pcc_p2"].id,
            evidence=_ev(product_label="Premium Card Collection -Uta-"),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS


# --- 7. wrong product membership fails closed -------------------------------
def test_the_label_never_approves_a_print_from_another_product(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["op01_base"].id,
            evidence=_ev(),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS


# --- an unlisted label is still unresolved ----------------------------------
def test_a_label_with_no_source_rendering_alias_is_still_unresolved(catalogue):
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["pcc_p2"].id,
            evidence=_ev(product_label="Championship Battle Best 16"),
        )
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


# --- the resolver itself: exact equality, fails closed ----------------------
@pytest.mark.parametrize(
    "label",
    [
        "premium card collection -best selection vol.1-",   # case
        "Premium Card Collection -Best Selection vol.1",    # truncated
        "Premium Card Collection -Best Selection vol.1- ",  # trailing space
        "PremiumCardCollection-BestSelectionvol.1-",        # whitespace removed
        "Best Selection vol.1",                             # substring
        JP_NAME,                                            # the Bandai name
    ],
)
def test_the_uncoded_resolver_is_exact_equality_only(catalogue, label):
    assert resolve_uncoded_product_id(catalogue["db"], "snkrdunk", label) is None


def test_a_bandai_official_alias_can_never_answer_the_source_question(catalogue):
    """alias_kind is load-bearing: a Bandai name is not a storefront's name."""
    db = catalogue["db"]
    db.add(ReleaseProductAlias(product_id=catalogue["pcc"].id, alias_name="OFFICIAL ONLY",
                               alias_kind="bandai_official",
                               source_url="https://www.onepiece-cardgame.com/x"))
    db.commit()
    assert resolve_uncoded_product_id(db, "snkrdunk", "OFFICIAL ONLY") is None


def test_a_label_behind_two_products_refuses_rather_than_picking_one(catalogue):
    db = catalogue["db"]
    other = _product(db, None, "別の限定商品")
    db.add(ReleaseProductAlias(product_id=other.id, alias_name=LABEL,
                               alias_kind="source_rendering", source_url=None))
    db.commit()
    assert resolve_uncoded_product_id(db, "snkrdunk", LABEL) is None


# --- 3. coded products are unchanged ----------------------------------------
def test_a_coded_product_still_narrows_on_its_code_and_ignores_labels(catalogue):
    """The coded channel is consulted first and a label can never override it."""
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=catalogue["prints"]["op01_base"].id,
        evidence=_ev(set_code="OP-01", product_label=LABEL),
    )
    assert decision.card_print.id == catalogue["prints"]["op01_base"].id
    assert "product OP-01" in decision.evidence_used
    assert not any("uncoded" in line for line in decision.evidence_used)


def test_a_source_rendering_on_a_CODED_product_is_never_answered_here(catalogue):
    """Staging carries exactly this row: 'ロマンスドーン' -> OP-01, a coded product.

    A coded product's label belongs to the worker's contents-based alias table,
    where its evidence was reviewed. Answering it here as well would create a
    second route to the same product, and two routes can drift into disagreeing.
    """
    db = catalogue["db"]
    db.add(ReleaseProductAlias(product_id=catalogue["op01"].id, alias_name="ロマンスドーン",
                               alias_kind="source_rendering", source_url=None))
    db.commit()
    assert resolve_uncoded_product_id(db, "snkrdunk", "ロマンスドーン") is None


def test_a_coded_label_that_reaches_the_gate_is_still_refused_as_unresolved(catalogue):
    """The consequence, at the gate: nothing about the coded path changed."""
    db = catalogue["db"]
    db.add(ReleaseProductAlias(product_id=catalogue["op01"].id, alias_name="ロマンスドーン",
                               alias_kind="source_rendering", source_url=None))
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(db, card_print_id=catalogue["prints"]["op01_base"].id,
                            evidence=_ev(product_label="ロマンスドーン"))
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_the_rendering_lookup_is_source_agnostic_today(catalogue):
    """A documented limit, pinned so it cannot change unnoticed.

    `release_product_aliases` has no source column, so the same rendering
    answers whichever source asks. Harmless while SNKRDUNK is the only source
    with renderings; this test is what will fail if that stops being true.
    """
    db = catalogue["db"]
    assert resolve_uncoded_product_id(db, "yuyutei", LABEL) == catalogue["pcc"].id
    assert resolve_uncoded_product_id(db, "snkrdunk", LABEL) == catalogue["pcc"].id
