"""CLI entrypoints:

    python -m yuyutei_collector.collect --mapping-id <id>
    python -m yuyutei_collector.collect --approved-mappings

Runs, collects, and exits - no server, no scheduling (Railway Cron calls
this directly once configured). Exactly one homepage request, and only if
that is a genuine normal HTTP 200, exactly one product request per mapping.
No retries after 403/429/challenge/CAPTCHA or an extraction validation
failure. Writes at most one new price_observations row per mapping per
invocation, and only on full success - see writer.py.

`--approved-mappings` (see yuyutei_collector.batch) discovers every eligible
approved Yuyu-Tei mapping from the database and processes them one at a
time, sequentially, stopping the whole batch immediately on a source-wide
denial signal (403/429/CAPTCHA/challenge) - see that module's docstring for
the full batch-safety contract.
"""

import argparse
import sys
from dataclasses import dataclass, field
from importlib.metadata import version as pkg_version

from playwright.sync_api import sync_playwright

from yuyutei_collector.browser import (
    HOMEPAGE_EXPECTED_MARKERS,
    HOMEPAGE_URL,
    DeadlineExceeded,
    deadline,
    goto_and_capture,
    log_event,
)
from yuyutei_collector.config import settings
from yuyutei_collector.db import SessionLocal
from yuyutei_collector.extractor import EXPECTED_TREATMENT, extract_with_agreement
from yuyutei_collector.models import CardPrint, Source, SourceCardMapping
from yuyutei_collector.writer import validate_and_write_observation

PARSER_VERSION = "yuyutei-collector-v3"

# A page classified as one of these is a source-wide denial signal, not a
# per-mapping data problem - see extractor.classify_page. Both an HTTP 403
# and an HTTP 429/CAPTCHA/challenge page collapse into these two
# classifications; there is no finer-grained distinction available from a
# single page fetch. Anything else (navigation_error, other_status_NNN) is
# treated as a mapping-level/operational issue, not a source-wide denial -
# it does not, on its own, establish that Yuyu-Tei is blocking this client.
SOURCE_DENIAL_CLASSIFICATIONS = frozenset({"static_403", "challenge_or_captcha"})


@dataclass
class MappingOutcome:
    """Structured result of one run_one_mapping_detailed call - richer than
    the plain int exit code run_one_mapping() returns, so batch orchestration
    (see yuyutei_collector.batch) can distinguish a written observation from
    a mapping-level validation failure from a source-wide denial without
    re-parsing log lines."""

    mapping_id: int
    stage: str
    written: bool = False
    source_denied: bool = False
    classification: str | None = None
    reasons: list[str] = field(default_factory=list)
    observation_id: int | None = None
    raw_snapshot_id: int | None = None
    card_id: int | None = None
    card_print_id: int | None = None
    source_card_mapping_id: int | None = None
    price_jpy: int | None = None
    stock_status: str | None = None
    observed_at: str | None = None


# Stages that map to a nonzero single-mapping CLI exit code - see
# run_one_mapping(). Every other stage (no_extraction_attempted,
# validated_only, validation_failed, written) is a clean, no-crash outcome
# from the single-mapping CLI's point of view, even when no observation was
# written.
_NONZERO_EXIT_STAGES = frozenset({"mapping_load_failed", "operational_error"})


def _load_mapping(session, mapping_id: int) -> tuple[SourceCardMapping | None, Source | None, list[str]]:
    reasons: list[str] = []
    mapping = session.get(SourceCardMapping, mapping_id)
    if mapping is None:
        return None, None, [f"mapping_not_found:{mapping_id}"]
    source = session.get(Source, mapping.source_id)
    if source is None:
        reasons.append(f"source_not_found:{mapping.source_id}")
    if mapping.source_url is None:
        reasons.append("mapping_missing_source_url")
    return mapping, source, reasons


