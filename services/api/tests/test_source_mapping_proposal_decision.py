from __future__ import annotations

from datetime import timedelta, timezone
import hashlib
import json
import time

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.admin_actor import AdminActor
from app.admin_actor import (
    ADMIN_ACTOR_AUDIENCE,
    ADMIN_ACTOR_ISSUER,
    ADMIN_ACTOR_PURPOSE,
    derive_admin_actor_key,
)
from app.db import Base
from app.main import app
from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    ReleaseProductAlias,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.services.exact_print_approval import ExactPrintApprovalError
from app.services.source_mapping_proposal_decision import (
    ProposalDecisionError,
    approve_exact_proposal,
)
from app.services.source_mapping_proposals import (
    ProposalFilters,
    analyse_source_mapping_proposals,
    persist_proposals,
)
from app.source_mapping_proposal_schemas import ApproveExactProposalIn


ACTOR = AdminActor(id="authjs-reviewer", email="Reviewer@Example.COM")
TEST_ADMIN_TOKEN = "test-admin-token"


def _source(db, name):
    row = Source(name=name, base_url=f"https://{name}.example.test")
    db.add(row)
    db.flush()
    return row


def _release(db, code, *, official=True):
    row = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=code if official else None,
        display_name=code,
        first_seen_name=code,
        source_series_id=f"series-{code}",
        source_url=f"https://bandai.example.test/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.flush()
    return row


def _family(db, code):
    row = CanonicalCard(card_code=code, name_en=code, card_type="Character")
    db.add(row)
    db.flush()
    return row


def _print(db, family, release, variant="base"):
    row = CardPrint(
        canonical_card_id=family.id,
        language="jp",
        release_product_code=release.official_code,
        release_product_id=release.id,
        artwork_key=f"sha256:{family.card_code}:{release.id}:{variant}",
        official_asset_variant=variant,
        verification_status="verified",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _run(db, slug):
    row = YuyuteiDiscoveryRun(
        status="completed",
        requested_set_slugs=[slug],
        per_slug_metrics_json={slug: {"enumeration_complete": True}},
    )
    db.add(row)
    db.flush()
    return row


def _persist_one(db, source_name, candidate_id):
    analysis = analyse_source_mapping_proposals(
        db, ProposalFilters(source=source_name, candidate_id=candidate_id)
    )
    assert len(analysis.plans) == 1
    persist_proposals(db, analysis.plans)
    db.commit()
    return db.scalar(
        select(SourceMappingProposalGroup).where(
            SourceMappingProposalGroup.source_candidate_id == candidate_id,
            SourceMappingProposalGroup.source_id
            == db.scalar(select(Source.id).where(Source.name == source_name)),
        )
    )


def _request(group, *, alternative_id=None, note=None, updated_at=None):
    basis = updated_at or group.updated_at
    if basis.tzinfo is None:
        basis = basis.replace(tzinfo=timezone.utc)
    return ApproveExactProposalIn(
        selected_alternative_id=alternative_id or group.alternatives[0].id,
        expected_evidence_digest=group.evidence_digest,
        expected_resolver_version=group.resolver_version,
        expected_updated_at=basis,
        review_note=note,
    )


def _base(db):
    return _source(db, "yuyutei"), _source(db, "snkrdunk")


def _seed_yuyu(db, *, status="family_matched", code="OP17-001", slug="op17"):
    yuyu, _ = _base(db)
    release = _release(db, "OP-17")
    family = _family(db, code)
    physical = _print(db, family, release)
    candidate = YuyuteiCandidate(
        discovery_run_id=_run(db, slug).id,
        set_slug=slug,
        product_id="7001",
        source_url=f"https://yuyu-tei.jp/sell/opc/card/{slug}/7001",
        detected_card_code=code,
        name_jp=code,
        match_status=status,
        matched_card_print_id=physical.id if status == "print_matched" else None,
    )
    db.add(candidate)
    db.flush()
    group = _persist_one(db, "yuyutei", candidate.id)
    return yuyu, release, family, physical, candidate, group


def _seed_snkr(db, *, uncoded=False):
    _, snkr = _base(db)
    release = _release(db, "LIMITED BOX" if uncoded else "OP-17", official=not uncoded)
    if uncoded:
        db.add(
            ReleaseProductAlias(
                product_id=release.id,
                source_id=snkr.id,
                alias_name="LIMITED BOX",
                alias_kind="source_rendering",
            )
        )
    family = _family(db, "OP17-002")
    physical = _print(db, family, release)
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/77002",
        title=f"Listing OP17-002 ({'LIMITED BOX' if uncoded else 'OP-17'})",
        detected_card_code=family.card_code,
        detected_set_code=None if uncoded else "OP-17",
        match_status="unmatched",
    )
    db.add(candidate)
    db.flush()
    group = _persist_one(db, "snkrdunk", candidate.id)
    return snkr, release, family, physical, candidate, group


