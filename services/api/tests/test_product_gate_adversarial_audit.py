"""PART 1 of the 2026-08-29 product-gate adversarial audit: the REAL guard
order, proved by exercising the real functions.

WHY ORDER IS PROVED BY COLLISION, NOT BY READING. A test that triggers one
refusal in isolation proves only that the refusal exists. What the audit has
to establish is the ORDER, so every test here puts TWO refusals in scope at
once and asserts which one the function actually raises. That pins the
sequence to observed behaviour, and any reordering of the gates breaks a test
rather than a comment.

The second half is containment: with ARTWORK_EVIDENCE_ENABLED forced ON and
the artwork verdict made maximally confident and maximally wrong, artwork must
still be incapable of introducing, resurrecting, or relocating a printing.
Every one of those tests drives `resolve_exact_print` itself.
"""

import pytest

from app.services.artwork_evidence import (
    STATUS_AMBIGUOUS,
    STATUS_EXACT,
    STATUS_NO_MATCH,
    STATUS_UNUSABLE,
    ArtworkVerdict,
)
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
    _narrow_by_artwork,
    resolve_exact_print,
    sibling_prints_for_card_code,
)
from tests.test_exact_print_approval import catalogue  # noqa: F401 - fixture


def _ev(**kw) -> SourceEvidence:
    base = {
        "source_name": "snkrdunk",
        "source_url": "https://snkrdunk.com/apparels/900001",
        "card_code": "OP02-013",
    }
    base.update(kw)
    return SourceEvidence(**base)


def _perfect(chosen: int, before: tuple[int, ...]) -> ArtworkVerdict:
    """The most persuasive verdict the module can emit: exact, at the best
    score the pipeline can produce, with a margin far above ARTWORK_MARGIN_MIN.
    Used everywhere below so no containment result can be attributed to weak
    artwork evidence."""
    return ArtworkVerdict(
        status=STATUS_EXACT,
        card_print_id=chosen,
        winning_class=(chosen,),
        best_score=0,
        runner_up_score=128,
        margin=128,
        card_print_ids_before=tuple(sorted(before)),
        card_print_ids_after=(chosen,),
    )


@pytest.fixture
def artwork_on(monkeypatch):
    """Every containment test runs with the flag FORCED ON. The audit's claim
    is that containment does not depend on the flag being off."""
    from app.settings import settings

    monkeypatch.setattr(settings, "ARTWORK_EVIDENCE_ENABLED", True)
    return True


# =============================================================================
# PART 1a - the observed guard order in resolve_exact_print
# =============================================================================


def test_01_missing_print_id_precedes_every_evidence_check(catalogue):
    """No card code, no product, no print id. The print id answers first, so
    the request-shape refusal is never masked by an evidence refusal."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=None,
            evidence=_ev(card_code=None, title="x (Unknown Box)", product_label="Unknown Box"),
        )
    assert exc.value.code == REFUSAL_PRINT_REQUIRED


def test_02_print_existence_precedes_card_code_verification(catalogue):
    """A dangling print id with a WRONG card code still answers print_not_found:
    the row is loaded before any source fact is read."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"], card_print_id=999_999, evidence=_ev(card_code="OP01-001")
        )
    assert exc.value.code == REFUSAL_PRINT_NOT_FOUND


def test_03_print_activity_precedes_card_code_verification(catalogue):
    db = catalogue["db"]
    row = catalogue["prints"]["p1"]
    row.is_active = False
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(db, card_print_id=row.id, evidence=_ev(card_code="OP01-001"))
    assert exc.value.code == REFUSAL_PRINT_INACTIVE


def test_04_print_verification_precedes_card_code_verification(catalogue):
    db = catalogue["db"]
    row = catalogue["prints"]["p1"]
    row.verification_status = "needs_review"
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(db, card_print_id=row.id, evidence=_ev(card_code="OP01-001"))
    assert exc.value.code == REFUSAL_PRINT_UNVERIFIED


