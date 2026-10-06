"""Metered, explicit product/artwork evidence capture. Never approves identity."""

import base64
import hashlib
import io
import json
import re
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

from sqlalchemy import select
from playwright.sync_api import sync_playwright
from PIL import Image
from opcg_source_identity import yuyutei_listing_identity
from app.models import CardPrint, FreshnessWork, YuyuteiCandidate
from app.services.freshness_integration import CaptureResult, AdmissionStopped
from app.services.source_mapping_proposals import resolve_current_candidate_proposal
from app.services.official_asset_variant import parse_official_asset_variant
from app.services.identity_evidence_scope import identity_evidence_scope
from yuyutei_collector.browser import (
    HOMEPAGE_URL,
    HOMEPAGE_EXPECTED_MARKERS,
    classify_capture,
    deadline,
    goto_and_capture_raw,
    homepage_session_ok,
)
from yuyutei_collector.config import settings
from yuyutei_collector.extractor import extract_with_agreement

PARSER_VERSION = "yuyu-identity-evidence-v1"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SIBLINGS = 12


def product_image_url(url, candidate):
    """Accept the published asset for this exact source natural key only."""
    if not isinstance(url, str):
        raise ValueError("published product image required")
    parsed = urlparse(url)
    match = re.fullmatch(
        r"/opc/(?:front|100_140|200_280)/([a-z0-9-]+)/(\d+)\.(?:jpg|png|webp)",
        parsed.path,
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc != "card.yuyu-tei.jp"
        or parsed.query
        or parsed.fragment
        or not match
        or match.groups() != (candidate.set_slug, candidate.product_id)
    ):
        raise ValueError("published image does not name this exact product")
    return url


def official_image_url(print_row, card_code):
    parsed = urlparse(print_row.image_url or "")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.onepiece-cardgame.com"
        or not parsed.path.startswith("/images/cardlist/card/")
        or parsed.fragment
        or (parsed.query and not re.fullmatch(r"\d{6,8}", parsed.query))
        or parse_official_asset_variant(print_row.image_url, card_code)
        != print_row.official_asset_variant
    ):
        raise ValueError("authoritative official asset URL required")
    return print_row.image_url


def load_intent(session, claim):
    """Fail closed before I/O on changed candidate/catalogue evidence."""
    cursor = claim.resume_cursor or {}
    work = session.get(FreshnessWork, claim.work_id)
    candidate_id = cursor.get("candidate_id")
    expected_scope = identity_evidence_scope(
        candidate_id, cursor.get("evidence_digest"), cursor.get("version", 1)
    )
    if (
        type(candidate_id) is not int
        or candidate_id <= 0
        or work.kind != "discovery"
        or work.attempt_count != 1
        or work.scope_key != expected_scope
        or cursor.get("explicit_identity_capture") is not True
    ):
        raise ValueError("one explicitly planned capture required")
    candidate = session.get(YuyuteiCandidate, candidate_id)
    plan = resolve_current_candidate_proposal(
        session, source_name="yuyutei", candidate_id=candidate_id
    )
    if (
        candidate is None
        or plan is None
        or plan.resolution_status != "ambiguous"
        or plan.evidence_digest != cursor.get("evidence_digest")
        or plan.release_product_id != cursor.get("release_product_id")
        or plan.source_id != work.source_id
        or yuyutei_listing_identity(candidate.source_url)
        != (candidate.set_slug, candidate.product_id)
    ):
        raise ValueError("current ambiguous release/family evidence required")
    ids = sorted(a.card_print_id for a in plan.alternatives)
    if ids != cursor.get("considered_print_ids") or not 2 <= len(ids) <= MAX_SIBLINGS:
        raise ValueError("complete bounded sibling set required")
    prints = session.scalars(
        select(CardPrint).where(CardPrint.id.in_(ids)).order_by(CardPrint.id)
    ).all()
    if len(prints) != len(ids):
        raise ValueError("official sibling disappeared")
    urls = {p.id: official_image_url(p, candidate.detected_card_code) for p in prints}
    return candidate, plan, prints, urls


