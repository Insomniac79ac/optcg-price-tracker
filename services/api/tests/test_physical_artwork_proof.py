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

    class Session:
        def get(self, model, identifier):
            return (
                work
                if model is FreshnessWork and identifier == 99
                else rows.get(identifier) if model is RawSnapshot else None
            )

        def scalars(self, statement):
            return Row(all=lambda: attempts)

    return Row(
        plan=plan,
        siblings=siblings,
        proof=proof,
        rows=rows,
        work=work,
        attempts=attempts,
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
