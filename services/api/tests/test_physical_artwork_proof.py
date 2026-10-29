"""Adversarial contracts for explicit retained physical artwork review."""

import base64
import copy
import hashlib
import io
import json
from types import SimpleNamespace as Row

import pytest
from PIL import Image, PngImagePlugin

from app.models import FreshnessWork, RawSnapshot
from app.services import physical_artwork_proof as proof_module
from app.settings import settings


def image(color, metadata=None):
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("test", metadata)
    Image.new("RGB", (8, 12), color).save(output, format="PNG", pnginfo=info)
    body = output.getvalue()
    digest = hashlib.sha256(body).hexdigest()
    content = json.dumps(
        {
            "encoding": "base64",
            "body": base64.b64encode(body).decode(),
            "body_sha256": digest,
        }
    )
    return content, digest


@pytest.fixture
def evidence():
    plan = Row(
        source_name="yuyutei",
        canonical_source_listing_identity="yuyutei:op01:10151",
        resolution_status="ambiguous",
        source_candidate_id=1,
        source_url="https://yuyu-tei.jp/sell/opc/card/op01/10151",
        evidence_digest="current-evidence",
        release_product_id=1,
        source_id=1,
        card_code="OP01-120",
    )
    records = []
    siblings = []
    rows = {}
    for index, (variant, color) in enumerate(
        [("base", "red"), ("p1", "green"), ("p2", "blue")], 10
    ):
        content, digest = image(color)
        url = f'https://www.onepiece-cardgame.com/images/cardlist/card/OP01-120{"" if variant == "base" else "_"+variant}.png'
        rows[index] = Row(
            id=index,
            source_id=1,
            source_url=url,
            raw_content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            http_status=200,
            parser_version="yuyu-identity-evidence-v1",
        )
        siblings.append(
            Row(
                id=index,
                language="jp",
                release_product_id=1,
                is_active=True,
                verification_status="verified",
                image_url=url,
                official_asset_variant=variant,
                artwork_key=digest,
            )
        )
        records.append(
            dict(
                card_print_id=index,
                raw_snapshot_id=index,
                official_asset_variant=variant,
                body_sha256=digest,
            )
        )
    source_url = "https://card.yuyu-tei.jp/opc/front/op01/10151.jpg"
    content, digest = image("green")
    rows[2] = Row(
        id=2,
        source_id=1,
        source_url=source_url,
        raw_content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        http_status=200,
        parser_version="yuyu-identity-evidence-v1",
    )
    product = '<html><img src="' + source_url + '"></html>'
    rows[1] = Row(
        id=1,
        source_id=1,
        source_url=plan.source_url,
        raw_content=product,
        content_hash=hashlib.sha256(product.encode()).hexdigest(),
        http_status=200,
        parser_version="yuyu-identity-evidence-v1",
    )
    proof = dict(
        source_candidate_id=1,
        source_url=plan.source_url,
        baseline_evidence_digest=plan.evidence_digest,
        release_product_id=1,
        language="jp",
        review_method="codex_visual_review_of_unique_full_physical_artwork",
        actor="codex:test-review",
        reviewed_at="2026-10-06T09:32:00+00:00",
        selected_card_print_id=11,
        considered_print_ids=[10, 11, 12],
        positive_physical_basis="Complete distinct physical illustration reviewed",
        excluded_sibling_basis={
            "10": "distinct base artwork",
            "12": "distinct alternate background",
        },
        work_id=99,
        source_product_snapshot_id=1,
        source_product_content_hash=rows[1].content_hash,
        source_image_snapshot_id=2,
        source_image_url=source_url,
        source_body_sha256=digest,
        official_images=records,
    )
    cursor = dict(
        evidence_digest=plan.evidence_digest,
        candidate_id=1,
        release_product_id=1,
        considered_print_ids=[10, 11, 12],
        source_product_snapshot_id=1,
        source_image_snapshot_id=2,
        official_images=copy.deepcopy(records),
    )
    work = Row(
        id=99,
        source_id=1,
        kind="discovery",
        scope_key="yuyu-identity:1",
        attempt_count=1,
        last_outcome="completed",
        resume_cursor=cursor,
    )
    attempts = [Row(outcome="completed", raw_snapshot_id=1, actual_request_cost=59)]
    history = []  # evidence summaries of this listing's proposal groups, as the query returns them

    class Session:
        def get(self, model, identifier):
            return (
                work
                if model is FreshnessWork and identifier == 99
                else rows.get(identifier) if model is RawSnapshot else None
            )

        def scalars(self, statement):
            if "source_mapping_proposal_groups" in str(statement):
                return Row(all=lambda: list(history))
            return Row(all=lambda: attempts)

    return Row(
        plan=plan,
        siblings=siblings,
        proof=proof,
        rows=rows,
        work=work,
        attempts=attempts,
        history=history,
        session=Session(),
    )


