"""Bounded recurring listing discovery inside the existing serial shard worker.

No approval or price writer. Candidate evidence and the discovery checkpoint
commit with the fenced queue result. No work is admitted merely by importing
this adapter: a discovery scope must be explicitly planned.
"""

from datetime import timedelta
from types import SimpleNamespace
import re
import time

from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.models import FreshnessWork
from app.services.freshness_integration import CaptureResult, AdmissionStopped
from yuyutei_collector.browser import (
    HOMEPAGE_URL,
    HOMEPAGE_EXPECTED_MARKERS,
    classify_capture,
    deadline,
    goto_and_capture_raw,
    homepage_session_ok,
)
from yuyutei_collector.config import settings
from yuyutei_collector.discovery import (
    enumerate_slug,
    own_series_code_counts,
    upsert_candidate,
    _slug_metrics,
)
from yuyutei_collector.discovery_match import classify_card_code
from yuyutei_collector.discovery_probe import SourceDenied
from yuyutei_collector.discovery_scope import validated_discovery_url
from yuyutei_collector.models import YuyuteiDiscoveryRun

PARSER_VERSION = "yuyutei-recurring-discovery-v1"


def persist_enumeration(session, claim, attempt, enumeration, raw_snapshot_id):
    """No intermediate commit: candidate rows and cursor share result fencing."""
    attempt.begin_result()
    run = YuyuteiDiscoveryRun(
        status="completed", requested_set_slugs=[enumeration.slug]
    )
    session.add(run)
    session.flush()
    counts = own_series_code_counts(enumeration)
    statuses = []
    candidate_ids = []
    new_candidates = 0
    for product in enumeration.products:
        classification = classify_card_code(
            session,
            product.detected_card_code,
            source_product_count=counts.get(product.detected_card_code, 1),
            source_listing_complete=enumeration.enumeration_complete,
        )
        candidate, is_new = upsert_candidate(session, run.id, product, classification)
        candidate_ids.append(candidate.id)
        new_candidates += int(is_new)
        statuses.append(classification.match_status)
    metrics = _slug_metrics(enumeration, statuses, len(statuses))
    run.finished_at = attempt.clock()
    run.per_slug_metrics_json = {enumeration.slug: metrics}
    for field, key in (
        ("pages_fetched", "pages_fetched"),
        ("products_seen", "own_series_products"),
        ("candidates_written", "candidates_written"),
        ("foreign_series_filtered", "foreign_series_filtered"),
        ("duplicate_products", "duplicate_products"),
        ("unparseable_codes", "unparseable_codes"),
    ):
        setattr(run, field, metrics[key])
    if not enumeration.enumeration_complete:
        run.stopped_reason = "bounded_incomplete_enumeration_no_exact_inference"
    session.flush()
    from app.services.discovery_proposal_refresh import refresh_discovery_proposals

    proposals = refresh_discovery_proposals(session, "yuyutei", candidate_ids)
    from app.services.freshness_queue import plan_discovery_scope

    work = session.get(FreshnessWork, claim.work_id)
    discovery_url = (work.resume_cursor or {}).get("discovery_url")
    new_scopes = []
    for slug, url in enumeration.advertised_scopes.items():
        scope_key = "yuyu-category:" + slug
        if (
            session.scalar(
                select(FreshnessWork.id).where(
                    FreshnessWork.source_id == work.source_id,
                    FreshnessWork.kind == "discovery",
                    FreshnessWork.scope_key == scope_key,
                )
            )
            is not None
        ):
            continue
        scope = plan_discovery_scope(
            session,
            work.source_id,
            scope_key,
            due_at=attempt.clock(),
            estimated_request_cost=work.estimated_request_cost,
        )
        scope.resume_cursor = {
            "version": 1,
            "discovery_url": url,
            "advertised_snapshot_id": raw_snapshot_id,
        }
        new_scopes.append(slug)
    # Keep metrics immutable to SQLAlchemy's JSON tracking and preserve the
    # completed enumeration evidence used by the resolver before refreshing.
    run.per_slug_metrics_json = {
        enumeration.slug: {
            **metrics,
            "new_candidates": new_candidates,
            "refreshed_candidates": len(candidate_ids) - new_candidates,
            "proposal_refresh": proposals,
            "new_advertised_scopes": new_scopes,
        }
    }
    attempt.result = CaptureResult(
        "completed",
        raw_snapshot_id=raw_snapshot_id,
        resume_cursor={
            "version": 1,
            "discovery_run_id": run.id,
            "enumeration_complete": enumeration.enumeration_complete,
            "proposal_refresh": proposals,
            "discovery_url": discovery_url,
        },
        next_due_at=attempt.clock() + timedelta(hours=24),
    )
    return SimpleNamespace(source_denied=False, stage="discovery_completed", reasons=[])


