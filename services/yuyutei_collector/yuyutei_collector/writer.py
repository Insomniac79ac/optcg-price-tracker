"""Lineage-safe observation writing. Writes exactly one price_observations
row (never updates/mutates an existing one) only when every fail-closed
gate below passes; otherwise writes zero rows to the database and returns
the reasons for audit logging by the caller.

Fail-closed gates (mirrors the tranche's Section 6 requirements):
- page classification must be exactly "normal_product"
- the source_card_mapping must be active, approved, and linked to an exact
  (existing) card_print - not just a legacy card_id
- the mapping's linked card_print's treatment must match what was extracted
- extraction_status must be "extracted" (i.e. extractor.py's own JSON-LD/DOM
  agreement, card-code, and treatment checks all passed)
- the resolved card code must equal the mapping's own source_card_id
- price must be present (already enforced by extraction_status, restated
  here as a direct guard)

Stock/availability is never a fail-closed gate (product decision - see
docs/yuyutei_collector_operations.md "Stock is not required"): a verified
sell price is written whether or not stock is present, missing, unknown, or
disagrees between JSON-LD and DOM. stock_status is still persisted on the
written observation as incidental metadata when the extractor resolved one.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from yuyutei_collector.models import CardPrint, PriceObservation, RawSnapshot, SourceCardMapping


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
    stock_status: str | None = None
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
            # Refuses to let an unverified/pending print (which is exactly
            # what a mock/demo seed row would be linked to, if linked at
            # all) become the lineage anchor for a real observation.
            reasons.append(f"card_print_not_verified:status={card_print.verification_status}")
    return reasons


def validate_and_write_observation(
    session: Session,
    mapping: SourceCardMapping,
    classification: str,
    extraction: dict,
    http_status: int | None,
    raw_html: str,
    source_url: str,
    parser_version: str,
    price_type: str = "sell",
) -> WriteResult:
    reasons: list[str] = []

    reasons.extend(validate_mapping_for_write(session, mapping))

    if classification != "normal_product":
        reasons.append(f"page_classification_not_normal_product:{classification}")

    if extraction.get("extraction_status") != "extracted":
        reasons.extend(extraction.get("fail_reasons") or ["extraction_fail_closed"])

    extracted = extraction.get("extracted") or {}
    resolved_card_code = extracted.get("card_code")
    if resolved_card_code != mapping.source_card_id:
        reasons.append(
            f"card_code_mismatch_vs_mapping:displayed={resolved_card_code},mapping={mapping.source_card_id}"
        )

    if mapping.card_print_id is not None:
        card_print = session.get(CardPrint, mapping.card_print_id)
        if card_print is not None and extracted.get("treatment") not in (None, card_print.treatment):
            reasons.append(
                f"treatment_mismatch_vs_print:displayed={extracted.get('treatment')},print={card_print.treatment}"
            )

    price_jpy = extracted.get("sell_price_jpy")
    # Incidental metadata only (see module docstring) - a missing/ambiguous
    # stock_status never gates the write.
    stock_status = extracted.get("stock_status")
    if price_jpy is None:
        reasons.append("price_missing_or_ambiguous")

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
        stock_status=stock_status,
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
        stock_status=observation.stock_status,
        observed_at=observed_at.isoformat(),
    )