def test_valid_explicit_review_returns_only_named_unique_print_without_writes(
    evidence, monkeypatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    selected, digest, actor = proof_module.resolve(
        evidence.session, evidence.plan, evidence.siblings
    )
    assert selected == 11 and len(digest) == 64 and actor == "codex:test-review"


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_candidate_id", 2),
        ("source_url", "https://yuyu-tei.jp/sell/opc/card/op02/10151"),
        ("baseline_evidence_digest", "stale"),
        ("release_product_id", 2),
        ("language", "en"),
        ("review_method", "perceptual_similarity"),
        ("actor", "anonymous"),
        ("reviewed_at", "not-time"),
        ("reviewed_at", "2026-10-06T09:00:00+09:00"),
        ("positive_physical_basis", ""),
        ("selected_card_print_id", 999),
        ("considered_print_ids", [10, 11]),
        ("excluded_sibling_basis", {"10": "only one exclusion"}),
        ("official_images", []),
        ("source_product_content_hash", "changed"),
        ("source_body_sha256", "changed"),
    ],
)
def test_stale_or_incomplete_review_retains_ambiguity(
    evidence, monkeypatch, field, value
):
    evidence.proof[field] = value
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    assert (
        proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None
    )


@pytest.mark.parametrize(
    "defect",
    [
        "missing_raw",
        "changed_envelope",
        "http_failure",
        "bad_image",
        "changed_release",
        "changed_variant",
        "changed_language",
        "incomplete_capture",
        "duplicate_attempt",
        "over_budget",
    ],
)
def test_retained_lineage_and_physical_identity_fail_closed(evidence, defect):
    if defect == "missing_raw":
        evidence.rows.pop(10)
    elif defect == "changed_envelope":
        evidence.rows[10].raw_content += "changed"
    elif defect == "http_failure":
        evidence.rows[10].http_status = 403
    elif defect == "bad_image":
        evidence.rows[10].raw_content = "{}"
    elif defect == "changed_release":
        evidence.siblings[0].release_product_id = 2
    elif defect == "changed_variant":
        evidence.siblings[0].official_asset_variant = "p9"
    elif defect == "changed_language":
        evidence.siblings[0].language = "en"
    elif defect == "incomplete_capture":
        evidence.work.resume_cursor["official_images"].pop()
    elif defect == "duplicate_attempt":
        evidence.attempts.append(evidence.attempts[0])
    elif defect == "over_budget":
        evidence.attempts[0].actual_request_cost = 101
    with pytest.raises((ValueError, KeyError)):
        proof_module.validate(
            evidence.session, evidence.plan, evidence.siblings, evidence.proof
        )


def test_same_art_physical_twins_with_distinct_byte_hashes_remain_ambiguous(evidence):
    content, digest = image("green", "different PNG metadata")
    row = evidence.rows[12]
    row.raw_content = content
    row.content_hash = hashlib.sha256(content.encode()).hexdigest()
    evidence.siblings[2].artwork_key = digest
    evidence.proof["official_images"][2]["body_sha256"] = digest
    assert digest != evidence.proof["official_images"][1]["body_sha256"]
    with pytest.raises(ValueError, match="same-art physical twins"):
        proof_module.validate(
            evidence.session, evidence.plan, evidence.siblings, evidence.proof
        )