def test_05_missing_card_code_precedes_unresolved_product(catalogue):
    """Both are true: no card code AND a product label Atlas cannot resolve.
    Identity has to start at the card code, so that refusal wins."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,
            evidence=_ev(card_code=None, product_label="Premium Card Collection"),
        )
    assert exc.value.code == REFUSAL_NO_SOURCE_CARD_CODE


def test_06_card_code_mismatch_precedes_product_narrowing(catalogue):
    """A source card code that does not name this print's card ends it before
    the product evidence is consulted at all."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,
            evidence=_ev(card_code="OP01-001", set_code="OP-02", variant="p2"),
        )
    assert exc.value.code == REFUSAL_CARD_CODE_MISMATCH


def test_07_product_contradiction_precedes_unresolved_product(catalogue):
    """The listing names a product that DOES resolve and rules the print out,
    while ALSO carrying an unresolvable label. The harder, more specific fact
    answers first - see the ordering comment in exact_print_approval."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,  # OP-02
            evidence=_ev(set_code="PRB-01", product_label="Premium Card Collection"),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS


def test_08_unresolved_product_precedes_ambiguity(catalogue):
    """Three OP-02 prints survive the card code, so ambiguity is live - but the
    label the source published could not be resolved, and that answers first."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,
            evidence=_ev(product_label="Weekly Shonen Jump mail-in premium"),
        )
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT
    assert len(exc.value.alternatives) > 1


def test_09_unresolved_product_refuses_even_a_lone_survivor(catalogue):
    """Case C of the module contract, and the 4F-3C finding: a single survivor
    under an unreadable label is not proof, it is the only wrong answer left."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["solo"].id,
            evidence=_ev(card_code="OP01-999", product_label="Premium Card Collection"),
        )
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT
    assert exc.value.alternatives == [catalogue["prints"]["solo"].id]


def test_10_ambiguity_is_the_last_gate(catalogue):
    """Nothing refusable is left; three prints stand and none is proved."""
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,
            evidence=_ev(set_code="OP-02"),
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert len(exc.value.alternatives) == 3


def test_11_allowed_sibling_construction_admits_only_active_verified_prints(catalogue):
    """The set artwork is ever allowed to see is built here, and it is built
    from the catalogue's own state - not from anything the source said."""
    db = catalogue["db"]
    prints = catalogue["prints"]
    before = {p.id for p, _ in sibling_prints_for_card_code(db, "OP02-013")}
    assert before == {prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3")}

    prints["r1"].is_active = False
    prints["sp_p3"].verification_status = "unverified"
    db.commit()
    after = {p.id for p, _ in sibling_prints_for_card_code(db, "OP02-013")}
    assert after == {prints[k].id for k in ("base", "p1", "p2")}


# =============================================================================
# PART 1b - artwork containment, with the flag FORCED ON
# =============================================================================


def test_12_artwork_cannot_introduce_a_print_product_evidence_excluded(catalogue, artwork_on):
    """The headline containment. Artwork is perfectly confident that the photo
    is the PRB-01 reprint; the source's product evidence says OP-02. The
    reprint must not appear in the answer OR in the alternatives."""
    db, prints = catalogue["db"], catalogue["prints"]
    reprint = prints["r1"]
    verdict = _perfect(reprint.id, (prints["base"].id, prints["p1"].id, prints["p2"].id))

    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(set_code="OP-02"),
            artwork=verdict,
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert reprint.id not in exc.value.alternatives


def test_13_artwork_cannot_override_source_product_unresolved(catalogue, artwork_on):
    """The refusal fires before `_narrow_by_artwork` is reached at all, so no
    artwork verdict of any strength can convert it into an approval."""
    db, prints = catalogue["db"], catalogue["prints"]
    verdict = _perfect(
        prints["p2"].id,
        tuple(sorted(prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3"))),
    )
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(product_label="Premium Card Collection 25th Anniversary Edition"),
            artwork=verdict,
        )
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_14_artwork_cannot_override_a_lone_survivor_unresolved_product(catalogue, artwork_on):
    """The shape artwork would most plausibly 'rescue': one survivor, perfect
    artwork agreement, and an unreadable product label. Still refused."""
    db, prints = catalogue["db"], catalogue["prints"]
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["solo"].id,
            evidence=_ev(card_code="OP01-999", product_label="Premium Card Collection"),
            artwork=_perfect(prints["solo"].id, (prints["solo"].id,)),
        )
    assert exc.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_15_artwork_cannot_override_evidence_contradicts_selection(catalogue, artwork_on):
    """Product evidence rules the operator's print out; artwork insists it is
    the photo. The contradiction refusal stands."""
    db, prints = catalogue["db"], catalogue["prints"]
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(set_code="PRB-01"),
            artwork=_perfect(prints["p2"].id, (prints["p2"].id,)),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS


def test_16_artwork_cannot_override_an_empty_survivor_set(catalogue, artwork_on):
    """Product + variant leave NOTHING standing. Artwork must not repopulate
    the set from the sibling field."""
    db, prints = catalogue["db"], catalogue["prints"]
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(set_code="OP-02", variant="p9"),
            artwork=_perfect(prints["p2"].id, (prints["p2"].id,)),
        )
    assert exc.value.code == REFUSAL_EVIDENCE_CONTRADICTS
    assert exc.value.alternatives  # the considered field, not a survivor set