def _approve(db, group, **kwargs):
    result = approve_exact_proposal(db, group.id, _request(group, **kwargs), ACTOR)
    db.commit()
    return result


def _api_body(group, **extra):
    updated = group.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    payload = {
        "selected_alternative_id": group.alternatives[0].id,
        "expected_evidence_digest": group.evidence_digest,
        "expected_resolver_version": group.resolver_version,
        "expected_updated_at": updated.isoformat(),
        **extra,
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _api_assertion(path, body):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ADMIN_ACTOR_ISSUER,
            "aud": ADMIN_ACTOR_AUDIENCE,
            "purpose": ADMIN_ACTOR_PURPOSE,
            "sub": "validated-authjs-admin",
            "email": "Trusted.Reviewer@Example.COM",
            "iat": now,
            "exp": now + 60,
            "jti": "proposal-api-test",
            "method": "POST",
            "path": path,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        },
        derive_admin_actor_key(TEST_ADMIN_TOKEN),
        algorithm="HS256",
    )


def test_yuyu_print_matched_exact_approval_succeeds(db_session):
    _, _, _, physical, candidate, group = _seed_yuyu(db_session, status="print_matched")
    result = _approve(db_session, group, note=" reviewed exactly ")
    assert result.card_print_id == physical.id
    assert result.reviewed_by == "reviewer@example.com"
    assert result.review_notes == "reviewed exactly"
    assert result.mapping_created and not result.mapping_reused
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id == physical.id


def test_review_api_uses_only_asserted_actor_and_preserves_contract(client, db_session):
    _, _, _, physical, _, group = _seed_yuyu(db_session)
    path = f"/admin/source-mapping-proposals/review/groups/{group.id}/approve-exact"
    body = _api_body(group, review_note="API approval")
    response = client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-admin-actor-assertion": _api_assertion(path, body),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reviewed_by"] == "trusted.reviewer@example.com"
    assert payload["card_print_id"] == physical.id
    assert payload["collection_triggered"] is False
    assert payload["price_observation_written"] is False


def test_review_api_missing_or_body_mismatched_actor_fails_without_mutation(client, db_session):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    path = f"/admin/source-mapping-proposals/review/groups/{group.id}/approve-exact"
    body = _api_body(group)
    missing = client.post(path, content=body, headers={"content-type": "application/json"})
    changed = client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-admin-actor-assertion": _api_assertion(path, body + b" "),
        },
    )
    assert missing.status_code == changed.status_code == 401
    assert db_session.query(SourceCardMapping).count() == 0
    assert db_session.get(SourceMappingProposalGroup, group.id).review_status == "pending"


def test_reviewed_by_in_api_body_is_forbidden(client, db_session):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    path = f"/admin/source-mapping-proposals/review/groups/{group.id}/approve-exact"
    body = _api_body(group, reviewed_by="attacker@example.com")
    response = client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-admin-actor-assertion": _api_assertion(path, body),
        },
    )
    assert response.status_code == 422
    assert db_session.query(SourceCardMapping).count() == 0


