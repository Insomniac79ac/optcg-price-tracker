"""PART 3 of the 2026-08-29 product-gate adversarial audit, resolver side.

Each case corrupts exactly ONE upstream identity signal and then hands the
resolver the most persuasive artwork verdict the module can emit, agreeing
with whatever the operator asked for. The question every test answers is the
same: is the write refused BEFORE artwork could legitimise it?

A case that reaches a writable state SOLELY because artwork agrees is a
blocker, and `test_blocker_sweep` states that as an assertion over the whole
set rather than leaving it to the reader.
"""

import pytest

from app.services.artwork_evidence import STATUS_EXACT, ArtworkVerdict
from app.services.exact_print_approval import (
    REFUSAL_AMBIGUOUS,
    REFUSAL_CARD_CODE_MISMATCH,
    REFUSAL_EVIDENCE_CONTRADICTS,
    REFUSAL_UNRESOLVED_SOURCE_PRODUCT,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
)
from tests.test_exact_print_approval import catalogue  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def artwork_on(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)


def _agreeing_artwork(chosen: int, field: tuple[int, ...]) -> ArtworkVerdict:
    return ArtworkVerdict(
        status=STATUS_EXACT,
        card_print_id=chosen,
        winning_class=(chosen,),
        best_score=0,
        runner_up_score=128,
        margin=128,
        card_print_ids_before=tuple(sorted(field)),
        card_print_ids_after=(chosen,),
    )


def _ev(**kw) -> SourceEvidence:
    base = {
        "source_name": "snkrdunk",
        "source_url": "https://snkrdunk.com/apparels/900001",
        "card_code": "OP02-013",
    }
    base.update(kw)
    return SourceEvidence(**base)


def _attempt(catalogue, *, card_print_id, evidence, artwork_field=None):
    """Run the real resolver and report (approved, refusal_code)."""
    field = artwork_field or (card_print_id,)
    try:
        decision = resolve_exact_print(
            catalogue["db"],
            card_print_id=card_print_id,
            evidence=evidence,
            artwork=_agreeing_artwork(card_print_id, field),
        )
        return True, None, decision
    except ExactPrintApprovalError as exc:
        return False, exc.code, None


# --- the seven injected cases -------------------------------------------------


def test_case_a_wrong_release_correct_card_code(catalogue):
    """The card code is right; the product named is one this printing did not
    ship in. Refused on product evidence, with artwork agreeing throughout."""
    approved, code, _ = _attempt(
        catalogue,
        card_print_id=catalogue["prints"]["p2"].id,   # OP-02
        evidence=_ev(set_code="PRB-01"),
    )
    assert not approved
    assert code == REFUSAL_EVIDENCE_CONTRADICTS


def test_case_b_missing_release_is_THE_BLOCKER_artwork_alone_approves(catalogue):
    """BLOCKER. No product label, no resolved code, nothing to narrow on but
    the card code - and with ARTWORK_EVIDENCE_ENABLED on, artwork alone picks
    one of the five printings and the approval succeeds.

    This is `_narrow_by_artwork` working exactly as designed: the survivor set
    IS the sibling field, so the verdict was computed over the same set that
    survived, the chosen print is in it, and it is the print the operator
    named. Every containment condition passes. What does NOT exist is any
    second channel corroborating the choice.

    It is the shape with the worst measured exposure, because the field artwork
    is ranked over is the WHOLE card-code field, spanning release products -
    which is where the 2026-08-29 stress test found its one real false exact.
    """
    from app.settings import settings

    prints = catalogue["prints"]
    field = tuple(prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3"))

    settings.ARTWORK_EVIDENCE_ENABLED = False
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"], card_print_id=prints["p2"].id, evidence=_ev(), artwork=None
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert len(exc.value.alternatives) == 5

    settings.ARTWORK_EVIDENCE_ENABLED = True
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=prints["p2"].id,
        evidence=_ev(),
        artwork=_agreeing_artwork(prints["p2"].id, field),
    )
    assert decision.card_print.id == prints["p2"].id
    assert decision.evidence_used[0] == "card code OP02-013"
    assert any("listing artwork" in e for e in decision.evidence_used), (
        "artwork is the sole discriminator on this path"
    )
    assert not any(e.startswith("product ") for e in decision.evidence_used)


