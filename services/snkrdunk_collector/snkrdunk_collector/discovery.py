"""Explicit admitted sitemap evidence; candidates only, no identity decisions."""

import base64
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import time
import unicodedata
from urllib.robotparser import RobotFileParser

from sqlalchemy import select
from app.models import FreshnessWork, SnkrdunkCandidate, Source, SourceCardMapping
from app.services.freshness_integration import CaptureResult, AdmissionStopped
from opcg_source_identity import canonical_source_listing_identity
from snkrdunk_collector.published_discovery import (
    INDEX,
    MAX_XML_BYTES,
    candidate_evidence,
    locations,
    neighbours,
)

PARSER_VERSION = "snkr-published-discovery-v1"
ROBOTS = "https://snkrdunk.com/robots.txt"
MAX_TOTAL_LOCATIONS = 400_000


@dataclass(frozen=True)
class RetainedDocument:
    url: str
    body: bytes
    raw_snapshot_id: int
    http_status: int


def intent(session, claim):
    cursor = claim.resume_cursor or {}
    work = session.get(FreshnessWork, claim.work_id)
    source = session.get(Source, work.source_id)
    if (
        source.name != "snkrdunk"
        or work.kind != "discovery"
        or work.attempt_count != 1
        or claim.scope_key != cursor.get("scope_key")
        or not claim.scope_key.startswith("snkr-published:")
        or cursor.get("version") != 1
        or cursor.get("explicit_published_discovery") is not True
        or work.source_card_mapping_id is not None
        or not 1 <= len(cursor.get("anchor_mapping_ids", [])) <= 12
        or len(set(cursor["anchor_mapping_ids"])) != len(cursor["anchor_mapping_ids"])
        or not 1 <= cursor.get("radius_start", 0) <= cursor.get("radius_end", 0) <= 48
        or not 1 <= cursor.get("max_products", 0) <= 20
        or not 1 <= work.estimated_request_cost <= 300
    ):
        raise ValueError("one bounded explicit published discovery claim required")
    mappings = session.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.id.in_(cursor["anchor_mapping_ids"]),
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.manual_verified.is_(True),
        )
    ).all()
    if len(mappings) != len(cursor["anchor_mapping_ids"]):
        raise ValueError("current approved manually verified anchors required")
    anchors = [
        canonical_source_listing_identity("snkrdunk", m.source_url) for m in mappings
    ]
    if not all(anchors) or len(set(anchors)) != len(anchors):
        raise ValueError("distinct established source identities required")
    return work, source, cursor, anchors


def consume(session, claim, *, freshness, fetch, settle=lambda: None):
    work, source, cursor, anchors = intent(session, claim)
    # Previously retained pages and candidate rows are evidence, not re-fetch targets.
    known = set(session.scalars(select(SnkrdunkCandidate.source_url)))
    exclusions = {canonical_source_listing_identity("snkrdunk", u) for u in known}
    exclusions |= set(anchors)
    previous = session.scalars(
        select(FreshnessWork).where(
            FreshnessWork.source_id == source.id,
            FreshnessWork.scope_key.like("snkr-published:%"),
        )
    ).all()
    for row in previous:
        exclusions.update((row.resume_cursor or {}).get("inspected_identities", []))
    robots_doc = fetch(ROBOTS)
    if robots_doc.http_status != 200:
        raise ValueError("current retained robots policy required")
    policy = RobotFileParser()
    policy.parse(robots_doc.body.decode("utf-8").splitlines())
    if not policy.can_fetch("*", INDEX):
        raise ValueError("published sitemap denied by source robots policy")
    index = fetch(INDEX)
    if index.http_status != 200:
        raise ValueError("current complete published index required")
    shard_urls = locations(index.body, index=True)
    shards = {}
    documents = [{"url": index.url, "raw_snapshot_id": index.raw_snapshot_id}]
    total = 0
    for url in shard_urls:
        if not policy.can_fetch("*", url):
            raise ValueError("published shard denied by source robots policy")
        document = fetch(url)
        if document.http_status != 200:
            raise ValueError("complete advertised shard response required")
        shards[url] = locations(document.body, index=False)
        total += len(shards[url])
        if total > MAX_TOTAL_LOCATIONS:
            raise ValueError("aggregate published URL bound exceeded")
        documents.append({"url": url, "raw_snapshot_id": document.raw_snapshot_id})
    targets = neighbours(
        shards,
        anchors,
        exclusions,
        radius_start=cursor["radius_start"],
        radius_end=cursor["radius_end"],
        limit=cursor["max_products"],
    )
    candidates = []
    inspected = []
    for target in targets:
        if not policy.can_fetch("*", target.source_url):
            raise ValueError("published product denied by source robots policy")
        document = fetch(target.source_url)
        inspected.append(target.identity)
        documents.append(
            {
                "url": target.source_url,
                "raw_snapshot_id": document.raw_snapshot_id,
                "shard_url": target.shard_url,
                "offset": target.offset,
                "anchor_identity": target.anchor_identity,
                "radius": target.radius,
                "http_status": document.http_status,
            }
        )
        if document.http_status in (404, 410):
            continue  # discovery absence only; never RAW no-listing credit
        if document.http_status != 200:
            raise ValueError("published product response incomplete")
        if len(document.body) > 2 * 1024**2:
            raise ValueError("bounded complete product document required")
        evidence = candidate_evidence(target.source_url, document.body.decode("utf-8"))
        if evidence is not None:
            if (
                not evidence.title
                or len(evidence.title) > 512
                or len(evidence.image_url or "") > 1024
            ):
                raise ValueError("candidate metadata length bound exceeded")
            candidates.append(evidence)
    # Browser callbacks may commit a source pause. Settle them before any
    # candidate insert, so a late denial cannot commit unpublished candidates.
    settle()
    freshness.begin_result()
    inserted = []
    # Fence before DB writes; preserve every pre-existing candidate and decision.
    for evidence in candidates:
        if session.scalar(
            select(SnkrdunkCandidate.id).where(
                SnkrdunkCandidate.source_url == evidence.source_url
            )
        ):
            continue
        row = SnkrdunkCandidate(
            source_url=evidence.source_url,
            title=evidence.title,
            image_url=evidence.image_url,
            raw_text=evidence.raw_text,
            normalized_title=" ".join(
                unicodedata.normalize("NFKC", evidence.title).split()
            ),
            detected_card_code=evidence.card_code,
            detected_set_code=evidence.resolved_product_code,
            detected_rarity=evidence.rarity_token,
            detected_variant=evidence.asset_variant,
            match_status="unmatched",
        )
        session.add(row)
        session.flush()
        inserted.append(row.id)
    result_cursor = {
        **cursor,
        "inspected_identities": inspected,
        "documents": documents,
        "new_candidate_ids": inserted,
        "published_urls_observed": total,
        "price_writes": 0,
        "mapping_writes": 0,
    }
    return CaptureResult(
        "completed",
        raw_snapshot_id=index.raw_snapshot_id,
        resume_cursor=result_cursor,
        next_due_at=freshness.clock() + timedelta(days=36500),
    )