def retain_image(freshness, source_id, url, body):
    """Persist full source bytes before any image decoding/comparison."""
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("bounded nonempty source image required")
    raw = json.dumps(
        {
            "encoding": "base64",
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body": base64.b64encode(body).decode("ascii"),
        },
        separators=(",", ":"),
    )
    snapshot = freshness.snapshot(
        source_id, url, {"http_status": 200, "html": raw}, PARSER_VERSION
    )
    # Structural decoding validates a usable artifact, never a CardPrint.
    # The complete original response is already durable if decoding fails.
    try:
        with Image.open(io.BytesIO(body)) as image:
            if (
                image.format not in {"PNG", "JPEG", "WEBP"}
                or image.width * image.height > 16000000
            ):
                raise ValueError("bounded card image required")
            image.verify()
    except Exception as exc:
        raise ValueError("retained image is unusable") from exc
    return snapshot


def capture_pages(session, claim, freshness, page, candidate, plan, prints, urls):
    """One ordinary warm-up/product navigation and explicit serial assets."""

    def capture(url, markers=None):
        step = goto_and_capture_raw(page, url)
        if "html" not in step:
            raise RuntimeError("required page unavailable")
        snapshot = freshness.snapshot(plan.source_id, url, step, PARSER_VERSION)
        freshness.raw_snapshot_id = snapshot
        classified = classify_capture(step, markers)
        if classified.get("classification") in {
            "static_403",
            "static_429",
            "challenge_or_captcha",
        }:
            freshness.deny()
            freshness.check()
        if step.get("http_status") != 200:
            raise RuntimeError("required successful product capture unavailable")
        return step, classified, snapshot

    _, warmup, _ = capture(HOMEPAGE_URL, HOMEPAGE_EXPECTED_MARKERS)
    if not homepage_session_ok(warmup):
        raise RuntimeError("ordinary homepage session unavailable")
    time.sleep(max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000)
    step, _, product_snapshot = capture(candidate.source_url)
    if yuyutei_listing_identity(step.get("final_url")) != (
        candidate.set_slug,
        candidate.product_id,
    ):
        raise ValueError("product navigation changed natural key")
    extraction = extract_with_agreement(
        step["html"],
        candidate.source_url,
        candidate.detected_card_code,
        expected_treatment=None,
    )
    if extraction["extracted"].get("card_code") != candidate.detected_card_code or any(
        reason.startswith("card_code_") for reason in extraction["fail_reasons"]
    ):
        raise ValueError("fresh product code conflicts with candidate")
    image_url = product_image_url(
        extraction["extracted"].get("product_image_url"), candidate
    )
    image_snapshot = retain_image(
        freshness, plan.source_id, image_url, freshness.request_bytes(page, image_url)
    )
    official = []
    for print_row in prints:
        time.sleep(max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000)
        url = urls[print_row.id]
        snapshot = retain_image(
            freshness, plan.source_id, url, freshness.request_bytes(page, url)
        )
        official.append(
            {
                "card_print_id": print_row.id,
                "raw_snapshot_id": snapshot,
                "official_asset_variant": print_row.official_asset_variant,
                "artwork_key": print_row.artwork_key,
            }
        )
    freshness.begin_result()
    freshness.result = CaptureResult(
        "completed",
        raw_snapshot_id=product_snapshot,
        resume_cursor={
            **claim.resume_cursor,
            "source_product_snapshot_id": product_snapshot,
            "source_image_snapshot_id": image_snapshot,
            "official_images": official,
            "identity_status": "unresolved; retained artwork evidence only",
        },
        next_due_at=freshness.clock() + timedelta(days=36500),
    )
    return SimpleNamespace(
        stage="identity_evidence_captured", source_denied=False, reasons=[]
    )


def run_identity_evidence(session, claim, *, freshness):
    try:
        candidate, plan, prints, urls = load_intent(session, claim)
        with deadline(settings.TOTAL_RUN_TIMEOUT_S, "identity_evidence"):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
                )
                try:
                    context = browser.new_context(service_workers="block")
                    freshness.install_browser(context)
                    return capture_pages(
                        session,
                        claim,
                        freshness,
                        context.new_page(),
                        candidate,
                        plan,
                        prints,
                        urls,
                    )
                finally:
                    browser.close()
    except AdmissionStopped:
        raise
    except Exception as exc:
        session.rollback()
        freshness.check()
        freshness.result = CaptureResult(
            "identity_refusal" if isinstance(exc, ValueError) else "transient_failure",
            raw_snapshot_id=freshness.raw_snapshot_id,
            failure=type(exc).__name__,
        )
        return SimpleNamespace(
            stage="identity_evidence_failed", source_denied=False, reasons=[]
        )