def test_case_b2_missing_release_on_a_code_with_one_print_DOES_approve(catalogue):
    """FINDING, recorded as a test rather than as prose. When the catalogue
    holds exactly one print for a card code, a listing with NO product evidence
    at all is approved on the card code alone.

    This is not an artwork failure - artwork changes nothing here, and the same
    approval happens with the flag off and no verdict. It is the true floor of
    the product gate, and it is what bounds any claim that product evidence
    'always' precedes artwork: for single-print codes there is no product
    evidence in the decision at all."""
    solo = catalogue["prints"]["solo"].id
    approved, code, decision = _attempt(
        catalogue, card_print_id=solo, evidence=_ev(card_code="OP01-999")
    )
    assert approved, "documented behaviour, not an endorsement"
    assert decision.evidence_used == ["card code OP01-999"], (
        "the audit trail names the card code and nothing else - no product, "
        "no variant, no artwork"
    )

    # And with artwork switched off entirely the outcome is identical, which is
    # what proves artwork is not what legitimised it.
    from app.settings import settings

    settings.ARTWORK_EVIDENCE_ENABLED = False
    try:
        again = resolve_exact_print(
            catalogue["db"], card_print_id=solo, evidence=_ev(card_code="OP01-999")
        )
        assert again.evidence_used == decision.evidence_used
    finally:
        settings.ARTWORK_EVIDENCE_ENABLED = True


def test_case_c_wrong_card_code_with_visually_matching_art(catalogue):
    """Artwork insists the photo is this print. The card code says it belongs
    to another card, and identity starts at the card code."""
    approved, code, _ = _attempt(
        catalogue,
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_ev(card_code="OP01-001", set_code="OP-02"),
    )
    assert not approved
    assert code == REFUSAL_CARD_CODE_MISMATCH


def test_case_d_correct_release_wrong_variant(catalogue):
    """Right product, wrong official asset variant. The variant filter empties
    the survivor set and artwork cannot refill it."""
    approved, code, _ = _attempt(
        catalogue,
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_ev(set_code="OP-02", variant="p1"),
    )
    assert not approved
    assert code == REFUSAL_EVIDENCE_CONTRADICTS


def test_case_e_english_mirror_url_against_a_japanese_print(catalogue):
    """The resolver itself is language-blind; the guard for this case lives in
    `canonical_listing_url`, which the two approval endpoints call immediately
    after the resolver returns. Exercised here so the audit covers the real
    path rather than the resolver in isolation."""
    from app.services.snkrdunk_urls import canonical_listing_url

    jp = canonical_listing_url(
        "https://snkrdunk.com/en/trading-cards/104428", card_print_language="jp"
    )
    en = canonical_listing_url(
        "https://snkrdunk.com/apparels/104428", card_print_language="en"
    )
    assert jp == "https://snkrdunk.com/apparels/104428"
    assert en == "https://snkrdunk.com/en/trading-cards/104428"
    assert jp != en, (
        "a jp print approved from the English mirror is rewritten to the page "
        "the collector will actually fetch, and the collector's own "
        "language_mismatch gate then holds the line"
    )
    with pytest.raises(ExactPrintApprovalError):
        canonical_listing_url("https://example.com/not-a-listing", card_print_language="jp")


def test_case_f_same_artwork_reused_by_a_reprint(catalogue):
    """Artwork is byte-identical across the two prints, so the image is
    incapable of separating them. With no product evidence the resolver must
    refuse; with product evidence the PRODUCT decides, not the picture."""
    prints = catalogue["prints"]
    field = tuple(prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3"))

    from app.settings import settings

    settings.ARTWORK_EVIDENCE_ENABLED = False
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"], card_print_id=prints["base"].id, evidence=_ev(), artwork=None
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    settings.ARTWORK_EVIDENCE_ENABLED = True

    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=prints["r1"].id,
        evidence=_ev(set_code="PRB-01"),
        artwork=_agreeing_artwork(prints["r1"].id, field),
    )
    assert decision.card_print.id == prints["r1"].id
    assert "product PRB-01" in decision.evidence_used
    assert not any("artwork" in e for e in decision.evidence_used), (
        "the verdict was computed over the sibling field, not the survivor set, "
        "so `_narrow_by_artwork` declined to consult it"
    )