def test_17_artwork_cannot_move_a_mapping_between_release_products(catalogue, artwork_on):
    """The failure the contradiction-guard prototype exists for, driven end to
    end: artwork names a print in a DIFFERENT release product than the one the
    operator named, and the approval must not relocate."""
    db, prints = catalogue["db"], catalogue["prints"]
    sp = prints["sp_p3"]  # OP-08
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,  # OP-02
            evidence=_ev(set_code="OP-02"),
            artwork=_perfect(sp.id, (prints["base"].id, prints["p1"].id, prints["p2"].id)),
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert sp.id not in exc.value.alternatives


def test_18_artwork_cannot_resurrect_a_deactivated_sibling(catalogue, artwork_on):
    """Removed upstream by the catalogue itself, not by the source. Artwork
    names it with total confidence and it stays gone."""
    db, prints = catalogue["db"], catalogue["prints"]
    dead = prints["p1"]
    dead.is_active = False
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(set_code="OP-02"),
            artwork=_perfect(dead.id, (prints["base"].id, prints["p2"].id)),
        )
    assert exc.value.code == REFUSAL_AMBIGUOUS
    assert dead.id not in exc.value.alternatives


def test_19_artwork_cannot_resurrect_an_unverified_reprint_sibling(catalogue, artwork_on):
    db, prints = catalogue["db"], catalogue["prints"]
    dead = prints["r1"]
    dead.verification_status = "unverified"
    db.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        resolve_exact_print(
            db,
            card_print_id=prints["p2"].id,
            evidence=_ev(set_code="OP-02"),
            artwork=_perfect(dead.id, (prints["base"].id, prints["p1"].id, prints["p2"].id)),
        )
    assert dead.id not in exc.value.alternatives


def test_20_narrowing_is_a_subset_operation_for_every_verdict_shape():
    """The invariant behind every test above, checked directly against the real
    function over the whole cross-product of verdict shapes: the returned set
    is always a SUBSET of the set handed in. Never once a superset."""
    from app.settings import settings

    survivors = [10, 11, 12]
    shapes = []
    for status in (STATUS_EXACT, STATUS_AMBIGUOUS, STATUS_NO_MATCH, STATUS_UNUSABLE):
        for chosen in (10, 11, 12, 99, None):
            for before in ((10, 11, 12), (10, 11), (10, 11, 12, 99), ()):
                shapes.append(
                    ArtworkVerdict(
                        status=status,
                        card_print_id=chosen,
                        winning_class=() if chosen is None else (chosen,),
                        best_score=0,
                        runner_up_score=128,
                        margin=128,
                        card_print_ids_before=before,
                        card_print_ids_after=() if chosen is None else (chosen,),
                    )
                )
    shapes.append(None)

    for enabled in (False, True):
        settings.ARTWORK_EVIDENCE_ENABLED = enabled
        try:
            for operator in survivors:
                for verdict in shapes:
                    out, _ = _narrow_by_artwork(list(survivors), operator, verdict)
                    assert set(out) <= set(survivors), (enabled, operator, verdict)
                    assert out, "narrowing must never empty the set"
        finally:
            settings.ARTWORK_EVIDENCE_ENABLED = False