def test_review_route_rolls_back_failure_after_service_flush(
    client, db_session, monkeypatch
):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    path = f"/admin/source-mapping-proposals/review/groups/{group.id}/approve-exact"
    body = _api_body(group)
    import app.api.admin_source_mapping_proposals as route_module

    real_service = route_module.approve_exact_proposal

    def fail_after_service_flush(*args, **kwargs):
        real_service(*args, **kwargs)
        raise RuntimeError("forced route failure")

    monkeypatch.setattr(route_module, "approve_exact_proposal", fail_after_service_flush)
    response = client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            "x-admin-actor-assertion": _api_assertion(path, body),
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "proposal_decision_failed"
    assert db_session.query(SourceCardMapping).count() == 0
    pending = db_session.get(SourceMappingProposalGroup, group.id)
    assert pending.review_status == "pending"
    assert pending.resulting_source_card_mapping_id is None


def test_yuyu_family_matched_uses_release_scope_and_preserves_candidate(db_session):
    _, release, family, physical, candidate, group = _seed_yuyu(
        db_session, status="family_matched", code="OP12-056"
    )
    older = _release(db_session, "OP-12")
    old_print = _print(db_session, family, older)
    db_session.commit()
    # Re-materialize after adding the cross-release sibling; OP-17 remains exact.
    db_session.delete(group)
    db_session.commit()
    group = _persist_one(db_session, "yuyutei", candidate.id)

    result = _approve(db_session, group)
    assert result.card_print_id == physical.id
    assert result.card_print_id != old_print.id
    assert physical.release_product_id == release.id
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None


@pytest.mark.parametrize("uncoded", [False, True])
def test_snkrdunk_exact_and_uncoded_alias_approvals_succeed(db_session, uncoded):
    _, _, _, physical, candidate, group = _seed_snkr(db_session, uncoded=uncoded)
    result = _approve(db_session, group)
    assert result.card_print_id == physical.id
    assert result.candidate_status == "matched"
    assert candidate.match_status == "matched"


def test_approval_updates_lifecycle_atomically_and_writes_no_collection_rows(db_session):
    _, _, _, physical, _, group = _seed_yuyu(db_session)
    before = group.updated_at
    result = _approve(db_session, group)
    db_session.refresh(group)
    assert group.review_status == "approved"
    assert group.selected_alternative_id == group.alternatives[0].id
    assert group.resulting_source_card_mapping_id == result.resulting_source_card_mapping_id
    assert group.decision_basis_updated_at.replace(tzinfo=timezone.utc) == before.replace(
        tzinfo=timezone.utc
    )
    assert group.alternatives[0].review_disposition == "approved"
    assert group.alternatives[0].reviewed_at == group.reviewed_at
    mapping = db_session.get(SourceCardMapping, result.resulting_source_card_mapping_id)
    assert mapping.card_print_id == physical.id
    assert db_session.query(PriceObservation).count() == 0
    assert db_session.query(SourceCollectionAttempt).count() == 0
    assert db_session.query(RawSnapshot).count() == 0
    assert result.collection_triggered is False
    assert result.price_observation_written is False
    assert result.eligible_for_future_scheduled_collection is True


def test_idempotent_replay_changes_nothing_and_different_actor_or_note_refuses(db_session):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    request = _request(group, note="same note")
    first = approve_exact_proposal(db_session, group.id, request, ACTOR)
    db_session.commit()
    decided_at = first.reviewed_at
    mapping_count = db_session.query(SourceCardMapping).count()

    replay = approve_exact_proposal(db_session, group.id, request, ACTOR)
    db_session.commit()
    assert replay.idempotent_replay is True
    assert replay.reviewed_at == decided_at
    assert db_session.query(SourceCardMapping).count() == mapping_count

    for actor, note in [
        (AdminActor(id="other", email="other@example.com"), "same note"),
        (ACTOR, "different note"),
    ]:
        changed = request.model_copy(update={"review_note": note})
        with pytest.raises(ProposalDecisionError, match="does not match") as exc:
            approve_exact_proposal(db_session, group.id, changed, actor)
        assert exc.value.code == "proposal_not_pending"
        db_session.rollback()

    wrong_selection = request.model_copy(update={"selected_alternative_id": 999999})
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, wrong_selection, ACTOR)
    assert exc.value.code == "selected_alternative_not_in_group"
    db_session.rollback()

    wrong_basis = request.model_copy(
        update={"expected_updated_at": request.expected_updated_at - timedelta(seconds=1)}
    )
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, wrong_basis, ACTOR)
    assert exc.value.code == "proposal_not_pending"
    db_session.rollback()


