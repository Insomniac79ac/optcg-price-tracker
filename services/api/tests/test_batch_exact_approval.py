"""The batch exact-approval job: what it refuses, and that it writes exactly
what a human approval writes.

Two claims are being defended here and they are different claims.

The first is that the batch cannot approve anything the single-candidate
endpoint would not. Every refusal test below exists because there is a way a
batch could quietly say yes where a person would have been shown a reason to
say no - a candidate someone already decided on, a listing another game
published, a mapping a person rejected, a print the evidence does not name.

The second is `manual_verified`. The collector's eligibility filter reads that
column, so a second writer that sets it under weaker conditions silently
widens what gets priced. The test at the bottom answers that by writing the
same candidate both ways - through the endpoint and through the job - and
comparing every column of the resulting mapping.
"""

import pytest
from sqlalchemy import select

from app.approve_exact_snkrdunk_candidates import (
    CONFIRM_PHRASE,
    REFUSAL_MAPPING_CONFLICT,
    REFUSAL_MAPPING_NO_PRINT,
    REFUSAL_MAPPING_REJECTED,
    REFUSAL_NOT_EXACT,
    REFUSAL_NOT_ONE_PIECE,
    REFUSAL_NOT_UNMATCHED,
    BatchApprovalError,
    apply_batch,
    plan_batch,
)
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.seed import SOURCES