def run_one_mapping_detailed(
    session,
    mapping_id: int,
    validate_only: bool = False,
    batch_run_id: str | None = None,
) -> MappingOutcome:
    """Does the actual navigation/extraction/write work for one mapping and
    returns a structured MappingOutcome. Takes an already-open `session`
    (rather than opening/closing its own, as run_one_mapping did) so batch
    mode can reuse one session across mappings without each mapping's
    rollback/commit touching a different connection."""
    mapping, source, load_reasons = _load_mapping(session, mapping_id)
    if load_reasons:
        log_event(
            "mapping_load_failed", mapping_id=mapping_id, reasons=load_reasons, batch_run_id=batch_run_id
        )
        return MappingOutcome(mapping_id=mapping_id, stage="mapping_load_failed", reasons=load_reasons)

    expected_card_code = mapping.source_card_id
    expected_treatment = EXPECTED_TREATMENT
    if mapping.card_print_id is not None:
        card_print = session.get(CardPrint, mapping.card_print_id)
        if card_print is not None:
            expected_treatment = card_print.treatment

    # Every Yuyu-Tei product page displays its own card code somewhere in
    # the visible text (see extractor._find_card_code_element) - using the
    # mapping's own source_card_id as the "expected content present" marker
    # is generic across every card, unlike a hardcoded name/word.
    product_expected_markers = [expected_card_code]

    log_event(
        "collection_start",
        mapping_id=mapping.id,
        source=source.name if source else None,
        source_url=mapping.source_url,
        expected_card_code=expected_card_code,
        expected_treatment=expected_treatment,
        card_print_id=mapping.card_print_id,
        validate_only=validate_only,
        batch_run_id=batch_run_id,
    )

    result_holder: dict = {
        "extraction": None,
        "classification": None,
        "http_status": None,
        "html": None,
        "observed_classification": None,
    }

    try:
        with deadline(settings.TOTAL_RUN_TIMEOUT_S, "total_run"):
            with sync_playwright() as p:
                log_event("playwright_ready", playwright_version=pkg_version("playwright"))
                with deadline(settings.BROWSER_LAUNCH_TIMEOUT_S, "browser_launch"):
                    browser = p.chromium.launch(headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000)
                    context = browser.new_context()
                    page = context.new_page()

                with deadline(settings.HOMEPAGE_NAV_TIMEOUT_S, "homepage_navigation"):
                    homepage_step = goto_and_capture(page, HOMEPAGE_URL, HOMEPAGE_EXPECTED_MARKERS)
                log_event(
                    "homepage_result",
                    mapping_id=mapping.id,
                    http_status=homepage_step.get("http_status"),
                    classification=homepage_step.get("classification"),
                    error=homepage_step.get("error"),
                    batch_run_id=batch_run_id,
                )

                homepage_ok = (
                    "error" not in homepage_step
                    and homepage_step.get("http_status") == 200
                    and homepage_step.get("classification") == "normal_product"
                )

                if not homepage_ok:
                    result_holder["observed_classification"] = homepage_step.get("classification")
                    log_event(
                        "homepage_gate_failed",
                        mapping_id=mapping.id,
                        reason=homepage_step.get("classification", "navigation_error"),
                        batch_run_id=batch_run_id,
                    )
                    context.close()
                    browser.close()
                else:
                    with deadline(settings.PRODUCT_NAV_TIMEOUT_S, "product_navigation"):
                        product_step = goto_and_capture(page, mapping.source_url, product_expected_markers)
                    log_event(
                        "product_result",
                        mapping_id=mapping.id,
                        http_status=product_step.get("http_status"),
                        classification=product_step.get("classification"),
                        error=product_step.get("error"),
                        batch_run_id=batch_run_id,
                    )

                    result_holder["classification"] = product_step.get("classification")
                    result_holder["http_status"] = product_step.get("http_status")
                    result_holder["observed_classification"] = product_step.get("classification")

                    if product_step.get("classification") == "normal_product" and "error" not in product_step:
                        html = product_step["html"]
                        result_holder["html"] = html
                        extraction = extract_with_agreement(
                            html, mapping.source_url, expected_card_code, expected_treatment
                        )
                        result_holder["extraction"] = extraction
                        log_event(
                            "extraction_result",
                            mapping_id=mapping.id,
                            extraction_status=extraction["extraction_status"],
                            fail_reasons=extraction["fail_reasons"],
                            sell_price_jpy=(extraction.get("extracted") or {}).get("sell_price_jpy"),
                            stock_status=(extraction.get("extracted") or {}).get("stock_status"),
                            batch_run_id=batch_run_id,
                        )
                        if extraction["extraction_status"] != "extracted":
                            # Diagnostic-only detail (never used to accept a
                            # value) - the raw stock/price element text so a
                            # fail-closed disagreement can be root-caused
                            # without re-fetching the page.
                            dom = (extraction.get("raw") or {}).get("dom") or {}
                            jsonld = (extraction.get("raw") or {}).get("jsonld") or {}
                            log_event(
                                "extraction_fail_diagnostics",
                                mapping_id=mapping.id,
                                dom_stock_element=dom.get("stock_element"),
                                dom_price_candidates=dom.get("price_candidates"),
                                jsonld_availability=jsonld.get("offers_availability"),
                                jsonld_price=jsonld.get("offers_price"),
                                batch_run_id=batch_run_id,
                            )

                    context.close()
                    browser.close()
    except DeadlineExceeded as exc:
        log_event("watchdog_triggered", mapping_id=mapping_id, label=str(exc), batch_run_id=batch_run_id)
        return MappingOutcome(
            mapping_id=mapping_id, stage="operational_error", reasons=[f"watchdog_triggered:{exc}"]
        )
    except Exception as exc:  # operational error - never leave a half-written row
        session.rollback()
        log_event(
            "collection_error",
            mapping_id=mapping_id,
            error=f"{type(exc).__name__}: {exc}",
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping_id,
            stage="operational_error",
            reasons=[f"{type(exc).__name__}: {exc}"],
        )

    observed_classification = result_holder["observed_classification"]
    source_denied = observed_classification in SOURCE_DENIAL_CLASSIFICATIONS

    if result_holder["extraction"] is None:
        reasons = [f"no_extraction_attempted:classification={observed_classification}"]
        log_event(
            "collection_no_write",
            mapping_id=mapping.id,
            reasons=reasons,
            source_denied=source_denied,
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping.id,
            stage="no_extraction_attempted",
            classification=observed_classification,
            source_denied=source_denied,
            reasons=reasons,
        )

    write_result = validate_and_write_observation(
        session=session,
        mapping=mapping,
        classification=result_holder["classification"],
        extraction=result_holder["extraction"],
        http_status=result_holder["http_status"],
        raw_html=result_holder["html"],
        source_url=mapping.source_url,
        parser_version=PARSER_VERSION,
    )

    # validate_and_write_observation already flushed (not committed) any
    # would-be insert to compute IDs - roll back unconditionally in
    # validate-only mode so a passing validation never leaves a row behind,
    # regardless of whether it would have written.
    if validate_only:
        session.rollback()
        log_event(
            "validation_result",
            mapping_id=mapping.id,
            would_write=write_result.written,
            reasons=write_result.reasons,
            price_jpy=write_result.price_jpy,
            stock_status=write_result.stock_status,
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping.id,
            stage="validated_only",
            written=write_result.written,
            classification=observed_classification,
            reasons=write_result.reasons,
            price_jpy=write_result.price_jpy,
            stock_status=write_result.stock_status,
        )

    if not write_result.written:
        session.rollback()
        log_event(
            "collection_no_write",
            mapping_id=mapping.id,
            reasons=write_result.reasons,
            source_denied=False,
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping.id,
            stage="validation_failed",
            classification=observed_classification,
            reasons=write_result.reasons,
        )

    session.commit()
    log_event(
        "collection_written",
        mapping_id=mapping.id,
        observation_id=write_result.observation_id,
        raw_snapshot_id=write_result.raw_snapshot_id,
        card_id=write_result.card_id,
        card_print_id=write_result.card_print_id,
        source_id=write_result.source_id,
        source_card_mapping_id=write_result.source_card_mapping_id,
        price_jpy=write_result.price_jpy,
        stock_status=write_result.stock_status,
        observed_at=write_result.observed_at,
        batch_run_id=batch_run_id,
    )
    return MappingOutcome(
        mapping_id=mapping.id,
        stage="written",
        written=True,
        classification=observed_classification,
        observation_id=write_result.observation_id,
        raw_snapshot_id=write_result.raw_snapshot_id,
        card_id=write_result.card_id,
        card_print_id=write_result.card_print_id,
        source_card_mapping_id=write_result.source_card_mapping_id,
        price_jpy=write_result.price_jpy,
        stock_status=write_result.stock_status,
        observed_at=write_result.observed_at,
    )


