"""CLI entrypoints:

    python -m snkrdunk_collector.collect --mapping-id <id> [--validate-only]
    python -m snkrdunk_collector.collect --approved-mappings [--validate-only]

Runs, collects, and exits - no server, no scheduling (Railway Cron
configuration is a separate tranche step). Exactly one homepage request as a
source-wide-denial canary, and only if that is a genuine normal HTTP 200,
exactly one product request, one image fetch each for the official and
candidate artwork, and (best-effort, never gating) one sales-history
request - per mapping. No retries after 403/429/challenge/CAPTCHA or an
extraction/artwork/lineage validation failure. Writes at most one new
price_observations row per mapping per invocation, and only on full success
- see writer.py. Sold-history rows are never written as price_observations
(see sales_history.py's module docstring) - retained only as a standalone
RawSnapshot and in this run's own structured log/result output.

`--approved-mappings` (see snkrdunk_collector.batch) discovers every
eligible approved SNKRDUNK mapping from the database and processes them one
at a time, sequentially, stopping the whole batch immediately on a
source-wide denial signal (403/429/CAPTCHA/challenge) - mirrors
services/yuyutei_collector/yuyutei_collector/batch.py's contract.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from snkrdunk_collector.artwork import compare_artwork
from snkrdunk_collector.browser import (
    DESKTOP_ACCEPT_LANGUAGE,
    DESKTOP_CHROME_UA,
    DESKTOP_VIEWPORT,
    HOMEPAGE_URL,
    DeadlineExceeded,
    deadline,
    fetch_bytes,
    goto_and_capture,
    log_event,
)
from snkrdunk_collector.config import settings
from snkrdunk_collector.db import SessionLocal
from snkrdunk_collector.extractor import extract_product
from snkrdunk_collector.models import CardPrint, Source, SourceCardMapping
from snkrdunk_collector.sales_history import find_sales_history_link, parse_sales_history_page
from snkrdunk_collector.writer import (
    PRICE_ONLY_FAIL_REASONS,
    validate_and_write_observation,
    write_evidence_snapshot,
)

PARSER_VERSION = "snkrdunk-collector-v2"

# The parser version bumps to v2 with the identity-evidence expansion:
# observed name/rarity/release/set and complete per-condition A-D prices are
# now retained, and release/set is verified rather than ignored. A record
# tagged v1 was produced by a parser that could not have checked those.


def _is_floor_unavailable(write_result) -> bool:
    """A verified print that simply has nothing listed right now.

    Page loaded normally, identity/artwork/release all verified, and the ONLY
    thing standing between it and a row is that every A-D chip is 出品待ち.
    That is a successful outcome with nothing to record - not a failure - so
    it must not colour the batch's exit code. Any other blocking reason
    (approval state, identity mismatch, denial) disqualifies it.
    """
    if not write_result.identity_verified or write_result.price_jpy is not None:
        return False
    blocking = [
        reason
        for reason in write_result.reasons
        if reason.split(":", 1)[0] not in PRICE_ONLY_FAIL_REASONS
    ]
    return not blocking


def _identity_classification(write_result) -> str:
    """The verification verdict for one mapping, derived only from what this
    run observed. Identity is judged independently of price availability -
    see writer.PRICE_ONLY_FAIL_REASONS."""
    if not write_result.identity_verified:
        return "IDENTITY_FAILED"
    if write_result.price_jpy is None:
        return "PASS_FLOOR_UNAVAILABLE"
    return "PASS"

# A page classified as one of these is a source-wide denial signal, not a
# per-mapping data problem - see browser.classify_page.
SOURCE_DENIAL_CLASSIFICATIONS = frozenset({"static_403", "static_429", "challenge_or_captcha"})

_NONZERO_EXIT_STAGES = frozenset({"mapping_load_failed", "operational_error"})


@dataclass
class MappingOutcome:
    mapping_id: int
    stage: str
    # `written` means a row was actually persisted. In a validate-only run it
    # is ALWAYS False - use `would_write` for "every write gate passed".
    # Conflating the two previously let batch_complete.mappings_written count
    # writes that never happened, which is exactly the number a zero-write
    # audit relies on.
    written: bool = False
    would_write: bool = False
    # A verified print with no current listing - a SUCCESSFUL no-write
    # outcome, never counted as a batch failure. See _is_floor_unavailable.
    floor_unavailable: bool = False
    source_denied: bool = False
    classification: str | None = None
    reasons: list[str] = field(default_factory=list)
    identity_verified: bool = False
    identity_reasons: list[str] = field(default_factory=list)
    identity_classification: str | None = None
    card_code_authority: str | None = None
    card_code_evidence: str | None = None
    card_code_evidence_type: str | None = None
    release_name_match_authority: str | None = None
    observation_id: int | None = None
    raw_snapshot_id: int | None = None
    card_id: int | None = None
    card_print_id: int | None = None
    source_card_mapping_id: int | None = None
    price_jpy: int | None = None
    condition_label: str | None = None
    observed_at: str | None = None
    artwork_match: bool | None = None
    raw_a_to_d: dict | None = None
    sold_history: dict | None = None


def _load_mapping(session, mapping_id: int) -> tuple[SourceCardMapping | None, Source | None, CardPrint | None, list[str]]:
    reasons: list[str] = []
    mapping = session.get(SourceCardMapping, mapping_id)
    if mapping is None:
        return None, None, None, [f"mapping_not_found:{mapping_id}"]
    source = session.get(Source, mapping.source_id)
    if source is None:
        reasons.append(f"source_not_found:{mapping.source_id}")
    if mapping.source_url is None:
        reasons.append("mapping_missing_source_url")
    card_print = None
    if mapping.card_print_id is not None:
        card_print = session.get(CardPrint, mapping.card_print_id)
        if card_print is None:
            reasons.append(f"card_print_not_found:{mapping.card_print_id}")
    return mapping, source, card_print, reasons


def run_one_mapping_detailed(
    session, mapping_id: int, validate_only: bool = False, batch_run_id: str | None = None
) -> MappingOutcome:
    mapping, source, card_print, load_reasons = _load_mapping(session, mapping_id)
    if load_reasons:
        log_event("mapping_load_failed", mapping_id=mapping_id, reasons=load_reasons, batch_run_id=batch_run_id)
        return MappingOutcome(mapping_id=mapping_id, stage="mapping_load_failed", reasons=load_reasons)

    expected_card_code = mapping.source_card_id
    expected_treatment = card_print.treatment if card_print else None

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

    holder: dict = {
        "product_classification": None,
        "product_http_status": None,
        "product_html": None,
        "product_final_url": None,
        "extraction": None,
        "artwork_comparison": None,
        "sold_history": None,
        "sales_history_html": None,
        "sales_history_url": None,
        "sales_history_http_status": None,
    }

    try:
        with deadline(settings.TOTAL_RUN_TIMEOUT_S, "total_run"):
            with sync_playwright() as p:
                log_event("playwright_ready", playwright_version=pkg_version("playwright"))
                with deadline(settings.BROWSER_LAUNCH_TIMEOUT_S, "browser_launch"):
                    browser = p.chromium.launch(headless=True, timeout=settings.BROWSER_LAUNCH_TIMEOUT_S * 1000)
                    context = browser.new_context(
                        user_agent=DESKTOP_CHROME_UA,
                        viewport=DESKTOP_VIEWPORT,
                        locale="ja-JP",
                        extra_http_headers={"Accept-Language": DESKTOP_ACCEPT_LANGUAGE},
                    )
                    page = context.new_page()

                with deadline(settings.HOMEPAGE_NAV_TIMEOUT_S, "homepage_navigation"):
                    homepage_step = goto_and_capture(page, HOMEPAGE_URL)
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
                    and homepage_step.get("classification") == "normal_page"
                )

                if not homepage_ok:
                    holder["product_classification"] = homepage_step.get("classification", "navigation_error")
                    log_event(
                        "homepage_gate_failed",
                        mapping_id=mapping.id,
                        reason=holder["product_classification"],
                        batch_run_id=batch_run_id,
                    )
                    context.close()
                    browser.close()
                else:
                    with deadline(settings.PRODUCT_NAV_TIMEOUT_S, "product_navigation"):
                        product_step = goto_and_capture(page, mapping.source_url)
                    log_event(
                        "product_result",
                        mapping_id=mapping.id,
                        http_status=product_step.get("http_status"),
                        classification=product_step.get("classification"),
                        error=product_step.get("error"),
                        batch_run_id=batch_run_id,
                    )
                    holder["product_classification"] = product_step.get("classification")
                    holder["product_http_status"] = product_step.get("http_status")

                    if product_step.get("classification") == "normal_page" and "error" not in product_step:
                        html = product_step["html"]
                        holder["product_html"] = html
                        holder["product_final_url"] = product_step["final_url"]

                        extraction = extract_product(
                            html, product_step["final_url"], expected_card_code, expected_treatment
                        )
                        holder["extraction"] = extraction
                        # Every observed identity field is logged verbatim so
                        # a verification record can be reconstructed from the
                        # run's own evidence alone, without re-deriving
                        # anything from database metadata. `conditions` is
                        # the complete per-condition object (price_jpy +
                        # raw_text), NOT list(keys) - reducing it to its keys
                        # previously discarded every A-D price.
                        extracted_fields = extraction["extracted"]
                        log_event(
                            "extraction_result",
                            mapping_id=mapping.id,
                            extraction_status=extraction["extraction_status"],
                            fail_reasons=extraction["fail_reasons"],
                            observed_title=extracted_fields.get("title"),
                            observed_card_name=extracted_fields.get("card_name"),
                            observed_card_code=extracted_fields.get("card_code"),
                            observed_rarity=extracted_fields.get("rarity"),
                            observed_treatment=extracted_fields.get("treatment"),
                            observed_page_language=extracted_fields.get("page_language"),
                            observed_release_text=extracted_fields.get("release_text"),
                            observed_release_product_code=extracted_fields.get("release_product_code"),
                            observed_product_image_url=extracted_fields.get("product_image_url"),
                            raw_floor_jpy=extracted_fields.get("raw_floor_jpy"),
                            raw_floor_condition=extracted_fields.get("raw_floor_condition"),
                            conditions=extracted_fields.get("conditions") or {},
                            selector_version=extraction.get("selector_version"),
                            batch_run_id=batch_run_id,
                        )

                        candidate_image_url = extraction["extracted"].get("product_image_url")
                        official_image_url = card_print.image_url if card_print else None
                        if candidate_image_url and official_image_url:
                            with deadline(settings.IMAGE_FETCH_TIMEOUT_S, "image_fetch"):
                                official_bytes = fetch_bytes(page, official_image_url)
                                candidate_bytes = fetch_bytes(page, candidate_image_url)
                            if official_bytes and candidate_bytes:
                                holder["artwork_comparison"] = compare_artwork(official_bytes, candidate_bytes)
                            else:
                                holder["artwork_comparison"] = {
                                    "match": False,
                                    "error": "image_fetch_failed",
                                    "official_fetched": bool(official_bytes),
                                    "candidate_fetched": bool(candidate_bytes),
                                }
                        else:
                            holder["artwork_comparison"] = {"match": False, "error": "missing_image_url"}
                        log_event(
                            "artwork_comparison_complete",
                            mapping_id=mapping.id,
                            match=holder["artwork_comparison"].get("match"),
                            hash_distances=holder["artwork_comparison"].get("hash_distances"),
                            aspect_ratio_relative_diff=holder["artwork_comparison"].get("aspect_ratio_relative_diff"),
                            batch_run_id=batch_run_id,
                        )

                        # Sold history: best-effort, evidence-only, never
                        # gates the write (see sales_history.py).
                        soup_for_link = BeautifulSoup(html, "html.parser")
                        history_href, history_link_diag = find_sales_history_link(soup_for_link)
                        if history_href:
                            history_url = urljoin(product_step["final_url"], history_href)
                            with deadline(settings.SALES_HISTORY_NAV_TIMEOUT_S, "sales_history_navigation"):
                                history_step = goto_and_capture(page, history_url)
                            log_event(
                                "sales_history_result",
                                mapping_id=mapping.id,
                                http_status=history_step.get("http_status"),
                                classification=history_step.get("classification"),
                                batch_run_id=batch_run_id,
                            )
                            if history_step.get("classification") == "normal_page" and "error" not in history_step:
                                pid_match = re.search(r"/apparels/(\d+)", mapping.source_url)
                                product_id = pid_match.group(1) if pid_match else None
                                sold_history = parse_sales_history_page(history_step["html"], product_id)
                                sold_history["link_diagnostics"] = history_link_diag
                                sold_history["source_url"] = history_url
                                holder["sold_history"] = sold_history
                                holder["sales_history_html"] = history_step["html"]
                                holder["sales_history_url"] = history_url
                                holder["sales_history_http_status"] = history_step.get("http_status")
                                log_event(
                                    "sold_history_extracted",
                                    mapping_id=mapping.id,
                                    availability_status=sold_history["availability_status"],
                                    raw_sales_count=len(sold_history["raw_sales"]),
                                    stable_identifier_available=sold_history["stable_identifier_available"],
                                    batch_run_id=batch_run_id,
                                )
                        else:
                            holder["sold_history"] = {
                                "availability_status": "not_exposed_on_current_product",
                                "raw_sales": [],
                                "stable_identifier_available": False,
                                "link_diagnostics": history_link_diag,
                            }

                    context.close()
                    browser.close()
    except DeadlineExceeded as exc:
        log_event("watchdog_triggered", mapping_id=mapping_id, label=str(exc), batch_run_id=batch_run_id)
        return MappingOutcome(mapping_id=mapping_id, stage="operational_error", reasons=[f"watchdog_triggered:{exc}"])
    except Exception as exc:  # never leave a half-written row
        session.rollback()
        log_event("collection_error", mapping_id=mapping_id, error=f"{type(exc).__name__}: {exc}", batch_run_id=batch_run_id)
        return MappingOutcome(mapping_id=mapping_id, stage="operational_error", reasons=[f"{type(exc).__name__}: {exc}"])

    classification = holder["product_classification"]
    source_denied = classification in SOURCE_DENIAL_CLASSIFICATIONS

    if holder["extraction"] is None:
        reasons = [f"no_extraction_attempted:classification={classification}"]
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
            classification=classification,
            source_denied=source_denied,
            reasons=reasons,
        )

    write_result = validate_and_write_observation(
        session=session,
        mapping=mapping,
        classification=classification,
        extraction=holder["extraction"],
        artwork_comparison=holder["artwork_comparison"],
        http_status=holder["product_http_status"],
        raw_html=holder["product_html"],
        source_url=holder["product_final_url"],
        parser_version=PARSER_VERSION,
    )

    if validate_only:
        session.rollback()
        log_event(
            "validation_result",
            mapping_id=mapping.id,
            would_write=write_result.written,
            reasons=write_result.reasons,
            identity_verified=write_result.identity_verified,
            identity_reasons=write_result.identity_reasons,
            identity_classification=_identity_classification(write_result),
            card_code_authority=write_result.card_code_authority,
            card_code_evidence=write_result.card_code_evidence,
            release_name_match_authority=write_result.release_name_match_authority,
            price_jpy=write_result.price_jpy,
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping.id,
            stage="validated_only",
            written=False,  # the session was just rolled back - nothing persisted
            would_write=write_result.written,
            floor_unavailable=_is_floor_unavailable(write_result),
            classification=classification,
            reasons=write_result.reasons,
            identity_verified=write_result.identity_verified,
            identity_reasons=write_result.identity_reasons,
            identity_classification=_identity_classification(write_result),
            card_code_authority=write_result.card_code_authority,
            card_code_evidence=write_result.card_code_evidence,
            card_code_evidence_type=write_result.card_code_evidence_type,
            release_name_match_authority=write_result.release_name_match_authority,
            price_jpy=write_result.price_jpy,
            condition_label=write_result.condition_label,
            artwork_match=(holder["artwork_comparison"] or {}).get("match"),
            raw_a_to_d=(holder["extraction"] or {}).get("extracted", {}).get("conditions"),
            sold_history=holder["sold_history"],
        )

    if not write_result.written:
        session.rollback()
        floor_unavailable = _is_floor_unavailable(write_result)
        log_event(
            "collection_no_write",
            mapping_id=mapping.id,
            reasons=write_result.reasons,
            identity_verified=write_result.identity_verified,
            identity_reasons=write_result.identity_reasons,
            identity_classification=_identity_classification(write_result),
            floor_unavailable=floor_unavailable,
            card_code_authority=write_result.card_code_authority,
            card_code_evidence_type=write_result.card_code_evidence_type,
            release_name_matched_via=write_result.release_name_match_authority,
            source_denied=False,
            batch_run_id=batch_run_id,
        )
        return MappingOutcome(
            mapping_id=mapping.id,
            stage="floor_unavailable" if floor_unavailable else "validation_failed",
            floor_unavailable=floor_unavailable,
            classification=classification,
            reasons=write_result.reasons,
            identity_verified=write_result.identity_verified,
            identity_reasons=write_result.identity_reasons,
            identity_classification=_identity_classification(write_result),
            card_code_authority=write_result.card_code_authority,
            card_code_evidence=write_result.card_code_evidence,
            card_code_evidence_type=write_result.card_code_evidence_type,
            release_name_match_authority=write_result.release_name_match_authority,
            price_jpy=write_result.price_jpy,
            condition_label=write_result.condition_label,
            artwork_match=(holder["artwork_comparison"] or {}).get("match"),
            raw_a_to_d=(holder["extraction"] or {}).get("extracted", {}).get("conditions"),
            sold_history=holder["sold_history"],
        )

    # Evidence retention for sold history (section 5): a standalone raw
    # snapshot, never a price_observations row - see writer.write_evidence_snapshot.
    if holder["sales_history_html"] is not None:
        write_evidence_snapshot(
            session=session,
            source_id=mapping.source_id,
            source_url=holder["sales_history_url"],
            http_status=holder["sales_history_http_status"],
            raw_html=holder["sales_history_html"],
            parser_version=PARSER_VERSION,
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
        condition_label=write_result.condition_label,
        observed_at=write_result.observed_at,
        sold_history_status=(holder["sold_history"] or {}).get("availability_status"),
        sold_history_raw_sales_count=len((holder["sold_history"] or {}).get("raw_sales") or []),
        card_code_authority=write_result.card_code_authority,
        card_code_evidence_type=write_result.card_code_evidence_type,
        release_name_matched_via=write_result.release_name_match_authority,
        batch_run_id=batch_run_id,
    )
    return MappingOutcome(
        mapping_id=mapping.id,
        stage="written",
        written=True,
        would_write=True,
        identity_verified=write_result.identity_verified,
        identity_reasons=write_result.identity_reasons,
        identity_classification=_identity_classification(write_result),
        card_code_authority=write_result.card_code_authority,
        card_code_evidence=write_result.card_code_evidence,
        card_code_evidence_type=write_result.card_code_evidence_type,
        release_name_match_authority=write_result.release_name_match_authority,
        classification=classification,
        observation_id=write_result.observation_id,
        raw_snapshot_id=write_result.raw_snapshot_id,
        card_id=write_result.card_id,
        card_print_id=write_result.card_print_id,
        source_card_mapping_id=write_result.source_card_mapping_id,
        price_jpy=write_result.price_jpy,
        condition_label=write_result.condition_label,
        observed_at=write_result.observed_at,
        artwork_match=(holder["artwork_comparison"] or {}).get("match"),
        raw_a_to_d=(holder["extraction"] or {}).get("extracted", {}).get("conditions"),
        sold_history=holder["sold_history"],
    )


def run_one_mapping(mapping_id: int, validate_only: bool = False) -> int:
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
            "Discover every approved, verified-print SNKRDUNK mapping from the "
            "database and process them sequentially in one bounded batch."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run the full navigation/classification/extraction/artwork/lineage check but never write to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="--approved-mappings only: cap how many eligible mappings this run processes.",
    )
    parser.add_argument(
        "--mapping-ids",
        type=str,
        default=None,
        help=(
            "--approved-mappings only: comma-separated mapping ids to narrow the "
            "eligible set to. Ids outside the eligible set are silently excluded, "
            "never force-included (unless --allow-unapproved is also given)."
        ),
    )
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help=(
            "--approved-mappings only, and only together with --validate-only and "
            "--mapping-ids: bypass the review_status=approved/manual_verified=True/"
            "print-verification_status=verified eligibility gate so an explicit, "
            "caller-given list of not-yet-approved mapping ids can be identity/"
            "artwork re-verified in one bounded, sequential, safety-identical batch. "
            "Never widens what --mapping-ids targets beyond the ids given - it only "
            "relaxes which review states are eligible. Mechanically cannot write "
            "(validate_only is required), so it can never move an unapproved "
            "mapping into production on its own."
        ),
    )
    args = parser.parse_args()

    if args.allow_unapproved and not (args.approved_mappings and args.validate_only and args.mapping_ids):
        parser.error("--allow-unapproved requires --approved-mappings, --validate-only, and --mapping-ids together.")

    if args.approved_mappings:
        from snkrdunk_collector.batch import run_batch  # local import avoids a top-level cycle

        mapping_ids = None
        if args.mapping_ids:
            try:
                mapping_ids = [int(x) for x in args.mapping_ids.split(",") if x.strip()]
            except ValueError:
                parser.error("--mapping-ids must be a comma-separated list of integers")

        result = run_batch(
            limit=args.limit,
            mapping_ids=mapping_ids,
            validate_only=args.validate_only,
            require_approved=not args.allow_unapproved,
        )
        sys.exit(result.exit_code)

    run_id_ts = datetime.now(timezone.utc).isoformat()
    log_event("run_start", run_at=run_id_ts, mapping_id=args.mapping_id, validate_only=args.validate_only)

    session = SessionLocal()
    try:
        outcome = run_one_mapping_detailed(session, args.mapping_id, validate_only=args.validate_only)
    finally:
        session.close()

    log_event("run_complete", **asdict(outcome))
    print("RESULT_JSON=" + json.dumps(asdict(outcome), ensure_ascii=False), flush=True)
    sys.exit(1 if outcome.stage in _NONZERO_EXIT_STAGES else 0)


if __name__ == "__main__":
    main()