def test_selected_alternative_from_another_group_and_extra_alternative_refuse(db_session):
    _, _, _, first_print, _, first = _seed_yuyu(db_session, code="OP17-010")
    # Add a second proposal without creating duplicate source rows.
    release = db_session.get(ReleaseProduct, first.release_product_id)
    family = _family(db_session, "OP17-011")
    second_print = _print(db_session, family, release)
    candidate = YuyuteiCandidate(
        discovery_run_id=_run(db_session, "op17b").id,
        set_slug="op17b",
        product_id="7011",
        source_url="https://yuyu-tei.jp/sell/opc/card/op17b/7011",
        detected_card_code=family.card_code,
        match_status="family_matched",
    )
    # slug must resolve to the release, so use an explicit proposal for this structural test.
    db_session.add(candidate)
    db_session.flush()
    second = SourceMappingProposalGroup(
        source_id=first.source_id,
        canonical_source_listing_identity="op17b:7011",
        source_url=candidate.source_url,
        source_candidate_type="yuyutei_candidate",
        source_candidate_id=candidate.id,
        canonical_card_id=family.id,
        release_product_id=release.id,
        resolution_status="exact",
        review_status="pending",
        resolver_version=first.resolver_version,
        evidence_digest="b" * 64,
        evidence_summary_json={},
        resolution_reasons_json=[],
    )
    db_session.add(second)
    db_session.flush()
    foreign_alt = SourceMappingProposalAlternative(
        proposal_group_id=second.id,
        card_print_id=second_print.id,
        recommended=True,
        supporting_evidence_json=[],
        missing_evidence_json=[],
        conflict_reasons_json=[],
    )
    db_session.add(foreign_alt)
    db_session.commit()

    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(
            db_session, first.id, _request(first, alternative_id=foreign_alt.id), ACTOR
        )
    assert exc.value.code == "selected_alternative_not_in_group"
    db_session.rollback()

    extra = SourceMappingProposalAlternative(
        proposal_group_id=first.id,
        card_print_id=second_print.id,
        recommended=False,
        supporting_evidence_json=[],
        missing_evidence_json=[],
        conflict_reasons_json=[],
    )
    db_session.add(extra)
    db_session.commit()
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, first.id, _request(first), ACTOR)
    assert exc.value.code == "proposal_has_no_single_recommended_alternative"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda group, candidate, print_row: setattr(group, "evidence_digest", "f" * 64), "evidence_digest_changed"),
        (lambda group, candidate, print_row: setattr(group, "resolver_version", "changed"), "resolver_version_changed"),
        (lambda group, candidate, print_row: setattr(candidate, "match_status", "unmatched"), "candidate_state_changed"),
        (lambda group, candidate, print_row: setattr(print_row, "is_active", False), "print_inactive"),
        (lambda group, candidate, print_row: setattr(print_row, "verification_status", "unverified"), "print_unverified"),
    ],
)
def test_stale_decision_bases_refuse_without_writes(db_session, mutation, code):
    _, _, _, physical, candidate, group = _seed_yuyu(db_session)
    request = _request(group)
    mutation(group, candidate, physical)
    db_session.commit()
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, request, ACTOR)
    assert exc.value.code == code
    db_session.rollback()
    assert db_session.query(SourceCardMapping).count() == 0
    assert db_session.get(SourceMappingProposalGroup, group.id).review_status == "pending"


