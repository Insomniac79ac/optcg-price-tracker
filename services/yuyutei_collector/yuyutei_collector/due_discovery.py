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
from sqlalchemy import select, update

from app.models import FreshnessWork, FreshnessAttempt, SourceDispatchBudget
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
from yuyutei_collector.models import YuyuteiDiscoveryRun

PARSER_VERSION = "yuyutei-recurring-discovery-v1"
ACTIVATION_GATE = "awaiting_five_successful_natural_raw_captures"


def activate_ready_scopes(session, source_id):
    """Open only explicitly armed discovery scopes after durable RAW success.

    Called at run start and after captures, so the first healthy natural run
    opens discovery without a manual job or a second scheduler. RAW identity
    quarantines are never selected by this update.
    """
    gated = (
        FreshnessWork.source_id == source_id,
        FreshnessWork.kind == "discovery",
        FreshnessWork.state == "blocked",
        FreshnessWork.last_failure == ACTIVATION_GATE,
    )
    if session.scalar(select(FreshnessWork.id).where(*gated).limit(1)) is None:
        return 0
    budget = session.scalar(
        select(SourceDispatchBudget).where(SourceDispatchBudget.source_id == source_id)
    )
    if not budget or not budget.enabled or budget.pause_reason or budget.paused_until:
        return 0
    successes = session.scalars(
        select(FreshnessAttempt.id)
        .join(FreshnessWork, FreshnessWork.id == FreshnessAttempt.work_id)
        .where(
            FreshnessWork.source_id == source_id,
            FreshnessWork.kind == "refresh",
            FreshnessAttempt.outcome == "captured",
            FreshnessAttempt.claimed_by.like("yuyutei-due-%"),
        )
        .limit(5)
    ).all()
    if len(successes) < 5:
        return 0
    result = session.execute(
        update(FreshnessWork).where(*gated).values(state="pending", last_failure=None)
    )
    print(
        f"RECURRING_DISCOVERY_GATE_OPENED source_id={source_id} scopes={result.rowcount}",
        flush=True,
    )
    return result.rowcount


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
    for product in enumeration.products:
        classification = classify_card_code(
            session,
            product.detected_card_code,
            source_product_count=counts.get(product.detected_card_code, 1),
            source_listing_complete=enumeration.enumeration_complete,
        )
        upsert_candidate(session, run.id, product, classification)
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
    attempt.result = CaptureResult(
        "completed",
        raw_snapshot_id=raw_snapshot_id,
        resume_cursor={
            "version": 1,
            "discovery_run_id": run.id,
            "enumeration_complete": enumeration.enumeration_complete,
        },
        next_due_at=attempt.clock() + timedelta(hours=24),
    )
    return SimpleNamespace(source_denied=False, stage="discovery_completed", reasons=[])


def run_discovery(session, claim, *, freshness):
    work = session.get(FreshnessWork, claim.work_id)
    slug = (work.scope_key or "").removeprefix("yuyu-category:")
    if work.scope_key != "yuyu-category:" + slug or not re.fullmatch(
        r"[a-z][a-z0-9]{1,15}", slug
    ):
        freshness.result = CaptureResult(
            "identity_refusal", failure="unsupported discovery scope"
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
