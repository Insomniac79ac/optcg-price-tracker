"""Validate positive visual reviews against immutable retained physical evidence.

This validates an explicit, attributable review; it never ranks or selects
images. Same-art physical twins are refused even when a review names one.
"""

import base64
import hashlib
import json
import io
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from app.models import FreshnessWork, FreshnessAttempt, RawSnapshot
from app.services.yuyutei_urls import listing_identity
from app.services.official_asset_variant import parse_official_asset_variant

REGISTRY = Path(__file__).with_name("evidence") / "positive_physical_artwork.json"


def registry():
    data = json.loads(REGISTRY.read_text())
    if (
        data.get("schema_version") != 1
        or data.get("target") != "staging"
        or len(data.get("proofs", [])) > 300
    ):
        raise ValueError("unrecognized bounded physical evidence registry")
    return data["proofs"]


def image_body(row, expected):
    from PIL import Image

    if row.http_status != 200 or row.parser_version != "yuyu-identity-evidence-v1":
        raise ValueError("retained successful identity image required")
    if hashlib.sha256(row.raw_content.encode()).hexdigest() != row.content_hash:
        raise ValueError("retained image envelope changed")
    envelope = json.loads(row.raw_content)
    body = base64.b64decode(envelope["body"], validate=True)
    digest = hashlib.sha256(body).hexdigest()
    if (
        not 0 < len(body) <= 2 * 1024 * 1024
        or envelope.get("encoding") != "base64"
        or digest != envelope.get("body_sha256")
        or digest != expected
    ):
        raise ValueError("retained original image bytes changed")
    with Image.open(io.BytesIO(body)) as image:
        if (
            image.format not in {"PNG", "JPEG", "WEBP"}
            or image.width * image.height > 16000000
        ):
            raise ValueError("usable bounded original image required")
        image.load()
        pixels = hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()
    return digest, pixels