def test_updated_at_concurrency_basis_refuses(db_session):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    stale = _request(group).model_copy(
        update={
            "expected_updated_at": group.updated_at.replace(tzinfo=timezone.utc)
            - timedelta(seconds=1)
        }
    )
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, stale, ACTOR)
    assert exc.value.code == "proposal_updated"


def test_ambiguous_and_unresolved_proposals_refuse(db_session):
    _base(db_session)
    release = _release(db_session, "OP-17")
    family = _family(db_session, "OP17-050")
    _print(db_session, family, release, "base")
    _print(db_session, family, release, "p1")
    candidate = YuyuteiCandidate(
        discovery_run_id=_run(db_session, "op17").id,
        set_slug="op17",
        product_id="7050",
        source_url="https://yuyu-tei.jp/sell/opc/card/op17/7050",
        detected_card_code=family.card_code,
        match_status="family_matched",
    )
    db_session.add(candidate)
    db_session.flush()
    ambiguous = _persist_one(db_session, "yuyutei", candidate.id)
    assert ambiguous.resolution_status == "ambiguous"
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, ambiguous.id, _request(ambiguous), ACTOR)
    assert exc.value.code == "proposal_not_exact"
    db_session.rollback()

    unresolved_candidate = YuyuteiCandidate(
        discovery_run_id=_run(db_session, "unknown").id,
        set_slug="unknown",
        product_id="7051",
        source_url="https://yuyu-tei.jp/sell/opc/card/unknown/7051",
        detected_card_code="UNKNOWN-001",
        match_status="unmatched",
    )
    db_session.add(unresolved_candidate)
    db_session.flush()
    unresolved = _persist_one(db_session, "yuyutei", unresolved_candidate.id)
    assert unresolved.resolution_status in {"release_unresolved", "unresolved_identity"}
    aware = unresolved.updated_at.replace(tzinfo=timezone.utc)
    request = ApproveExactProposalIn(
        selected_alternative_id=999999,
        expected_evidence_digest=unresolved.evidence_digest,
        expected_resolver_version=unresolved.resolver_version,
        expected_updated_at=aware,
    )
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, unresolved.id, request, ACTOR)
    assert exc.value.code == "proposal_not_exact"


def test_release_listing_evidence_and_resolver_drift_have_specific_refusals(
    db_session, monkeypatch
):
    # Release drift.
    _, _, _, physical, _, group = _seed_yuyu(db_session, code="OP17-060")
    request = _request(group)
    moved = _release(db_session, "OP-18")
    physical.release_product_id = moved.id
    physical.release_product_code = moved.official_code
    db_session.commit()
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, request, ACTOR)
    assert exc.value.code == "release_changed"
    db_session.rollback()

    # Each remaining case gets a fresh database shape by removing the first fixture.
    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()
    db_session.expunge_all()
    _, _, _, _, candidate, group = _seed_yuyu(db_session, code="OP17-061")
    request = _request(group)
    candidate.source_url = "https://yuyu-tei.jp/sell/opc/card/op17/9999"
    db_session.commit()
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, request, ACTOR)
    assert exc.value.code == "source_identity_changed"
    db_session.rollback()

    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()
    db_session.expunge_all()
    _, _, _, _, candidate, group = _seed_yuyu(db_session, code="OP17-062")
    request = _request(group)
    candidate.name_jp = "changed stored evidence"
    db_session.commit()
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, request, ACTOR)
    assert exc.value.code == "evidence_digest_changed"
    db_session.rollback()

    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()
    db_session.expunge_all()
    _, _, _, _, _, group = _seed_yuyu(db_session, code="OP17-063")
    request = _request(group)
    monkeypatch.setattr(
        "app.services.source_mapping_proposals.RESOLVER_VERSION", "source-mapping-proposals/2.0"
    )
    with pytest.raises(ProposalDecisionError) as exc:
        approve_exact_proposal(db_session, group.id, request, ACTOR)
    assert exc.value.code == "resolver_version_changed"