def _product(db, code):
    row = ReleaseProduct(
        source_catalogue="jp",
        official_code=code,
        display_name=code,
        first_seen_name=code,
        source_series_id=(code or "X").replace("-", ""),
        source_url=f"https://example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _canonical(db, card_code, **kw):
    row = CanonicalCard(
        card_code=card_code,
        name_en=kw.pop("name_en", "Portgas.D.Ace"),
        name_jp="ポートガス・D・エース",
        card_type="Character",
        rarity=kw.pop("rarity", "SR"),
    )
    db.add(row)
    db.flush()
    return row


def _print(db, canonical, product, variant, **kw):
    row = CardPrint(
        canonical_card_id=canonical.id,
        language=kw.pop("language", "jp"),
        release_product_code=product.official_code,
        release_product_id=product.id,
        artwork_key=f"sha256:{canonical.id}-{variant}-{product.id}",
        official_asset_variant=variant,
        verification_status=kw.pop("verification_status", "verified"),
        is_active=kw.pop("is_active", True),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


def _candidate(db, listing_id, title, **kw):
    row = SnkrdunkCandidate(
        source_url=f"https://snkrdunk.com/en/trading-cards/{listing_id}",
        title=title,
        normalized_title=title.lower(),
        price_jpy=1200,
        image_url=kw.pop(
            "image_url", f"https://static.snkrdunk.com/OPC-EN-TCG-{listing_id}-of.webp"
        ),
        match_status=kw.pop("match_status", "unmatched"),
        **kw,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def world(db_session):
    """A catalogue with one unambiguous code, one five-print code, and the
    candidates that exercise each path."""
    db = db_session
    for data in SOURCES:
        db.add(Source(**data))

    op01 = _product(db, "OP-01")
    op02 = _product(db, "OP-02")
    op08 = _product(db, "OP-08")

    # A code with exactly one printing: the source's product narrows nothing
    # because nothing needs narrowing.
    solo = _canonical(db, "OP01-999", name_en="Solo Print")
    solo_print = _print(db, solo, op01, "base")

    # Two printings in different products: the product label is what
    # separates them, so an unlabelled listing is ambiguous.
    ace = _canonical(db, "OP02-013")
    ace_base = _print(db, ace, op02, "base")
    ace_sp = _print(db, ace, op08, "p3", official_rarity="SPカード")

    # A second unambiguous code, so a batch can hold more than one row.
    second = _canonical(db, "OP01-998", name_en="Second Solo")
    second_print = _print(db, second, op01, "base")

    candidates = {
        "solo": _candidate(
            db, 900001, "Solo Print C [OP01-999] (Booster Pack ROMANCE DAWN)",
            detected_card_code="OP01-999", detected_set_code="OP-01",
        ),
        "second": _candidate(
            db, 900002, "Second Solo C [OP01-998] (Booster Pack ROMANCE DAWN)",
            detected_card_code="OP01-998", detected_set_code="OP-01",
        ),
        "ambiguous": _candidate(
            db, 900003, "Portgas.D.Ace SR [OP02-013]",
            detected_card_code="OP02-013",
        ),
        "already_matched": _candidate(
            db, 900004, "Solo Print C [OP01-999] (Booster Pack ROMANCE DAWN)",
            detected_card_code="OP01-999", detected_set_code="OP-01",
            match_status="matched",
        ),
        "foreign": _candidate(
            db, 900005, "Something Else [OP01-999] (Booster Pack ROMANCE DAWN)",
            detected_card_code="OP01-999", detected_set_code="OP-01",
            image_url="https://static.snkrdunk.com/SVE-TCG-bp08-117.webp",
        ),
        "unresolved_product": _candidate(
            db, 900006, "Solo Print C [OP01-999] (Some Product Atlas Cannot Read)",
            detected_card_code="OP01-999",
        ),
    }
    db.commit()
    return {
        "db": db,
        "c": candidates,
        "prints": {
            "solo": solo_print,
            "second": second_print,
            "ace_base": ace_base,
            "ace_sp": ace_sp,
        },
        "source": db.query(Source).filter_by(name="snkrdunk").one(),
    }


def _ids(world, *keys):
    return [world["c"][k].id for k in keys]


def _mapping_for(db, candidate):
    return db.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.source_url.like(f"%{candidate.source_url.rsplit('/', 1)[-1]}%")
        )
    ).one_or_none()


# --- scope -------------------------------------------------------------------


def test_an_unscoped_batch_is_refused(world):
    """There is no "approve all exact candidates" mode, and its absence is the
    feature: an operator approves the rows they read on a plan."""
    with pytest.raises(BatchApprovalError, match="unscoped"):
        plan_batch(world["db"], [])


def test_a_missing_candidate_id_aborts_rather_than_being_skipped(world):
    """A typo that quietly approves a smaller set is the failure mode."""
    with pytest.raises(BatchApprovalError, match="do not exist"):
        plan_batch(world["db"], _ids(world, "solo") + [999999])


# --- planning writes nothing -------------------------------------------------


def test_planning_writes_nothing(world):
    db = world["db"]
    before = db.scalar(select(SourceCardMapping.id).limit(1))
    report = plan_batch(db, _ids(world, "solo", "second"))
    assert len(report.approvable) == 2
    assert report.applied is False
    assert report.outcomes == []
    db.expire_all()
    assert db.scalar(select(SourceCardMapping.id).limit(1)) == before
    assert world["c"]["solo"].match_status == "unmatched"


def test_the_plan_states_every_fact_the_operator_has_to_check(world):
    plan = plan_batch(world["db"], _ids(world, "solo")).plans[0]
    row = plan.as_dict()
    for field in (
        "candidate_id",
        "source_url",
        "canonical_listing_url",
        "listing_identity",
        "card_code",
        "release_product",
        "card_print_id",
        "variant",
        "resolver_verdict",
        "evidence_used",
        "existing_mapping_id",
        "proposed_action",
        "refusal_code",
    ):
        assert field in row, field
    assert row["resolver_verdict"] == "exact"
    assert row["card_print_id"] == world["prints"]["solo"].id
    assert row["evidence_used"] == ["card code OP01-999", "product OP-01"]
    assert row["canonical_listing_url"] == "https://snkrdunk.com/apparels/900001"
    assert row["proposed_action"] == "create mapping"


# --- confirmation ------------------------------------------------------------


@pytest.mark.parametrize("phrase", [None, "", "approve", "Approve Exact Candidates", "yes"])
def test_apply_without_the_exact_confirmation_phrase_is_refused(world, phrase):
    with pytest.raises(BatchApprovalError, match="confirmation phrase"):
        apply_batch(world["db"], _ids(world, "solo"), confirm=phrase)
    world["db"].expire_all()
    assert world["c"]["solo"].match_status == "unmatched"


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    "key,code",
    [
        ("already_matched", REFUSAL_NOT_UNMATCHED),
        ("foreign", REFUSAL_NOT_ONE_PIECE),
        ("ambiguous", REFUSAL_NOT_EXACT),
        ("unresolved_product", REFUSAL_NOT_EXACT),
    ],
)
def test_ineligible_candidates_are_refused_with_a_reason(world, key, code):
    plan = plan_batch(world["db"], _ids(world, key)).plans[0]
    assert plan.approvable is False
    assert plan.refusal_code == code
    assert plan.refusal_reason


