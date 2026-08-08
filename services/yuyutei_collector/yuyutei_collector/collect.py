"""CLI entrypoint: python -m yuyutei_collector.collect --mapping-id <id>

Runs, collects, and exits - no server, no scheduling (Railway Cron will
call this directly once configured; not configured yet). Exactly one
homepage request, and only if that is a genuine normal HTTP 200, exactly
one product request. No retries after 403/429/challenge/CAPTCHA or an
extraction validation failure. Writes at most one new price_observations
row per invocation, and only on full success - see writer.py.

A future `--batch` mode over all approved mappings is out of scope for this
CLI today; this module supports exactly the one-mapping-at-a-time shape
requested for this vertical slice.
"""

import argparse
import sys
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
PRODUCT_EXPECTED_MARKERS = ["ロロノア・ゾロ", "パラレル"]


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


def run_one_mapping(mapping_id: int) -> int:
    """Returns a process exit code (0 success-and-written or clean no-write
    fail-closed outcome, 1 on an unexpected/operational error)."""
    session = SessionLocal()
    try:
        mapping, source, load_reasons = _load_mapping(session, mapping_id)
        if load_reasons:
            log_event("mapping_load_failed", mapping_id=mapping_id, reasons=load_reasons)
            return 1

        expected_card_code = mapping.source_card_id
        expected_treatment = EXPECTED_TREATMENT
        if mapping.card_print_id is not None:
            card_print = session.get(CardPrint, mapping.card_print_id)
            if card_print is not None:
                expected_treatment = card_print.treatment

        log_event(
            "collection_start",
            mapping_id=mapping.id,
            source=source.name if source else None,
            source_url=mapping.source_url,
            expected_card_code=expected_card_code,
            expected_treatment=expected_treatment,
            card_print_id=mapping.card_print_id,
        )

        result_holder: dict = {"extraction": None, "classification": None, "http_status": None, "html": None}

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
                        http_status=homepage_step.get("http_status"),
                        classification=homepage_step.get("classification"),
                        error=homepage_step.get("error"),
                    )

                    homepage_ok = (
                        "error" not in homepage_step
                        and homepage_step.get("http_status") == 200
                        and homepage_step.get("classification") == "normal_product"
                    )

                    if not homepage_ok:
                        log_event(
                            "homepage_gate_failed",
                            reason=homepage_step.get("classification", "navigation_error"),
                        )
                        context.close()
                        browser.close()
                    else:
                        with deadline(settings.PRODUCT_NAV_TIMEOUT_S, "product_navigation"):
                            product_step = goto_and_capture(page, mapping.source_url, PRODUCT_EXPECTED_MARKERS)
                        log_event(
                            "product_result",
                            http_status=product_step.get("http_status"),
                            classification=product_step.get("classification"),
                            error=product_step.get("error"),
                        )

                        result_holder["classification"] = product_step.get("classification")
                        result_holder["http_status"] = product_step.get("http_status")

                        if product_step.get("classification") == "normal_product" and "error" not in product_step:
                            html = product_step["html"]
                            result_holder["html"] = html
                            extraction = extract_with_agreement(html, mapping.source_url, expected_card_code)
                            result_holder["extraction"] = extraction
                            log_event(
                                "extraction_result",
                                extraction_status=extraction["extraction_status"],
                                fail_reasons=extraction["fail_reasons"],
                                sell_price_jpy=(extraction.get("extracted") or {}).get("sell_price_jpy"),
                                stock_status=(extraction.get("extracted") or {}).get("stock_status"),
                            )

                        context.close()
                        browser.close()
        except DeadlineExceeded as exc:
            log_event("watchdog_triggered", label=str(exc))
            return 1

        if result_holder["extraction"] is None:
            log_event(
                "collection_no_write",
                mapping_id=mapping.id,
                reasons=[f"no_extraction_attempted:classification={result_holder['classification']}"],
            )
            return 0

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

        if not write_result.written:
            session.rollback()
            log_event("collection_no_write", mapping_id=mapping.id, reasons=write_result.reasons)
            return 0

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
        )
        return 0
    except Exception as exc:  # operational error - roll back, never leave a half-written row
        session.rollback()
        log_event("collection_error", mapping_id=mapping_id, error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping-id", type=int, required=True)
    args = parser.parse_args()
    sys.exit(run_one_mapping(args.mapping_id))


if __name__ == "__main__":
    main()