def test_21_no_production_call_site_passes_artwork_into_the_resolver():
    """Artwork is DOUBLY dark in the API today: the flag is off, and no caller
    supplies a verdict for the flag to act on. That second fact is load-bearing
    for the audit's conclusion and nothing else asserts it."""
    import ast
    import pathlib

    api_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in api_dir.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "resolve_exact_print":
                continue
            if any(kw.arg == "artwork" for kw in node.keywords):
                offenders.append(f"{path.relative_to(api_dir)}:{node.lineno}")
    assert offenders == [], (
        "a production call site now feeds artwork into the exact-print resolver; "
        "the audit's containment argument must be re-run: " + ", ".join(offenders)
    )


# =============================================================================
# PART 1c - the containment THEOREM the audit turns on
# =============================================================================


def test_22_artwork_is_consulted_only_when_product_evidence_removed_nothing(catalogue):
    """The mechanism, isolated.

    `_narrow_by_artwork` consults a verdict only when the verdict's own
    `card_print_ids_before` equals the survivor set. The ONLY producer of
    verdicts in this codebase is `artwork_preview.preview_candidate_artwork`,
    which ranks over `sibling_prints_for_card_code` - the FULL card-code field.

    So artwork is consulted if and only if product+variant evidence removed
    nothing, and it is ignored the moment product evidence does any work at
    all. Both halves are exercised here."""
    db, prints = catalogue["db"], catalogue["prints"]
    full_field = tuple(sorted(prints[k].id for k in ("base", "p1", "p2", "r1", "sp_p3")))

    from app.settings import settings

    settings.ARTWORK_EVIDENCE_ENABLED = True
    try:
        # (a) product evidence narrowed 5 -> 3: the preview-shaped verdict is
        #     computed over a different set and is not consulted.
        ids, note = _narrow_by_artwork(
            sorted(prints[k].id for k in ("base", "p1", "p2")),
            prints["p2"].id,
            _perfect(prints["p2"].id, full_field),
        )
        assert note is None
        assert len(ids) == 3

        # (b) product evidence removed nothing: the sets agree and artwork is
        #     the sole discriminator.
        ids, note = _narrow_by_artwork(list(full_field), prints["p2"].id,
                                       _perfect(prints["p2"].id, full_field))
        assert note is not None
        assert ids == [prints["p2"].id]
    finally:
        settings.ARTWORK_EVIDENCE_ENABLED = False


def test_23_a_resolvable_product_label_that_removes_nothing_implies_a_single_product_field(
    catalogue,
):
    """The corollary, and why the 'artwork crosses a release product' risk is
    reachable only through a listing that names NO product at all.

    If a resolved product code removes no print from the field, then every
    print in the field carries that product code - so the field cannot span
    release products, and the artwork comparison artwork is allowed to make is
    necessarily WITHIN one product. Checked here against the real sibling
    query rather than argued."""
    db, prints = catalogue["db"], catalogue["prints"]
    siblings = sibling_prints_for_card_code(db, "OP02-013")
    field_ids = sorted(p.id for p, _ in siblings)

    def survivors(set_code):
        norm = set_code.replace("-", "").upper() if set_code else None
        kept = [
            p for p, _ in siblings
            if norm is None
            or (p.release_product_code or "").replace("-", "").upper() == norm
        ]
        return sorted(p.id for p in kept)

    # A label that resolves and DOES narrow -> artwork is never consulted.
    assert survivors("OP-02") != field_ids

    # For every product present in the field, "removes nothing" is equivalent
    # to "the field is that one product".
    products = {p.release_product_code for p, _ in siblings}
    for code in products:
        removed_nothing = survivors(code) == field_ids
        single_product = len(products) == 1
        assert removed_nothing == single_product, code

    # And with no product evidence at all the survivor set IS the field, which
    # is the one route by which artwork can compare across release products.
    assert survivors(None) == field_ids
    assert len(products) > 1, "this fixture's field really does span products"