def test_rejected_conflicting_and_duplicate_mappings_use_writer_refusals(db_session):
    source, _, _, physical, candidate, group = _seed_yuyu(db_session)
    mapping = SourceCardMapping(
        source_id=source.id,
        source_card_id=candidate.detected_card_code,
        source_url=candidate.source_url,
        card_print_id=physical.id,
        review_status="rejected",
        is_active=False,
    )
    db_session.add(mapping)
    db_session.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        approve_exact_proposal(db_session, group.id, _request(group), ACTOR)
    assert exc.value.code == "existing_mapping_was_rejected"
    db_session.rollback()


@pytest.mark.parametrize(
    "case, expected_code",
    [
        ("rejected", "existing_mapping_was_rejected"),
        ("different_print", "existing_mapping_names_another_print"),
    ],
)
def test_snkrdunk_reusable_writer_owns_mapping_guards(db_session, case, expected_code):
    source, release, _, physical, candidate, group = _seed_snkr(db_session)
    mapped_print = physical
    if case == "different_print":
        mapped_print = _print(db_session, _family(db_session, "OP17-099"), release)
    first = SourceCardMapping(
        source_id=source.id,
        source_card_id=candidate.detected_card_code,
        source_url=candidate.source_url,
        card_print_id=mapped_print.id,
        review_status="rejected" if case == "rejected" else "needs_review",
        is_active=False,
    )
    db_session.add(first)
    db_session.commit()
    with pytest.raises(ExactPrintApprovalError) as exc:
        approve_exact_proposal(db_session, group.id, _request(group), ACTOR)
    assert exc.value.code == expected_code
    db_session.rollback()
    assert db_session.get(SourceMappingProposalGroup, group.id).review_status == "pending"


def test_forced_failure_after_mapping_flush_rolls_everything_back(db_session, monkeypatch):
    _, _, _, _, _, group = _seed_yuyu(db_session)
    import app.services.source_mapping_proposal_decision as decision_module

    real_writer = decision_module.approve_candidate_from_exact_proposal

    def fail_after_flush(*args, **kwargs):
        real_writer(*args, **kwargs)
        raise RuntimeError("forced after mapping flush")

    monkeypatch.setattr(decision_module, "approve_candidate_from_exact_proposal", fail_after_flush)
    with pytest.raises(RuntimeError, match="forced"):
        approve_exact_proposal(db_session, group.id, _request(group), ACTOR)
    db_session.rollback()
    assert db_session.query(SourceCardMapping).count() == 0
    reloaded = db_session.get(SourceMappingProposalGroup, group.id)
    assert reloaded.review_status == "pending"
    assert reloaded.selected_alternative_id is None


def test_request_schema_forbids_reviewer_and_requires_timezone():
    with pytest.raises(ValidationError):
        ApproveExactProposalIn.model_validate(
            {
                "selected_alternative_id": 1,
                "expected_evidence_digest": "a" * 64,
                "expected_resolver_version": "v1",
                "expected_updated_at": "2026-09-22T00:00:00Z",
                "reviewed_by": "attacker@example.com",
            }
        )
    with pytest.raises(ValidationError):
        ApproveExactProposalIn.model_validate(
            {
                "selected_alternative_id": 1,
                "expected_evidence_digest": "a" * 64,
                "expected_resolver_version": "v1",
                "expected_updated_at": "2026-09-22T00:00:00",
            }
        )


def test_openapi_registers_only_the_exact_approval_mutation():
    path = "/admin/source-mapping-proposals/review/groups/{proposal_group_id}/approve-exact"
    assert "post" in app.openapi()["paths"][path]
    proposal_paths = {
        name: methods
        for name, methods in app.openapi()["paths"].items()
        if name.startswith("/admin/source-mapping-proposals")
    }
    mutation_operations = [
        (name, method)
        for name, methods in proposal_paths.items()
        for method in methods
        if method.lower() in {"post", "put", "patch", "delete"}
    ]
    assert mutation_operations == [(path, "post")]