def test_the_unresolved_product_refusal_names_the_gate_s_own_code(world):
    """The batch's own code says "not exact"; the gate's says why. Both are
    reported, because "not exact" alone sends the operator looking at the
    artwork when the real problem is a product Atlas cannot read."""
    plan = plan_batch(world["db"], _ids(world, "unresolved_product")).plans[0]
    assert set(plan.sibling_refusals.values()) == {"source_product_unresolved"}
    assert "source_product_unresolved" in plan.verdict


def test_one_ineligible_candidate_refuses_the_whole_batch(world):
    """A batch approves the set it was given or none of it."""
    db = world["db"]
    with pytest.raises(BatchApprovalError, match="not approval-eligible"):
        apply_batch(db, _ids(world, "solo", "ambiguous"), confirm=CONFIRM_PHRASE)
    db.expire_all()
    assert world["c"]["solo"].match_status == "unmatched"
    assert db.scalar(select(SourceCardMapping.id).limit(1)) is None


# --- existing mappings -------------------------------------------------------


def test_a_rejected_mapping_on_the_same_listing_is_refused(world):
    """The 94915 case. A person quarantined that listing; a batch must not
    overturn that."""
    db = world["db"]
    db.add(
        SourceCardMapping(
            source_id=world["source"].id,
            source_card_id="OP01-999",
            # Deliberately the URL discovery saw, query string and all - the
            # shape the canonical-URL lookup does NOT find.
            source_url="https://snkrdunk.com/en/trading-cards/900001?slide=right&query_id=abc",
            review_status="rejected",
            review_notes="quarantined by a human",
            is_active=True,
        )
    )
    db.commit()
    plan = plan_batch(db, _ids(world, "solo")).plans[0]
    assert plan.refusal_code == REFUSAL_MAPPING_REJECTED
    assert plan.existing_mapping_id is not None


def test_a_mapping_naming_a_different_print_is_refused(world):
    db = world["db"]
    db.add(
        SourceCardMapping(
            source_id=world["source"].id,
            source_card_id="OP01-999",
            source_url="https://snkrdunk.com/apparels/900001",
            card_print_id=world["prints"]["ace_base"].id,
            review_status="approved",
            is_active=True,
        )
    )
    db.commit()
    plan = plan_batch(db, _ids(world, "solo")).plans[0]
    assert plan.refusal_code == REFUSAL_MAPPING_CONFLICT


def test_a_legacy_mapping_with_no_print_is_refused(world):
    db = world["db"]
    db.add(
        SourceCardMapping(
            source_id=world["source"].id,
            source_card_id="OP01-999",
            source_url="https://snkrdunk.com/apparels/900001",
            card_print_id=None,
            review_status="needs_review",
            is_active=True,
        )
    )
    db.commit()
    plan = plan_batch(db, _ids(world, "solo")).plans[0]
    assert plan.refusal_code == REFUSAL_MAPPING_NO_PRINT


def test_a_non_canonical_url_on_a_matching_mapping_is_refused(world):
    """Because the write reuses a mapping by URL equality, applying against a
    row stored under a third spelling would create a SECOND mapping for one
    listing rather than update it."""
    db = world["db"]
    db.add(
        SourceCardMapping(
            source_id=world["source"].id,
            source_card_id="OP01-999",
            source_url="https://snkrdunk.com/apparels/900001?ref=share",
            card_print_id=world["prints"]["solo"].id,
            review_status="approved",
            is_active=True,
        )
    )
    db.commit()
    plan = plan_batch(db, _ids(world, "solo")).plans[0]
    assert plan.refusal_code == REFUSAL_MAPPING_CONFLICT
    assert "SECOND mapping" in plan.refusal_reason


