"""Offline capture evidence: source bytes first, no identity/price decision."""

import base64
import json
import io
from PIL import Image
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/api"))
from app.services.freshness_integration import AdmissionStopped
from yuyutei_collector.identity_evidence import (
    capture_pages,
    load_intent,
    product_image_url,
    official_image_url,
    retain_image,
)


def candidate():
    return NS(
        set_slug="op01",
        product_id="10002",
        detected_card_code="OP01-001",
        source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
    )


class Evidence:
    def __init__(self):
        self.snapshots, self.requests, self.result = [], [], None
        self.denied = False
        self.begin_result = Mock()
        self.clock = lambda: datetime.now(timezone.utc)

    def snapshot(self, source_id, url, step, parser):
        self.snapshots.append((url, step, parser))
        return len(self.snapshots)

    def request_bytes(self, page, url):
        assert any("/sell/opc/card/" in s[0] for s in self.snapshots)
        self.requests.append(url)
        raw = io.BytesIO()
        Image.new("RGB", (40, 56), "red").save(raw, format="PNG")
        return raw.getvalue()

    def deny(self):
        self.denied = True

    def check(self):
        if self.denied:
            raise AdmissionStopped("required source denial")


def test_capture_retains_exact_product_and_all_assets_before_any_decision():
    html = (
        Path(__file__).parent / "fixtures/product_op01_001_reduced.html"
    ).read_text()
    c = candidate()
    plan, claim = NS(source_id=1), NS(resume_cursor={"version": 1})
    prints = [
        NS(id=1, official_asset_variant="base", artwork_key="base"),
        NS(id=2, official_asset_variant="p2", artwork_key="parallel"),
    ]
    urls = {
        1: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png",
        2: "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
    }
    freshness = Evidence()
    steps = [
        {"html": "<html>homepage</html>", "http_status": 200},
        {"html": html, "http_status": 200, "final_url": c.source_url},
    ]
    with patch(
        "yuyutei_collector.identity_evidence.goto_and_capture_raw", side_effect=steps
    ), patch(
        "yuyutei_collector.identity_evidence.classify_capture",
        return_value={"classification": "normal_product", "http_status": 200},
    ), patch(
        "yuyutei_collector.identity_evidence.time.sleep"
    ):
        result = capture_pages(Mock(), claim, freshness, Mock(), c, plan, prints, urls)
    assert result.stage == "identity_evidence_captured"
    assert len(freshness.requests) == 3 and len(freshness.snapshots) == 5
    body = json.loads(freshness.snapshots[2][1]["html"])
    assert base64.b64decode(body["body"]).startswith(b"\x89PNG")
    assert freshness.result.raw_snapshot_id == 2
    assert freshness.result.observation_ids == {}
    assert freshness.result.resume_cursor["identity_status"].startswith("unresolved")
    assert len(freshness.result.resume_cursor["official_images"]) == 2
    freshness.begin_result.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/opc/front/op01/10002.jpg",
        "https://card.yuyu-tei.jp/opc/front/op01/10003.jpg",
        "https://card.yuyu-tei.jp/opc/front/op02/10002.jpg",
        "https://card.yuyu-tei.jp/opc/front/op01/10002.jpg?credential=secret",
        "/opc/front/op01/10002.jpg",
    ],
)
def test_unknown_or_other_product_image_is_refused(url):
    with pytest.raises(ValueError):
        product_image_url(url, candidate())


def test_official_asset_must_be_authoritative_and_name_the_exact_variant():
    p = NS(
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
        official_asset_variant="p2",
    )
    assert official_image_url(p, "OP01-001") == p.image_url
    p.official_asset_variant = "p1"
    with pytest.raises(ValueError):
        official_image_url(p, "OP01-001")


def test_required_denial_is_retained_before_aborting_without_asset_fetch():
    freshness = Evidence()
    with patch(
        "yuyutei_collector.identity_evidence.goto_and_capture_raw",
        return_value={"html": "denied", "http_status": 403},
    ), patch(
        "yuyutei_collector.identity_evidence.classify_capture",
        return_value={"classification": "static_403"},
    ):
        with pytest.raises(AdmissionStopped):
            capture_pages(
                Mock(),
                NS(resume_cursor={}),
                freshness,
                Mock(),
                candidate(),
                NS(source_id=1),
                [],
                {},
            )
    assert len(freshness.snapshots) == 1 and freshness.requests == []


def test_changed_evidence_or_second_attempt_refuses_before_network():
    work = NS(kind="discovery", attempt_count=2, scope_key="yuyu-identity:1")
    session = Mock()
    session.get.return_value = work
    claim = NS(
        work_id=1, resume_cursor={"candidate_id": 1, "explicit_identity_capture": True}
    )
    with pytest.raises(ValueError):
        load_intent(session, claim)
    work.attempt_count = 1
    session.get.side_effect = [work, candidate()]
    with patch(
        "yuyutei_collector.identity_evidence.resolve_current_candidate_proposal",
        return_value=NS(resolution_status="ambiguous", evidence_digest="changed"),
    ):
        with pytest.raises(ValueError):
            load_intent(session, claim)


def test_invalid_image_bytes_are_durable_before_decode_refusal():
    freshness = Evidence()
    with pytest.raises(ValueError):
        retain_image(
            freshness,
            1,
            "https://card.yuyu-tei.jp/opc/front/op01/10002.jpg",
            b"not an image",
        )
    assert len(freshness.snapshots) == 1
    assert (
        base64.b64decode(json.loads(freshness.snapshots[0][1]["html"])["body"])
        == b"not an image"
    )


@pytest.mark.parametrize("tamper", [None, "scope", "digest", "attempt", "version"])
def test_versioned_intent_retains_current_canonical_guards_before_io(tamper):
    from app.services.identity_evidence_scope import identity_evidence_scope

    digest = "a" * 64
    cursor = dict(
        version=2,
        candidate_id=1,
        explicit_identity_capture=True,
        evidence_digest=digest,
        release_product_id=1,
        considered_print_ids=[1, 2],
    )
    work = NS(
        kind="discovery",
        attempt_count=1,
        source_id=1,
        scope_key=identity_evidence_scope(1, digest, 2),
    )
    plan = NS(
        resolution_status="ambiguous",
        evidence_digest=digest,
        release_product_id=1,
        source_id=1,
        alternatives=[NS(card_print_id=1), NS(card_print_id=2)],
    )
    if tamper == "scope":
        work.scope_key = "yuyu-identity:1"
    if tamper == "digest":
        cursor["evidence_digest"] = "b" * 64
    if tamper == "attempt":
        work.attempt_count = 2
    if tamper == "version":
        cursor["version"] = True
    session = Mock()
    session.get.side_effect = [work, candidate()]
    session.scalars.return_value.all.return_value = [NS(id=1), NS(id=2)]
    with patch(
        "yuyutei_collector.identity_evidence.resolve_current_candidate_proposal",
        return_value=plan,
    ), patch(
        "yuyutei_collector.identity_evidence.official_image_url",
        return_value="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png",
    ):
        if tamper:
            with pytest.raises(ValueError):
                load_intent(session, NS(work_id=1, resume_cursor=cursor))
        else:
            assert load_intent(session, NS(work_id=1, resume_cursor=cursor))[1] is plan