def validate(session, plan, siblings, proof):
    """Fail closed on stale corpus, lineage, review or same-art ambiguity."""
    if (
        plan.source_name != "yuyutei"
        or plan.resolution_status != "ambiguous"
        or proof.get("source_candidate_id") != plan.source_candidate_id
        or proof.get("source_url") != plan.source_url
        or proof.get("baseline_evidence_digest") != plan.evidence_digest
        or proof.get("release_product_id") != plan.release_product_id
        or proof.get("language") != "jp"
        or proof.get("review_method")
        != "codex_visual_review_of_unique_full_physical_artwork"
        or not proof.get("reviewed_at")
        or not proof.get("actor", "").startswith("codex:")
        or not proof.get("positive_physical_basis")
        or proof.get("selected_card_print_id") not in {p.id for p in siblings}
    ):
        raise ValueError("current attributable positive physical review required")
    reviewed_at = datetime.fromisoformat(proof["reviewed_at"])
    if reviewed_at.utcoffset() != timezone.utc.utcoffset(
        reviewed_at
    ) or reviewed_at > datetime.now(timezone.utc):
        raise ValueError("review timestamp must be UTC")
    ids = sorted(p.id for p in siblings)
    if ids != proof.get("considered_print_ids") or not 2 <= len(ids) <= 12:
        raise ValueError("complete authoritative physical sibling set required")
    if set(proof.get("excluded_sibling_basis", {})) != {
        str(i) for i in ids if i != proof["selected_card_print_id"]
    } or not all(proof["excluded_sibling_basis"].values()):
        raise ValueError("explicit physical exclusion for every other sibling required")
    if any(
        p.language != "jp"
        or p.release_product_id != plan.release_product_id
        or not p.is_active
        or p.verification_status != "verified"
        for p in siblings
    ):
        raise ValueError("physical catalogue identity changed")
    work = session.get(FreshnessWork, proof["work_id"])
    if (
        work is None
        or work.source_id != plan.source_id
        or work.kind != "discovery"
        or work.scope_key != f"yuyu-identity:{plan.source_candidate_id}"
        or work.attempt_count != 1
        or work.last_outcome != "completed"
    ):
        raise ValueError("one successful metered evidence capture required")
    cursor = work.resume_cursor or {}
    if (
        cursor.get("evidence_digest") != plan.evidence_digest
        or cursor.get("candidate_id") != plan.source_candidate_id
        or cursor.get("release_product_id") != plan.release_product_id
        or cursor.get("considered_print_ids") != ids
        or cursor.get("source_product_snapshot_id")
        != proof["source_product_snapshot_id"]
        or cursor.get("source_image_snapshot_id") != proof["source_image_snapshot_id"]
    ):
        raise ValueError("review and capture lineage differ")
    attempts = session.scalars(
        select(FreshnessAttempt).where(FreshnessAttempt.work_id == work.id)
    ).all()
    if (
        len(attempts) != 1
        or attempts[0].outcome != "completed"
        or attempts[0].raw_snapshot_id != proof["source_product_snapshot_id"]
        or not 0 < attempts[0].actual_request_cost <= 100
    ):
        raise ValueError("bounded natural capture receipt required")
    product = session.get(RawSnapshot, proof["source_product_snapshot_id"])
    source = session.get(RawSnapshot, proof["source_image_snapshot_id"])
    if (
        product is None
        or source is None
        or product.source_id != plan.source_id
        or source.source_id != plan.source_id
        or product.http_status != 200
        or product.source_url != plan.source_url
        or product.content_hash != proof["source_product_content_hash"]
        or product.parser_version != "yuyu-identity-evidence-v1"
        or hashlib.sha256(product.raw_content.encode()).hexdigest()
        != product.content_hash
        or source.source_url != proof["source_image_url"]
        or source.source_url not in product.raw_content
    ):
        raise ValueError("retained exact published source product required")
    slug, product_id = listing_identity(plan.source_url)
    if (
        source.source_url
        != f"https://card.yuyu-tei.jp/opc/front/{slug}/{product_id}.jpg"
    ):
        raise ValueError("source asset natural identity changed")
    image_body(source, proof["source_body_sha256"])
    capture_rows = cursor.get("official_images", [])
    review_rows = proof.get("official_images", [])
    captured = {p["card_print_id"]: p for p in capture_rows}
    recorded = {p["card_print_id"]: p for p in review_rows}
    if (
        len(capture_rows) != len(ids)
        or len(review_rows) != len(ids)
        or set(captured) != set(ids)
        or set(recorded) != set(ids)
    ):
        raise ValueError("complete retained official images required")
    hashes = []
    for p in siblings:
        expected = recorded[p.id]
        snapshot = session.get(RawSnapshot, expected["raw_snapshot_id"])
        if (
            snapshot is None
            or snapshot.source_id != plan.source_id
            or captured[p.id]["raw_snapshot_id"] != snapshot.id
            or snapshot.source_url != p.image_url
            or not p.image_url.startswith(
                "https://www.onepiece-cardgame.com/images/cardlist/card/"
            )
            or p.official_asset_variant != expected["official_asset_variant"]
            or parse_official_asset_variant(p.image_url, plan.card_code)
            != p.official_asset_variant
            or p.artwork_key != expected["body_sha256"]
        ):
            raise ValueError("authoritative official physical asset changed")
        hashes.append(image_body(snapshot, expected["body_sha256"])[1])
    if len(set(hashes)) != len(hashes):
        raise ValueError("same-art physical twins remain ambiguous")
    return hashlib.sha256(
        json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def resolve(session, plan, siblings):
    from app.env import get_app_env

    if get_app_env() != "staging":
        return None
    try:
        matches = [
            p
            for p in registry()
            if p.get("source_candidate_id") == plan.source_candidate_id
        ]
        if len(matches) != 1:
            return None
        digest = validate(session, plan, siblings, matches[0])
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        return None  # stale/unproven physical evidence retains ambiguity
    return matches[0]["selected_card_print_id"], digest, matches[0]["actor"]