def test_two_mappings_for_one_listing_are_refused_rather_than_chosen_between(world):
    db = world["db"]
    for url in (
        "https://snkrdunk.com/apparels/900001",
        "https://snkrdunk.com/en/trading-cards/900001",
    ):
        db.add(
            SourceCardMapping(
                source_id=world["source"].id,
                source_card_id="OP01-999",
                source_url=url,
                card_print_id=world["prints"]["solo"].id,
                review_status="approved",
                is_active=True,
            )
        )
    db.commit()
    plan = plan_batch(db, _ids(world, "solo")).plans[0]
    assert plan.refusal_code == REFUSAL_MAPPING_CONFLICT
    assert "2 mappings" in plan.refusal_reason


# --- applying ----------------------------------------------------------------


def test_apply_writes_the_plan_and_nothing_else(world):
    db = world["db"]
    report = apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)

    assert report.applied is True
    assert len(report.outcomes) == 2
    assert report.mappings_created == 2
    assert report.mappings_reused == 0

    for outcome, key in zip(report.outcomes, ("solo", "second")):
        mapping = db.get(SourceCardMapping, outcome.mapping_id)
        assert mapping.card_print_id == world["prints"][key].id
        # PRINT-AUTHORITATIVE LINEAGE: the print carries the claim and the
        # legacy card pointer stays NULL. No `cards` row is manufactured.
        assert mapping.card_id is None
        assert mapping.review_status == "approved"
        assert mapping.manual_verified is True
        assert mapping.is_active is True
        assert mapping.source_url.startswith("https://snkrdunk.com/apparels/")
        assert "approved on card code" in mapping.review_notes
        assert world["c"][key].match_status == "matched"


def test_approval_creates_no_price_observations(world):
    """Approval makes a listing collectable. It does not collect it, and a
    price that appeared here would be a price nobody fetched."""
    db = world["db"]
    apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)
    assert db.scalars(select(PriceObservation)).all() == []


def test_no_legacy_card_rows_are_created(world):
    db = world["db"]
    before = len(db.scalars(select(Card)).all())
    apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)
    assert len(db.scalars(select(Card)).all()) == before


def test_re_running_the_same_batch_writes_nothing(world):
    """The candidates are `matched` afterwards, which the eligibility filter
    refuses - so idempotency is a consequence of the rules, not a special
    case someone has to remember to add."""
    db = world["db"]
    apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)
    mapping_ids = sorted(m.id for m in db.scalars(select(SourceCardMapping)).all())
    notes = {m.id: m.review_notes for m in db.scalars(select(SourceCardMapping)).all()}

    with pytest.raises(BatchApprovalError, match="not approval-eligible"):
        apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)

    db.expire_all()
    rows = db.scalars(select(SourceCardMapping)).all()
    assert sorted(m.id for m in rows) == mapping_ids
    assert {m.id: m.review_notes for m in rows} == notes


def test_a_candidate_that_moved_since_the_plan_aborts_the_whole_batch(world):
    """The plan the operator read is the thing being confirmed. If a print is
    deactivated - or anything else moves - between reading and applying, the
    batch is abandoned in full rather than partly applied."""
    db = world["db"]
    expected = plan_batch(db, _ids(world, "solo", "second")).plans

    world["prints"]["second"].is_active = False
    db.commit()

    with pytest.raises(BatchApprovalError, match="resolve differently now"):
        apply_batch(
            db,
            _ids(world, "solo", "second"),
            confirm=CONFIRM_PHRASE,
            expected_plan=expected,
        )
    db.expire_all()
    # Not even the candidate that DID still resolve was written.
    assert world["c"]["solo"].match_status == "unmatched"
    assert db.scalar(select(SourceCardMapping.id).limit(1)) is None


