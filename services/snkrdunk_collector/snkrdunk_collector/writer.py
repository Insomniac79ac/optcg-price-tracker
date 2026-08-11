"""Lineage-safe observation writing. Writes exactly one price_observations
row (never updates/mutates an existing one) only when every fail-closed gate
below passes; otherwise writes zero rows to the database and returns the
reasons for audit logging by the caller. Mirrors
services/yuyutei_collector/yuyutei_collector/writer.py's structure and
fail-closed philosophy, extended with the two checks SNKRDUNK's collector
needs that Yuyu-Tei's doesn't: exact-artwork match and page-language match.

Two distinct verdicts are produced, because they answer different questions:

- validate_identity() answers "is the stored product actually the intended
  verified print?" - card code, name, rarity, treatment, language,
  release/set and exact artwork, each with its own named fail reason. A
  missing listed price never invalidates identity (see
  PRICE_ONLY_FAIL_REASONS), so a product whose A-D chips are all 出品待ち is
  still fully identifiable.
- validate_and_write_observation() answers "may a row be written?" - every
  identity gate above, plus mapping approval state and an actual numeric
  raw A-D floor price.

That split is what lets a pre-approval re-verification pass establish
mapping trust from identity alone (PASS_FLOOR_UNAVAILABLE) while keeping the
write path exactly as fail-closed as before.

price_type="floor" (existing repository convention - see
app.services.market_index._resolve_snkrdunk, which already reads
price_type="floor" for SNKRDUNK observations). Sold-history rows are never
written here - see sales_history.py's module docstring for why.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from snkrdunk_collector.identity import normalize_card_name, release_names_match
from snkrdunk_collector.release_reference import (
    RELEASE_NAME_AUTHORITY,
    get_release_reference,
)
from snkrdunk_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    SourceCardMapping,
)

# card_prints.language uses this app's own short locale codes (e.g. "jp"),
# not the ISO 639-1 codes a page's own <html lang="..."> attribute uses
# (confirmed live: SNKRDUNK's Japanese product pages render lang="ja", not
# lang="jp") - map the former to the latter before comparing so a real jp
# print is never wrongly rejected for its own matching page.
CARD_PRINT_LANGUAGE_TO_HTML_LANG = {"jp": "ja", "en": "en"}


def _expected_html_lang(card_print_language: str) -> str:
    return CARD_PRINT_LANGUAGE_TO_HTML_LANG.get(card_print_language, card_print_language)


# Fail reasons that speak only to whether a *price* is currently listed, not
# to whether the stored product is the intended print. Identity verification
# deliberately ignores these: a print whose A-D chips are all 出品待ち is
# still fully identifiable (see PASS_FLOOR_UNAVAILABLE), it just has nothing
# to observe a floor from yet.
PRICE_ONLY_FAIL_REASONS = frozenset({"no_raw_condition_price_available"})


@dataclass
class WriteResult:
    written: bool
    reasons: list[str] = field(default_factory=list)
    identity_verified: bool = False
    identity_reasons: list[str] = field(default_factory=list)
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


def validate_identity(
    mapping: SourceCardMapping,
    card_print: CardPrint | None,
    canonical: CanonicalCard | None,
    classification: str,
    extraction: dict,
    artwork_comparison: dict | None,
) -> list[str]:
    """Every check that answers "is the stored product actually the intended
    verified print?" - and nothing that answers "is there a price on it?".

    Each dimension emits its own distinct reason so an audit record can name
    exactly which one failed. Comparison targets are the print's *canonical*
    identity (name/rarity/set) plus the print row itself (treatment/language/
    release), never the mapping's free-text fields.
    """
    reasons: list[str] = []
    extracted = extraction.get("extracted") or {}

    if classification != "normal_page":
        reasons.append(f"page_classification_not_normal_page:{classification}")

    # extractor.py's own fail-closed reasons, minus the purely price-related
    # ones (a missing floor never invalidates identity).
    for reason in extraction.get("fail_reasons") or []:
        if reason.split(":", 1)[0] not in PRICE_ONLY_FAIL_REASONS:
            reasons.append(reason)

    displayed_code = extracted.get("card_code")
    if displayed_code != mapping.source_card_id:
        reasons.append(f"card_code_mismatch:displayed={displayed_code},expected={mapping.source_card_id}")

    if card_print is None:
        reasons.append("card_print_missing_for_identity_check")
    else:
        displayed_treatment = extracted.get("treatment")
        if displayed_treatment != card_print.treatment:
            reasons.append(
                f"treatment_mismatch:displayed={displayed_treatment},expected={card_print.treatment}"
            )

        page_language = extracted.get("page_language")
        expected_html_lang = _expected_html_lang(card_print.language)
        if page_language != expected_html_lang:
            reasons.append(
                f"language_mismatch:displayed={page_language},expected={card_print.language}"
            )

        # Release validation is two INDEPENDENT checks, and both must pass.
        #
        # (A) the set token in the page's own card code vs the print's
        #     release_product_code, and
        # (B) the page's own release NAME vs Bandai's authoritative name for
        #     that release code.
        #
        # (A) alone cannot catch a reprint or alternate product carrying an
        # unchanged card code but belonging to a different release, which is
        # exactly what (B) exists to detect - so they stay separate reasons.
        displayed_release = extracted.get("release_product_code")
        if displayed_release != card_print.release_product_code:
            reasons.append(
                f"release_product_mismatch:displayed={displayed_release},"
                f"expected={card_print.release_product_code},"
                f"release_text={extracted.get('release_text')}"
            )

        reference = get_release_reference(card_print.release_product_code)
        if reference is None:
            # A release with no authoritative reference must never be waved
            # through - that is how an OP05+ expansion would silently bypass
            # this gate entirely.
            reasons.append(
                f"authoritative_release_name_missing:release={card_print.release_product_code}"
            )
        else:
            observed_release_text = extracted.get("release_text")
            if not any(
                release_names_match(observed_release_text, official)
                for official in reference.accepted_names()
            ):
                reasons.append(
                    f"release_name_mismatch:displayed={observed_release_text},"
                    f"expected={reference.bandai_official_name},"
                    f"authority={RELEASE_NAME_AUTHORITY}"
                )

    if canonical is None:
        reasons.append("canonical_card_missing_for_identity_check")
    else:
        displayed_name = normalize_card_name(extracted.get("card_name"))
        expected_name = normalize_card_name(canonical.name_jp)
        # Tolerant of legitimate extra formatting SNKRDUNK may append to a
        # name, but never of a different card: the expected name must appear
        # whole. Generic containment only - no per-card aliasing.
        if not expected_name or not displayed_name or expected_name not in displayed_name:
            reasons.append(
                f"title_mismatch:displayed={extracted.get('card_name')},expected={canonical.name_jp}"
            )

        displayed_rarity = (extracted.get("rarity") or "").strip().upper() or None
        expected_rarity = (canonical.rarity or "").strip().upper() or None
        if not expected_rarity or displayed_rarity != expected_rarity:
            reasons.append(
                f"rarity_mismatch:displayed={extracted.get('rarity')},expected={canonical.rarity}"
            )

    if artwork_comparison is None or not artwork_comparison.get("match"):
        reasons.append(
            "artwork_not_confirmed_match:" + str((artwork_comparison or {}).get("error") or "no_match")
        )

    return list(dict.fromkeys(reasons))


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
    extracted = extraction.get("extracted") or {}

    card_print: CardPrint | None = None
    if mapping.card_print_id is not None:
        card_print = session.get(CardPrint, mapping.card_print_id)

    canonical: CanonicalCard | None = None
    if card_print is not None:
        canonical = session.get(CanonicalCard, card_print.canonical_card_id)

    identity_reasons = validate_identity(
        mapping=mapping,
        card_print=card_print,
        canonical=canonical,
        classification=classification,
        extraction=extraction,
        artwork_comparison=artwork_comparison,
    )

    # A write additionally needs approval state and an actual listed price;
    # neither bears on whether the product *is* the intended print.
    reasons = list(identity_reasons)
    reasons.extend(validate_mapping_for_write(session, mapping))

    price_jpy = extracted.get("raw_floor_jpy")
    condition_label = extracted.get("raw_floor_condition")
    if price_jpy is None:
        reasons.append("no_raw_condition_price_available")

    # De-duplicate while preserving order for stable, readable logs.
    reasons = list(dict.fromkeys(reasons))
    identity_verified = not identity_reasons

    if reasons:
        # price_jpy/condition_label are reported even when nothing is
        # written: they are what the page actually showed, and a validate-
        # only run needs them to tell PASS from PASS_FLOOR_UNAVAILABLE.
        return WriteResult(
            written=False,
            reasons=reasons,
            identity_verified=identity_verified,
            identity_reasons=identity_reasons,
            price_jpy=price_jpy,
            condition_label=condition_label,
            card_id=mapping.card_id,
            card_print_id=mapping.card_print_id,
            source_card_mapping_id=mapping.id,
        )

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
        identity_verified=True,
        identity_reasons=[],
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
