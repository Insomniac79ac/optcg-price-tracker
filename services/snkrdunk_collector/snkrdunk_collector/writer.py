"""Lineage-safe observation writing. Writes exactly one price_observations
row (never updates/mutates an existing one) only when every fail-closed gate
below passes; otherwise writes zero rows to the database and returns the
reasons for audit logging by the caller. Mirrors
services/yuyutei_collector/yuyutei_collector/writer.py's structure and
fail-closed philosophy, extended with the two checks SNKRDUNK's collector
needs that Yuyu-Tei's doesn't: exact-artwork match and page-language match.

Fail-closed gates:
- page classification must be exactly "normal_page"
- the source_card_mapping must be active, approved, and linked to an exact
  (existing, verified) card_print - not just a legacy card_id
- extraction_status must be "extracted" (extractor.py's own card-code and
  treatment checks passed)
- the resolved card code must equal the mapping's own source_card_id
- the mapping's linked card_print's treatment must match what was extracted
- the mapping's linked card_print's language must match the fetched page's
  own <html lang> attribute (rejects a foreign-language variant page)
- the artwork comparison (see artwork.compare_artwork) must report match=True
- a numeric raw A-D floor price must be present

price_type="floor" (existing repository convention - see
app.services.market_index._resolve_snkrdunk, which already reads
price_type="floor" for SNKRDUNK observations). Sold-history rows are never
written here - see sales_history.py's module docstring for why.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from snkrdunk_collector.models import CardPrint, PriceObservation, RawSnapshot, SourceCardMapping

# card_prints.language uses this app's own short locale codes (e.g. "jp"),
# not the ISO 639-1 codes a page's own <html lang="..."> attribute uses
# (confirmed live: SNKRDUNK's Japanese product pages render lang="ja", not
# lang="jp") - map the former to the latter before comparing so a real jp
# print is never wrongly rejected for its own matching page.
CARD_PRINT_LANGUAGE_TO_HTML_LANG = {"jp": "ja", "en": "en"}


def _expected_html_lang(card_print_language: str) -> str:
    return CARD_PRINT_LANGUAGE_TO_HTML_LANG.get(card_print_language, card_print_language)


@dataclass
class WriteResult:
    written: bool
    reasons: list[str] = field(default_factory=list)
    observation_id: int | None = None
    raw_snapshot_id: int | None = None
    card_id: int | None = None
    card_print_id: int | None = None
    source_id: int | None = None
    source_card_mapping_id: int | None = None
    price_jpy: int | None = None
    condition_label: str | None = None
    observed_at: str | None = None


def validate_mapping_for_write(session: Session, mapping: SourceCardMapping) -> list[str]:
    """Mapping-level fail-closed checks, independent of page content."""
    reasons: list[str] = []
    if not mapping.is_active:
        reasons.append("mapping_not_active")
    if mapping.review_status != "approved":
        reasons.append(f"mapping_not_approved:review_status={mapping.review_status}")
    if mapping.card_print_id is None:
        reasons.append("mapping_not_linked_to_exact_print")
    else:
        card_print = session.get(CardPrint, mapping.card_print_id)
        if card_print is None:
            reasons.append("mapping_card_print_id_does_not_exist")
        elif card_print.verification_status != "verified":
            reasons.append(f"card_print_not_verified:status={card_print.verification_status}")
    return reasons


def validate_and_write_observation(
    session: Session,
    mapping: SourceCardMapping,
    classification: str,
    extraction: dict,
    artwork_comparison: dict | None,
    http_status: int | None,
    raw_html: str,
    source_url: str,
    parser_version: str,
    price_type: str = "floor",
) -> WriteResult:
    reasons: list[str] = []

    reasons.extend(validate_mapping_for_write(session, mapping))

    if classification != "normal_page":
        reasons.append(f"page_classification_not_normal_page:{classification}")

    if extraction.get("extraction_status") != "extracted":
        reasons.extend(extraction.get("fail_reasons") or ["extraction_fail_closed"])

    extracted = extraction.get("extracted") or {}
    resolved_card_code = extracted.get("card_code")
    if resolved_card_code != mapping.source_card_id:
        reasons.append(
            f"card_code_mismatch_vs_mapping:displayed={resolved_card_code},mapping={mapping.source_card_id}"
        )

    card_print: CardPrint | None = None
    if mapping.card_print_id is not None:
        card_print = session.get(CardPrint, mapping.card_print_id)

    if card_print is not None:
        if extracted.get("treatment") not in (None, card_print.treatment):
            reasons.append(
                f"treatment_mismatch_vs_print:displayed={extracted.get('treatment')},print={card_print.treatment}"
            )
        page_language = extracted.get("page_language")
        expected_html_lang = _expected_html_lang(card_print.language)
        if page_language not in (None, expected_html_lang):
            reasons.append(
                f"language_mismatch_vs_print:displayed={page_language},print={card_print.language}"
            )

    if artwork_comparison is None or not artwork_comparison.get("match"):
        reasons.append(
            "artwork_not_confirmed_match:" + str((artwork_comparison or {}).get("error") or "no_match")
        )

    price_jpy = extracted.get("raw_floor_jpy")
    condition_label = extracted.get("raw_floor_condition")
    if price_jpy is None:
        reasons.append("no_raw_condition_price_available")

    # De-duplicate while preserving order for stable, readable logs.
    reasons = list(dict.fromkeys(reasons))

    if reasons:
        return WriteResult(written=False, reasons=reasons)

    content_hash = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()
    observed_at = datetime.now(timezone.utc)

    raw_snapshot = RawSnapshot(
        source_id=mapping.source_id,
        source_url=source_url,
        fetched_at=observed_at,
        http_status=http_status or 0,
        content_hash=content_hash,
        raw_content=raw_html,
        parser_version=parser_version,
    )
    session.add(raw_snapshot)
    session.flush()  # obtain raw_snapshot.id without committing yet

    observation = PriceObservation(
        card_id=mapping.card_id,
        source_id=mapping.source_id,
        observed_at=observed_at,
        price_type=price_type,
        price_jpy=price_jpy,
        condition_label=condition_label,
        raw_snapshot_id=raw_snapshot.id,
        source_card_mapping_id=mapping.id,
        card_print_id=mapping.card_print_id,
    )
    session.add(observation)
    session.flush()

    return WriteResult(
        written=True,
        observation_id=observation.id,
        raw_snapshot_id=raw_snapshot.id,
        card_id=observation.card_id,
        card_print_id=observation.card_print_id,
        source_id=observation.source_id,
        source_card_mapping_id=observation.source_card_mapping_id,
        price_jpy=observation.price_jpy,
        condition_label=observation.condition_label,
        observed_at=observed_at.isoformat(),
    )


def write_evidence_snapshot(
    session: Session, source_id: int, source_url: str, http_status: int | None, raw_html: str, parser_version: str
) -> int:
    """Persist a standalone RawSnapshot not linked to any PriceObservation -
    used to retain the sales-history page as durable raw evidence (section 5:
    "retain the extracted sold rows inside raw evidence/result metadata")
    without writing any price_observations rows for it. Always succeeds
    (evidence retention is never fail-closed); caller commits."""
    content_hash = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()
    snapshot = RawSnapshot(
        source_id=source_id,
        source_url=source_url,
        fetched_at=datetime.now(timezone.utc),
        http_status=http_status or 0,
        content_hash=content_hash,
        raw_content=raw_html,
        parser_version=parser_version,
    )
    session.add(snapshot)
    session.flush()
    return snapshot.id