def test_a_batch_that_fails_partway_leaves_nothing_behind(world, monkeypatch):
    """One transaction, asserted by breaking the second write."""
    import app.approve_exact_snkrdunk_candidates as job

    real = job.approve_candidate_onto_print
    calls = {"n": 0}

    def exploding(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(job, "approve_candidate_onto_print", exploding)
    db = world["db"]
    with pytest.raises(RuntimeError, match="boom"):
        apply_batch(db, _ids(world, "solo", "second"), confirm=CONFIRM_PHRASE)
    db.expire_all()
    assert db.scalar(select(SourceCardMapping.id).limit(1)) is None
    assert world["c"]["solo"].match_status == "unmatched"


def test_artwork_evidence_is_not_required_and_is_not_consulted(world):
    """The canary runs with ARTWORK_EVIDENCE_ENABLED off, and every approvable
    candidate must be approvable on card code, product and variant alone."""
    from app.settings import settings

    assert settings.ARTWORK_EVIDENCE_ENABLED is False
    plan = plan_batch(world["db"], _ids(world, "solo")).plans[0]
    assert plan.approvable is True
    assert not any("artwork" in e for e in plan.evidence_used)


# --- the manual_verified equivalence claim -----------------------------------

_COMPARED_MAPPING_COLUMNS = (
    "card_id",
    "card_print_id",
    "source_id",
    "source_card_id",
    "source_url",
    "manual_verified",
    "review_status",
    "is_active",
    "review_notes",
    "match_confidence",
)


def test_the_batch_writes_exactly_what_the_human_endpoint_writes(world, client):
    """`manual_verified = true` means the same thing on both paths.

    THE SAME candidate is approved onto THE SAME print twice - once through
    POST /admin/snkrdunk-candidates/{id}/approve-match with no legacy card
    (what an operator's click sends for a print-authoritative approval), then
    the row is removed and the candidate reset, then once through the batch
    job - and every column of the resulting mapping is compared, along with
    the candidate's own review state. Approving two DIFFERENT listings and
    ignoring the columns that differ would prove much less: it would leave
    open exactly the fields whose values depend on which path wrote them.

    They agree because there is only one implementation: both call
    `app.services.snkrdunk_candidate_approval.approve_candidate_onto_print`.
    This test is what stops that becoming two implementations again.
    """
    db = world["db"]
    candidate = world["c"]["solo"]
    card_print_id = world["prints"]["solo"].id
    canonical_url = "https://snkrdunk.com/apparels/900001"

    def snapshot():
        db.expire_all()
        mapping = db.scalars(
            select(SourceCardMapping).where(SourceCardMapping.source_url == canonical_url)
        ).one()
        return (
            {c: getattr(mapping, c) for c in _COMPARED_MAPPING_COLUMNS},
            (
                candidate.match_status,
                candidate.matched_card_id,
                candidate.match_confidence,
                candidate.best_match_card_id,
                candidate.best_match_score,
                candidate.best_match_confidence_label,
                candidate.ambiguous_matches_json,
            ),
        )

    response = client.post(
        f"/admin/snkrdunk-candidates/{candidate.id}/approve-match",
        json={"card_print_id": card_print_id},
    )
    assert response.status_code == 200, response.text
    via_endpoint = snapshot()

    # Back to exactly the state the endpoint found, so the batch faces the
    # same row rather than a similar one.
    db.execute(
        SourceCardMapping.__table__.delete().where(
            SourceCardMapping.source_url == canonical_url
        )
    )
    candidate.match_status = "unmatched"
    candidate.matched_card_id = None
    candidate.match_confidence = None
    candidate.best_match_card_id = None
    candidate.best_match_score = None
    candidate.best_match_confidence_label = None
    candidate.ambiguous_matches_json = None
    db.commit()

    report = apply_batch(db, [candidate.id], confirm=CONFIRM_PHRASE)
    assert report.outcomes[0].card_print_id == card_print_id
    via_batch = snapshot()

    assert via_batch == via_endpoint
    mapping_columns = via_batch[0]
    assert mapping_columns["manual_verified"] is True
    assert mapping_columns["review_status"] == "approved"
    assert mapping_columns["card_id"] is None
    assert mapping_columns["card_print_id"] == card_print_id
