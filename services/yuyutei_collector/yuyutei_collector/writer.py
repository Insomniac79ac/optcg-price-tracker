"""Lineage-safe observation writing. Writes exactly one price_observations
row (never updates/mutates an existing one) only when every fail-closed
gate below passes; otherwise writes zero rows to the database and returns
the reasons for audit logging by the caller.

The raw response is not created here. Collection commits it before parsing and
passes its id into this writer; keeping snapshot creation out of the observation
transaction is what lets that evidence survive every failure below.

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

Promotion state is treated identically and for the same reason. What the
source said about its own price ("sale" / "none" / not-determined) is
persisted alongside the price, but it never appears in `reasons` and can
never stop a write: a page whose SALE markers disagree still displayed a
verified sell price, and losing that price to protect a label would trade
real market evidence for nothing. The struck FORMER price is never written -
it is not an offer, so it is not stored as one; the page that displayed it is
retained whole in raw_snapshots.raw_content.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from yuyutei_collector.models import (
    CardPrint,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
)

SOURCE_NAME = "yuyutei"


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
    # None here is ambiguous in exactly the way the column is: either the page
    # markers disagreed, or nothing was written at all. Callers read it only
    # off a WriteResult whose `written` is True.
    promotion_state: str | None = None
    observed_at: str | None = None


def validate_mapping_for_write(session: Session, mapping: SourceCardMapping) -> list[str]:
    """Mapping-level fail-closed checks, independent of page content."""
    reasons: list[str] = []
    if not mapping.is_active:
        reasons.append("mapping_not_active")
    if mapping.review_status != "approved":
        reasons.append(f"mapping_not_approved:review_status={mapping.review_status}")

    source = session.get(Source, mapping.source_id)
    if source is None:
        reasons.append(f"mapping_source_does_not_exist:source_id={mapping.source_id}")
    elif source.name != SOURCE_NAME:
        reasons.append(
            f"mapping_source_mismatch:expected={SOURCE_NAME},actual={source.name}"
        )

    if mapping.card_print_id is None:
        reasons.append("mapping_not_linked_to_exact_print")
    else:
        card_print = session.get(CardPrint, mapping.card_print_id)
        if card_print is None:
            reasons.append("mapping_card_print_id_does_not_exist")
        else:
            if not card_print.is_active:
                reasons.append("card_print_not_active")
            if card_print.verification_status != "verified":
                # Refuses to let an unverified/pending print (which is exactly
                # what a mock/demo seed row would be linked to, if linked at
                # all) become the lineage anchor for a real observation.
                reasons.append(
                    f"card_print_not_verified:status={card_print.verification_status}"
                )
    return reasons


def validate_and_write_observation(
    session: Session,
    mapping: SourceCardMapping,
    classification: str,
    extraction: dict,
    raw_snapshot_id: int | None,
    write_observation: bool = True,
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
        # card_print.treatment being NULL is "unclassified", not an
        # expectation that the page show nothing - see extractor.py.
        if (
            card_print is not None
            and card_print.treatment is not None
            and extracted.get("treatment") not in (None, card_print.treatment)
        ):
            reasons.append(
                f"treatment_mismatch_vs_print:displayed={extracted.get('treatment')},print={card_print.treatment}"
            )

    price_jpy = extracted.get("sell_price_jpy")
    # Incidental metadata only (see module docstring) - a missing/ambiguous
    # stock_status never gates the write.
    stock_status = extracted.get("stock_status")
    # Descriptive metadata on exactly the same footing as stock_status, and
    # for the same reason: what the source said about its own price is worth
    # recording, but a page whose promotion markers disagree still displayed a
    # verified sell price, and refusing to store that price would trade real
    # market evidence for a label. `.get` rather than `[...]` so an older
    # caller whose extraction dict predates the key still writes normally,
    # landing NULL - which is exactly what NULL means here.
    promotion_state = extracted.get("promotion_state")
    if price_jpy is None:
        reasons.append("price_missing_or_ambiguous")

    if write_observation:
        if raw_snapshot_id is None:
            reasons.append("raw_snapshot_missing")
        else:
            raw_snapshot = session.get(RawSnapshot, raw_snapshot_id)
            if raw_snapshot is None:
                reasons.append(f"raw_snapshot_not_found:{raw_snapshot_id}")
            elif raw_snapshot.source_id != mapping.source_id:
                reasons.append(
                    "raw_snapshot_source_mismatch:"
                    f"snapshot={raw_snapshot.source_id},mapping={mapping.source_id}"
                )

    # De-duplicate while preserving order for stable, readable logs.
    reasons = list(dict.fromkeys(reasons))

    if reasons:
        return WriteResult(written=False, reasons=reasons)

    observed_at = datetime.now(timezone.utc)

    if not write_observation:
        return WriteResult(
            written=True,
            raw_snapshot_id=None,
            card_id=mapping.card_id,
            card_print_id=mapping.card_print_id,
            source_id=mapping.source_id,
            source_card_mapping_id=mapping.id,
            price_jpy=price_jpy,
            stock_status=stock_status,
            promotion_state=promotion_state,
            observed_at=observed_at.isoformat(),
        )

    observation = PriceObservation(
        card_id=mapping.card_id,
        source_id=mapping.source_id,
        observed_at=observed_at,
        price_type=price_type,
        price_jpy=price_jpy,
        stock_status=stock_status,
        promotion_state=promotion_state,
        raw_snapshot_id=raw_snapshot_id,
        source_card_mapping_id=mapping.id,
        card_print_id=mapping.card_print_id,
    )
    session.add(observation)
    session.flush()

    return WriteResult(
        written=True,
        observation_id=observation.id,
        raw_snapshot_id=raw_snapshot_id,
        card_id=observation.card_id,
        card_print_id=observation.card_print_id,
        source_id=observation.source_id,
        source_card_mapping_id=observation.source_card_mapping_id,
        price_jpy=observation.price_jpy,
        stock_status=observation.stock_status,
        promotion_state=observation.promotion_state,
        observed_at=observed_at.isoformat(),
    )