def retained_fetch(page, freshness, source_id, url):
    from bs4 import BeautifulSoup
    from snkrdunk_collector.browser import classify_page, log_event

    freshness.admit()
    response = page.context.request.get(
        url, max_redirects=0, max_retries=0, timeout=20000
    )
    try:
        body = response.body()
        status = response.status
        envelope = json.dumps(
            {
                "encoding": "base64",
                "body": base64.b64encode(body).decode(),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            },
            separators=(",", ":"),
        )
        raw_id = freshness.snapshot(
            source_id, url, {"http_status": status, "html": envelope}, PARSER_VERSION
        )
    finally:
        response.dispose()
    freshness.raw_snapshot_id = raw_id
    freshness.record_http(status)
    if len(body) > MAX_XML_BYTES:
        raise ValueError("retained public response exceeds parser byte bound")
    text_body = (
        body.decode("utf-8", errors="replace")
        if not body.startswith(b"\x1f\x8b")
        else ""
    )
    soup = (
        BeautifulSoup(text_body, "html.parser")
        if "<html" in text_body.lower()
        else None
    )
    title = soup.title.get_text(strip=True) if soup and soup.title else ""
    classification, _ = classify_page(status, text_body, title)
    if classification in ("static_403", "static_429", "challenge_or_captcha"):
        log_event(
            "published_discovery_denied",
            work_id=freshness.claim.work_id,
            request_role="required_published_document",
            evidence_critical=True,
            http_status=status,
            classification=classification,
        )
        freshness.deny()
    freshness.check()
    time.sleep(1.5)
    return RetainedDocument(url, body, raw_id, status)


def run_discovery(session, claim, *, freshness):
    from snkrdunk_collector.run_lock import LockLost
    from playwright.sync_api import sync_playwright
    from snkrdunk_collector.browser import (
        DESKTOP_CHROME_UA,
        DESKTOP_VIEWPORT,
        DESKTOP_ACCEPT_LANGUAGE,
        HOMEPAGE_URL,
        goto_and_capture,
        deadline,
    )
    from snkrdunk_collector.config import settings

    try:
        work, source, _, _ = intent(session, claim)
        with deadline(settings.TOTAL_RUN_TIMEOUT_S, "published_discovery"):
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
                )
                context = browser.new_context(
                    user_agent=DESKTOP_CHROME_UA,
                    viewport=DESKTOP_VIEWPORT,
                    locale="ja-JP",
                    extra_http_headers={"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
                    service_workers="block",
                )
                freshness.install_browser(context)
                page = context.new_page()
                try:
                    homepage = goto_and_capture(
                        page,
                        HOMEPAGE_URL,
                        before_parse=lambda step: freshness.snapshot(
                            source.id, HOMEPAGE_URL, step, PARSER_VERSION
                        ),
                    )
                    if homepage.get("classification") in (
                        "static_403",
                        "static_429",
                        "challenge_or_captcha",
                    ):
                        freshness.deny()
                    freshness.check()
                    if (
                        homepage.get("http_status") != 200
                        or homepage.get("classification") != "normal_page"
                    ):
                        raise ValueError("normal existing homepage session required")
                    result = consume(
                        session,
                        claim,
                        freshness=freshness,
                        fetch=lambda url: retained_fetch(
                            page, freshness, source.id, url
                        ),
                        settle=lambda: freshness.settle_browser(page),
                    )
                    freshness.result = result
                    return result
                finally:
                    try:
                        freshness.settle_browser(page)
                    finally:
                        context.close()
                        browser.close()
    except (AdmissionStopped, LockLost):
        raise
    except Exception as exc:
        session.rollback()
        result = CaptureResult(
            (
                "source_denial"
                if freshness.denied
                else (
                    "identity_refusal"
                    if isinstance(exc, ValueError)
                    else "transient_failure"
                )
            ),
            failure=f"published_discovery_refused:{type(exc).__name__}",
            raw_snapshot_id=freshness.raw_snapshot_id,
            next_due_at=freshness.clock() + timedelta(days=36500),
        )
        freshness.result = result
        return result