def run_discovery(session, claim, *, freshness):
    work = session.get(FreshnessWork, claim.work_id)
    slug = (work.scope_key or "").removeprefix("yuyu-category:")
    if work.scope_key != "yuyu-category:" + slug or not re.fullmatch(
        r"[a-z][a-z0-9-]{1,31}", slug
    ):
        freshness.result = CaptureResult(
            "identity_refusal", failure="unsupported discovery scope"
        )
        return SimpleNamespace(
            source_denied=False, stage="validation_failed", reasons=[]
        )
    try:
        start_url = validated_discovery_url(
            slug, (work.resume_cursor or {}).get("discovery_url")
        )
    except ValueError:
        start_url = None
    if start_url is None:
        freshness.result = CaptureResult(
            "identity_refusal", failure="unproven discovery URL"
        )
        return SimpleNamespace(
            source_denied=False, stage="validation_failed", reasons=[]
        )
    source_id = work.source_id
    last_snapshot = None

    def evidence(url, step):
        nonlocal last_snapshot
        last_snapshot = freshness.snapshot(source_id, url, step, PARSER_VERSION)
        classified = classify_capture(step)
        if classified.get("classification") in {
            "static_403",
            "static_429",
            "challenge_or_captcha",
        }:
            freshness.deny()
            freshness.check()
        freshness.check()

        if not 200 <= (step.get("http_status") or 0) < 300:
            raise RuntimeError(f"discovery_http_status:{step.get('http_status')}")

    try:
        with deadline(settings.TOTAL_RUN_TIMEOUT_S, "recurring_discovery"):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000
                )
                try:
                    context = browser.new_context(service_workers="block")
                    freshness.install_browser(context)
                    page = context.new_page()
                    warmup = goto_and_capture_raw(page, HOMEPAGE_URL)
                    if "html" not in warmup:
                        raise RuntimeError("discovery homepage capture failed")
                    evidence(HOMEPAGE_URL, warmup)
                    if not homepage_session_ok(
                        classify_capture(warmup, HOMEPAGE_EXPECTED_MARKERS)
                    ):
                        raise RuntimeError("discovery homepage session unavailable")
                    time.sleep(settings.YUYUTEI_REQUEST_DELAY_MS / 1000)
                    enumeration = enumerate_slug(
                        page,
                        slug,
                        max_products=500,
                        max_pages=3,
                        timeout_s=90,
                        evidence_sink=evidence,
                        start_url=start_url,
                    )
                finally:
                    browser.close()
    except AdmissionStopped:
        raise
    except SourceDenied:
        freshness.deny()
        freshness.check()
    except Exception as exc:
        session.rollback()
        freshness.result = CaptureResult(
            "transient_failure",
            raw_snapshot_id=last_snapshot,
            failure=f"discovery:{type(exc).__name__}:{exc}"[:500],
        )
        return SimpleNamespace(
            source_denied=False, stage="operational_error", reasons=[]
        )
    return persist_enumeration(session, claim, freshness, enumeration, last_snapshot)