@pytest.mark.parametrize("environment", [None, "development", "production"])
def test_review_registry_disabled_outside_staging(evidence, monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(
        proof_module,
        "registry",
        lambda: pytest.fail("registry consulted outside staging"),
    )
    assert (
        proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None
    )


def test_duplicate_review_does_not_choose_a_winner(evidence, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(
        proof_module, "registry", lambda: [evidence.proof, evidence.proof]
    )
    assert (
        proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None
    )


def test_proposal_integration_recommends_only_reviewed_print_and_preserves_manual_mapping(
    db_session, monkeypatch
):
    from tests.test_source_mapping_proposals import (
        _base,
        _release,
        _family,
        _print,
        _run,
        _yuyu,
    )
    from app.models import SourceCardMapping
    from app.services.source_mapping_proposals import analyse_source_mapping_proposals

    source, _ = _base(db_session)
    release = _release(db_session, "OP-01")
    family = _family(db_session, "OP01-120")
    _print(db_session, family, release)
    selected = _print(db_session, family, release, "p1")
    candidate = _yuyu(
        db_session, _run(db_session, "op01"), "op01", 10151, family.card_code
    )
    db_session.commit()
    baseline = analyse_source_mapping_proposals(db_session).plans[0]
    assert baseline.resolution_status == "ambiguous"
    monkeypatch.setattr(
        proof_module,
        "resolve",
        lambda *args: (selected.id, "review-digest", "codex:test-review"),
    )
    plan = analyse_source_mapping_proposals(db_session).plans[0]
    assert plan.resolution_status == "exact"
    assert [a.card_print_id for a in plan.alternatives if a.recommended] == [
        selected.id
    ]
    assert plan.evidence_digest != baseline.evidence_digest
    assert (
        plan.evidence_summary["positive_physical_artwork_proof"]["actor"]
        == "codex:test-review"
    )
    assert db_session.query(SourceCardMapping).count() == 0
    db_session.add(
        SourceCardMapping(
            source_id=source.id,
            card_print_id=selected.id,
            source_card_id=family.card_code,
            source_url=candidate.source_url,
            review_status="approved",
            manual_verified=True,
            is_active=True,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        proof_module, "resolve", lambda *args: pytest.fail("manual mapping overridden")
    )
    assert not analyse_source_mapping_proposals(db_session).plans


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "wrong_scope",
        "missing_proof_scope",
        "old_attempt",
        "old_digest",
        "unknown_version",
    ],
)
def test_versioned_capture_requires_new_single_attempt_and_current_digest(
    evidence, tamper
):
    from app.services.identity_evidence_scope import identity_evidence_scope

    e = evidence
    digest = "a" * 64
    e.plan.evidence_digest = digest
    e.proof["baseline_evidence_digest"] = digest
    e.work.resume_cursor.update(version=2, evidence_digest=digest)
    scope = identity_evidence_scope(1, digest, 2)
    e.work.scope_key = scope
    e.proof["capture_scope"] = scope
    if tamper == "wrong_scope":
        e.work.scope_key = identity_evidence_scope(1, "b" * 64, 2)
    if tamper == "missing_proof_scope":
        e.proof.pop("capture_scope")
    if tamper == "old_attempt":
        e.work.attempt_count = 2
    if tamper == "old_digest":
        e.work.resume_cursor["evidence_digest"] = "b" * 64
    if tamper == "unknown_version":
        e.work.resume_cursor["version"] = 3
    if tamper:
        with pytest.raises(ValueError):
            proof_module.validate(e.session, e.plan, e.siblings, e.proof)
    else:
        assert len(proof_module.validate(e.session, e.plan, e.siblings, e.proof)) == 64


@pytest.mark.parametrize(
    "version,digest",
    [
        (True, "a" * 64),
        (3, "a" * 64),
        (2, "A" * 64),
        (2, "a" * 63),
        (2, "a" * 64 + ":other"),
    ],
)
def test_capture_scope_refuses_noncanonical_versions_and_digests(version, digest):
    from app.services.identity_evidence_scope import identity_evidence_scope

    with pytest.raises(ValueError):
        identity_evidence_scope(1, digest, version)


def _legacy_bound(evidence, plan_summary, stored_summary):
    """A review recorded under resolver 1.2: its baseline hashed the full summary,
    including the discovery run that last saw the listing."""
    from app.services.source_mapping_proposals import evidence_digest, legacy_evidence_digest

    baseline = legacy_evidence_digest(stored_summary)
    evidence.plan.evidence_summary = plan_summary
    evidence.plan.evidence_digest = evidence_digest(plan_summary)  # 1.3, run-independent
    evidence.proof["baseline_evidence_digest"] = baseline
    evidence.work.resume_cursor["evidence_digest"] = baseline
    evidence.work.resume_cursor["evidence_summary"] = stored_summary


LISTING = {"candidate_id": 1, "price_jpy": 1280, "availability": "in_stock",
           "raw_listing_digest": "a" * 64, "eligible_print_identity": [{"card_print_id": 10}]}


def test_review_bound_under_1_2_reattaches_to_identical_evidence_from_a_later_run(
    evidence, monkeypatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    _legacy_bound(evidence, {**LISTING, "discovery_run_id": 900}, {**LISTING, "discovery_run_id": 143})
    assert evidence.proof["baseline_evidence_digest"] != evidence.plan.evidence_digest
    selected, digest, actor = proof_module.resolve(evidence.session, evidence.plan, evidence.siblings)
    assert selected == 11 and len(digest) == 64


@pytest.mark.parametrize("field,value", [("price_jpy", 1480), ("availability", "sold_out"),
                                         ("raw_listing_digest", "b" * 64)])
def test_review_survives_a_market_change_since_its_capture(evidence, monkeypatch, field, value):
    """Owner 2026-10-29: a review is about artwork; price, stock and row text change daily."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    _legacy_bound(evidence, {**LISTING, field: value, "discovery_run_id": 900},
                  {**LISTING, "discovery_run_id": 143})
    selected, _, _ = proof_module.resolve(evidence.session, evidence.plan, evidence.siblings)
    assert selected == 11


@pytest.mark.parametrize("field,value", [("eligible_print_identity", [{"card_print_id": 11}]),
                                         ("name_jp", "other"), ("image_url", "https://x/other.jpg"),
                                         ("detected_rarity", "SR"), ("candidate_id", 2),
                                         ("detected_card_code", "OP01-121"),
                                         ("resolved_canonical_card_id", 77)])
def test_review_bound_under_1_2_never_transfers_across_real_evidence_change(
    evidence, monkeypatch, field, value
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    _legacy_bound(evidence, {**LISTING, field: value, "discovery_run_id": 900},
                  {**LISTING, "discovery_run_id": 143})
    assert proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None


@pytest.mark.parametrize("tamper", ["baseline", "cursor_digest", "no_stored_summary"])
def test_legacy_bridge_requires_the_capture_own_stored_evidence(evidence, monkeypatch, tamper):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    _legacy_bound(evidence, {**LISTING, "discovery_run_id": 900}, {**LISTING, "discovery_run_id": 143})
    if tamper == "baseline":
        evidence.proof["baseline_evidence_digest"] = "f" * 64
    elif tamper == "cursor_digest":
        evidence.work.resume_cursor["evidence_digest"] = "f" * 64
    else:
        del evidence.work.resume_cursor["evidence_summary"]
    assert proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None


def _history_bound(evidence, plan_summary, stored_summary):
    """A capture planned under 1.3 evidence that only the proposal history still holds."""
    from app.services.source_mapping_proposals import evidence_digest

    baseline = evidence_digest(stored_summary)
    evidence.plan.evidence_summary = plan_summary
    evidence.plan.evidence_digest = evidence_digest(plan_summary)
    evidence.proof["baseline_evidence_digest"] = baseline
    evidence.work.resume_cursor["evidence_digest"] = baseline
    evidence.history.append(stored_summary)


def test_review_reattaches_through_the_listing_proposal_history_after_a_price_change(
    evidence, monkeypatch
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    _history_bound(evidence, {**LISTING, "price_jpy": 1980, "discovery_run_id": 900},
                   {**LISTING, "discovery_run_id": 143})
    assert "evidence_summary" not in evidence.work.resume_cursor
    selected, _, _ = proof_module.resolve(evidence.session, evidence.plan, evidence.siblings)
    assert selected == 11


@pytest.mark.parametrize("defect", ["identity_changed", "no_history", "history_does_not_hash",
                                    "cursor_planned_elsewhere"])
def test_history_binding_fails_closed(evidence, monkeypatch, defect):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    current = {**LISTING, "price_jpy": 1980, "discovery_run_id": 900}
    if defect == "identity_changed":
        current["eligible_print_identity"] = [{"card_print_id": 10}, {"card_print_id": 13}]
    _history_bound(evidence, current, {**LISTING, "discovery_run_id": 143})
    if defect == "no_history":
        evidence.history.clear()
    elif defect == "history_does_not_hash":
        evidence.history[0] = {**LISTING, "name_jp": "tampered"}
    elif defect == "cursor_planned_elsewhere":
        evidence.work.resume_cursor["evidence_digest"] = "f" * 64
    assert proof_module.resolve(evidence.session, evidence.plan, evidence.siblings) is None


@pytest.mark.parametrize("method,actor,ok", [
    ("claude_visual_review_of_unique_full_physical_artwork", "claude:retained-review-2026-10-29", True),
    ("codex_visual_review_of_unique_full_physical_artwork", "codex:test-review", True),
    ("claude_visual_review_of_unique_full_physical_artwork", "codex:test-review", False),
    ("codex_visual_review_of_unique_full_physical_artwork", "claude:retained-review", False),
    ("claude_visual_review_of_unique_full_physical_artwork", "claude:", False),
    ("claude_visual_review_of_unique_full_physical_artwork", "claude: ", False),
    ("claude_visual_review_of_unique_full_physical_artwork", "claude:review\n", False),
    ("claude_visual_review_of_unique_full_physical_artwork", None, False),
])
def test_reviewer_method_and_actor_namespace_come_as_a_pair(evidence, monkeypatch, method, actor, ok):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    evidence.proof.update(review_method=method, actor=actor)
    result = proof_module.resolve(evidence.session, evidence.plan, evidence.siblings)
    assert (result is not None) is ok
    if ok:
        assert result[2] == actor


def test_identity_check_against_the_real_resolver_and_proposal_history(db_session):
    """Price, stock and row text move; the listing identity does not. Postgres-free, real resolver."""
    from tests.test_source_mapping_proposals import _base, _release, _family, _print, _run, _yuyu
    from app.services.source_mapping_proposals import (
        persist_proposals,
        resolve_current_candidate_proposal,
        yuyu_identity_unchanged_since,
    )

    _base(db_session)
    release = _release(db_session, "OP-01")
    family = _family(db_session, "OP01-120")
    _print(db_session, family, release)
    _print(db_session, family, release, "p1")
    candidate = _yuyu(db_session, _run(db_session, "op01"), "op01", 10151, family.card_code,
                      price_jpy=1280, availability="in_stock", raw_listing_text="1,280円 在庫あり")
    db_session.commit()

    def current():
        return resolve_current_candidate_proposal(db_session, source_name="yuyutei", candidate_id=candidate.id)

    planned = current()
    assert planned.resolution_status == "ambiguous"
    persist_proposals(db_session, [planned])
    db_session.commit()
    candidate.price_jpy, candidate.availability, candidate.raw_listing_text = 1980, "out_of_stock", "1,980円 売切"
    candidate.discovery_run_id = _run(db_session, "op01").id
    db_session.commit()
    moved = current()
    assert moved.evidence_digest != planned.evidence_digest
    persist_proposals(db_session, [moved])  # the planned version is now superseded history
    db_session.commit()
    assert yuyu_identity_unchanged_since(db_session, moved, planned.evidence_digest)
    assert not yuyu_identity_unchanged_since(db_session, moved, "e" * 64)
    assert not yuyu_identity_unchanged_since(db_session, moved, None)

    candidate.name_jp = "renamed listing"
    db_session.commit()
    assert not yuyu_identity_unchanged_since(db_session, current(), planned.evidence_digest)
    candidate.name_jp = family.card_code
    _print(db_session, family, release, "p2")  # the sibling set changed
    db_session.commit()
    assert not yuyu_identity_unchanged_since(db_session, current(), planned.evidence_digest)


def test_a_1_2_digest_found_through_the_proposal_history_binds(evidence, monkeypatch):
    from app.services.source_mapping_proposals import evidence_digest, legacy_evidence_digest

    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(proof_module, "registry", lambda: [evidence.proof])
    stored = {**LISTING, "discovery_run_id": 143}
    current = {**LISTING, "price_jpy": 1980, "discovery_run_id": 900}
    baseline = legacy_evidence_digest(stored)
    evidence.plan.evidence_summary, evidence.plan.evidence_digest = current, evidence_digest(current)
    evidence.proof["baseline_evidence_digest"] = baseline
    evidence.work.resume_cursor["evidence_digest"] = baseline
    evidence.history.append(stored)
    assert proof_module.resolve(evidence.session, evidence.plan, evidence.siblings)[0] == 11