def run_one_mapping(mapping_id: int, validate_only: bool = False) -> int:
    """Single-mapping CLI entrypoint - opens its own session, runs
    run_one_mapping_detailed, and translates the result to the exact same
    process exit codes this function has always returned: 0 for every clean
    outcome (including "no observation written"), 1 only for a mapping-load
    failure or an unexpected/operational error. Unchanged behavior; see
    MappingOutcome for the richer result batch mode consumes instead."""
    session = SessionLocal()
    try:
        outcome = run_one_mapping_detailed(session, mapping_id, validate_only=validate_only)
        return 1 if outcome.stage in _NONZERO_EXIT_STAGES else 0
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mapping-id", type=int, help="Collect exactly one mapping by id.")
    group.add_argument(
        "--approved-mappings",
        action="store_true",
        help=(
            "Discover every approved, verified-print Yuyu-Tei mapping from the "
            "database and process them sequentially in one bounded batch."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run the full navigation/classification/extraction/lineage check but never write to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="--approved-mappings only: cap how many eligible mappings this run processes.",
    )
    args = parser.parse_args()

    if args.approved_mappings:
        if args.validate_only:
            parser.error("--validate-only is not supported with --approved-mappings")
        from yuyutei_collector.batch import run_batch  # local import avoids a top-level cycle

        result = run_batch(limit=args.limit)
        sys.exit(result.exit_code)

    sys.exit(run_one_mapping(args.mapping_id, validate_only=args.validate_only))


if __name__ == "__main__":
    main()