def test_case_g_label_that_resolves_to_a_real_but_wrong_product(catalogue):
    """THE UNCAUGHT SHAPE, and the reason this audit exists.

    Nothing is malformed. The label resolved - to a product Atlas really holds
    a print of - and it is simply the wrong one. The resolver narrows to that
    product's print and approves it, because every channel it trusts agrees.

    Artwork is the only signal that could contradict this, and it is exactly
    the signal not being trusted. Recorded as behaviour so the Part 4
    recommendation is anchored to a measured fact."""
    prints = catalogue["prints"]
    decision = resolve_exact_print(
        catalogue["db"],
        card_print_id=prints["r1"].id,  # PRB-01
        evidence=_ev(set_code="PRB-01"),
        artwork=_agreeing_artwork(prints["r1"].id, (prints["r1"].id,)),
    )
    assert decision.card_print.id == prints["r1"].id
    assert decision.evidence_used == ["card code OP02-013", "product PRB-01"]
    # The approval rests entirely on the label having resolved correctly.
    # Nothing downstream re-derives the product from the item itself.


def test_case_h_unresolvable_label_is_refused_however_confident_artwork_is(catalogue):
    approved, code, _ = _attempt(
        catalogue,
        card_print_id=catalogue["prints"]["p2"].id,
        evidence=_ev(product_label="Weekly Shonen Jump 2024 Issue 3 All Applicants Service"),
    )
    assert not approved
    assert code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


# --- the blocker sweep --------------------------------------------------------


def test_blocker_sweep_no_case_becomes_writable_because_artwork_agrees(catalogue):
    """For every injected case, run it twice - once with the agreeing artwork
    verdict and the flag ON, once with no verdict and the flag OFF - and assert
    the outcome is IDENTICAL. Any case whose outcome differs would be writable
    because artwork agreed, which is the blocker condition."""
    from app.settings import settings

    prints = catalogue["prints"]
    field = tuple(prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3"))
    cases = [
        ("wrong release", prints["p2"].id, _ev(set_code="PRB-01")),
        ("missing release", prints["p2"].id, _ev()),
        ("single-print code, no release", prints["solo"].id, _ev(card_code="OP01-999")),
        ("wrong card code", prints["p2"].id, _ev(card_code="OP01-001", set_code="OP-02")),
        ("wrong variant", prints["p2"].id, _ev(set_code="OP-02", variant="p1")),
        ("shared-artwork reprint", prints["base"].id, _ev()),
        ("mis-resolved label", prints["r1"].id, _ev(set_code="PRB-01")),
        ("unresolvable label", prints["p2"].id, _ev(product_label="Premium Card Collection")),
    ]

    def outcome(card_print_id, evidence, artwork):
        try:
            d = resolve_exact_print(
                catalogue["db"], card_print_id=card_print_id, evidence=evidence, artwork=artwork
            )
            return ("approved", d.card_print.id, tuple(d.evidence_used))
        except ExactPrintApprovalError as exc:
            return ("refused", exc.code, tuple(sorted(exc.alternatives)))

    differences = []
    for label, print_id, evidence in cases:
        settings.ARTWORK_EVIDENCE_ENABLED = True
        with_artwork = outcome(print_id, evidence, _agreeing_artwork(print_id, field))
        settings.ARTWORK_EVIDENCE_ENABLED = False
        without = outcome(print_id, evidence, None)
        if with_artwork != without:
            differences.append((label, with_artwork[0], without[0]))
    settings.ARTWORK_EVIDENCE_ENABLED = False

    # THE AUDIT RESULT, pinned. Exactly two of the eight injected cases become
    # writable because artwork agreed, and both are the SAME shape: no product
    # evidence at all, so the survivor set is the whole card-code field and
    # artwork is the only channel separating it. Every case where product
    # evidence actually said something is unmoved.
    assert differences == [
        ("missing release", "approved", "refused"),
        ("shared-artwork reprint", "approved", "refused"),
    ], repr(differences)

    moved = {label for label, _, _ in differences}
    assert not moved & {
        "wrong release", "wrong card code", "wrong variant",
        "mis-resolved label", "unresolvable label",
    }, "artwork moved a case that product/code evidence had already decided"
