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

from snkrdunk_collector.card_code_authority import CardCodeAuthority, resolve_expected_card_code
from snkrdunk_collector.identity import (
    RARITY_ABSENT,
    RARITY_UNRECOGNISED,
    normalize_card_name,
)
from snkrdunk_collector.source_rarity_renderings import rendering_for_token
from snkrdunk_collector.release_identity import (
    NO_PRODUCT_LINK,
    ReleaseIdentityResult,
    resolve_release_identity,
)
from snkrdunk_collector.release_reference import RELEASE_NAME_AUTHORITY
from snkrdunk_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    SourceCardMapping,
)

# This collector only ever reads SNKRDUNK, and a rarity rendering is declared
# per source - naming it here keeps the lookup from being source-agnostic by
# accident.
SOURCE_NAME = "snkrdunk"

# card_prints.language uses this app's own short locale codes (e.g. "jp"),
# not the ISO 639-1 codes a page's own <html lang="..."> attribute uses
# (confirmed live: SNKRDUNK's Japanese product pages render lang="ja", not
# lang="jp") - map the former to the latter before comparing so a real jp
# print is never wrongly rejected for its own matching page.
CARD_PRINT_LANGUAGE_TO_HTML_LANG = {"jp": "ja", "en": "en"}


def _authoritative_rarity(
    card_print: CardPrint | None, canonical: CanonicalCard | None
) -> str | None:
    """The rarity a page's own rarity token must match, or None if Atlas
    holds no trustworthy value to compare against.

    `card_prints.official_rarity` first: rarity is a property of a *printing*
    - Bandai publishes it per catalogue entry, and the same card code is
    published at different rarities in different products. That is exactly
    what a SNKRDUNK title shows, so the print's own value is the right
    comparand.

    `canonical_cards.rarity` second, unchanged for every print that predates
    the Bandai catalogue import: those rows carry the same token in both
    columns, so the resolution is a no-op for them and this check keeps
    behaving exactly as it did.

    None third - and None fails the check closed at the call site. That is
    the point of returning it rather than skipping the comparison: a print
    whose rarity Atlas cannot establish must never have a SNKRDUNK page's own
    claim accepted as agreement. Nothing here derives, infers or defaults a
    rarity; the only two answers are a stored value or no answer at all.
    """
    if card_print is not None:
        official = (card_print.official_rarity or "").strip()
        if official:
            return official
    if canonical is not None:
        return canonical.rarity
    return None


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
    # Provenance of the two identity fields that have a hierarchy behind
    # them, so a verification record can state which authority backed it.
    card_code_authority: str | None = None
    card_code_evidence: str | None = None
    card_code_evidence_type: str | None = None
    release_name_match_authority: str | None = None
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
    card_code_authority: CardCodeAuthority | None = None,
    release: ReleaseIdentityResult | None = None,
) -> list[str]:
    """Every check that answers "is the stored product actually the intended
    verified print?" - and nothing that answers "is there a price on it?".

    Each dimension emits its own distinct reason so an audit record can name
    exactly which one failed. Comparison targets are the print's *canonical*
    identity (name/set) plus the print row itself (rarity/treatment/language/
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

    # The expected card code must come from an authority independent of the
    # page being validated - Bandai card-level evidence, or a verified
    # Yuyu-Tei product for the same print. The mapping's own source_card_id
    # is deliberately NOT used: it is a SNKRDUNK-scoped field, and letting it
    # stand as "expected" would have SNKRDUNK supplying both sides of its own
    # check. See card_code_authority.py.
    displayed_code = extracted.get("card_code")
    if card_code_authority is None:
        reasons.append("card_code_authority_missing:no_bandai_or_verified_yuyutei_evidence")
    elif displayed_code != card_code_authority.card_code:
        reasons.append(
            f"card_code_mismatch:displayed={displayed_code},"
            f"expected={card_code_authority.card_code},"
            f"authority={card_code_authority.authority}"
        )

    if card_print is None:
        reasons.append("card_print_missing_for_identity_check")
    else:
        displayed_treatment = extracted.get("treatment")
        # A NULL print treatment is "unclassified", not an expectation of
        # nothing - see extractor.extract_product.
        if card_print.treatment is not None and displayed_treatment != card_print.treatment:
            reasons.append(
                f"treatment_mismatch:displayed={displayed_treatment},expected={card_print.treatment}"
            )

        page_language = extracted.get("page_language")
        expected_html_lang = _expected_html_lang(card_print.language)
        if page_language != expected_html_lang:
            reasons.append(
                f"language_mismatch:displayed={page_language},expected={card_print.language}"
            )

        # RELEASE VALIDATION: the listing's own release NAME, measured against
        # the authoritative names of the product THE PRINT SAYS IT BELONGS TO.
        #
        # The print's `release_product_id` is the authority - see
        # release_identity.py. Coded and uncoded products go through the same
        # path, because the product's identity is its row, not its code.
        #
        # THE CARD CODE'S SET TOKEN IS DELIBERATELY NOT PART OF THIS, and its
        # removal is the fix for the canary's 20 reprint failures rather than
        # a relaxation. `extracted["release_product_code"]` is SNKRDUNK's own
        # inference from the displayed card code (ST01-012 -> "ST-01"); it is
        # a fact about the CARD, never an observation about which product the
        # item shipped in. Comparing it to the print's product asked whether
        # Atlas agrees with a prefix rule, which no page can fail dishonestly
        # and every legitimate reprint fails by construction: staging mapping
        # 88 is ST01-012 printed in OP-03, whose listing release text matched
        # Bandai's official OP-03 name exactly and was still refused. The
        # displayed code stays in the extraction record as evidence; it just
        # no longer decides anything.
        # Passed in rather than resolved here for the same reason
        # `card_code_authority` is: this function stays pure and does no
        # database work, so its callers control the session and its tests can
        # state the identity directly.
        if release is None or release.identity is None:
            reasons.extend(
                release.refusals if release is not None else (NO_PRODUCT_LINK,)
            )
        else:
            observed_release_text = extracted.get("release_text")
            if release.identity.classify_match(observed_release_text) is None:
                reasons.append(
                    f"release_name_mismatch:displayed={observed_release_text},"
                    f"expected={release.identity.describe()},"
                    f"accepted={list(release.identity.accepted_names())},"
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

    # Rarity is checked outside the `canonical` branch above because its
    # authority is the PRINT, not the card - see _authoritative_rarity. The
    # gate itself is unchanged and still fails closed: an absent expected
    # value is a mismatch, never a pass. What changed is only which column
    # supplies that expected value, so a print whose card-level rarity the
    # catalogue deliberately leaves NULL is no longer rejected for a fact
    # Atlas does hold about it.
    expected_rarity_value = _authoritative_rarity(card_print, canonical)
    displayed_rarity = (extracted.get("rarity") or "").strip().upper() or None
    expected_rarity = (expected_rarity_value or "").strip().upper() or None
    rarity_evidence = extracted.get("rarity_evidence")
    # Only consulted for a token this parser could not read; a declared
    # rendering can never override a rarity that WAS read.
    rendering = (
        rendering_for_token(SOURCE_NAME, extracted.get("rarity_token"))
        if rarity_evidence == RARITY_UNRECOGNISED
        else None
    )
    if not expected_rarity:
        # Unchanged: an absent EXPECTED value is a mismatch, never a pass.
        # Atlas holding no rarity for a print is a gap in our catalogue, and a
        # gap cannot corroborate anything.
        reasons.append(
            f"rarity_mismatch:displayed={extracted.get('rarity')},"
            f"expected={expected_rarity_value}"
        )
    elif rarity_evidence == RARITY_ABSENT:
        # THE LISTING PUBLISHES NO RARITY, so this dimension yields no
        # evidence - and absent evidence narrows nothing. It is not a
        # disagreement, and treating it as one refused four canary mappings
        # for a fact SNKRDUNK simply does not print (confirmed on BOTH
        # language pages, where Atlas's own discovery parser also stored an
        # empty detected_rarity).
        #
        # WHY THIS DOES NOT WEAKEN THE GATE. Rarity is corroboration, not
        # identity: exact-print identity is
        # (canonical_card_id, language, release_product_id,
        # official_asset_variant), so within one product and variant there is
        # exactly ONE active verified print and no "other rarity printing"
        # exists for it to be confused with. Every other dimension - card code
        # against an authority independent of this page, release name against
        # the print's own ReleaseProduct, language, treatment, artwork - still
        # applies unchanged. What is NOT waved through is an unreadable rarity
        # claim: that is RARITY_UNRECOGNISED and falls to the branch below.
        pass
    elif rarity_evidence == RARITY_UNRECOGNISED and rendering is not None:
        # A DECLARED source rendering of a compound token - see
        # source_rarity_renderings, which carries the evidence. It is not a
        # value substitution: the token asserts TWO facts and both are checked
        # against Atlas, so this path is stricter than the ordinary
        # single-value comparison, not looser. Either half disagreeing refuses.
        canonical_rarity = ((canonical.rarity if canonical else None) or "").strip().upper() or None
        expected_base = rendering.base_rarity.strip().upper()
        expected_print = rendering.print_rarity.strip().upper()
        if expected_rarity != expected_print or canonical_rarity != expected_base:
            reasons.append(
                f"rarity_rendering_contradicted:token={rendering.source_token},"
                f"expected_print_rarity={rendering.print_rarity},"
                f"got_print_rarity={expected_rarity_value},"
                f"expected_base_rarity={rendering.base_rarity},"
                f"got_base_rarity={canonical.rarity if canonical else None}"
            )
    elif displayed_rarity != expected_rarity:
        reasons.append(
            f"rarity_mismatch:displayed={extracted.get('rarity')},"
            f"expected={expected_rarity_value},"
            f"evidence={rarity_evidence}"
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

    card_code_authority = resolve_expected_card_code(session, card_print)
    # THE PRODUCT THE PRINT SAYS IT BELONGS TO, resolved from the catalogue
    # rather than from a code table - see release_identity.py. Resolved here,
    # where the session lives, and passed in so validate_identity stays pure.
    release = resolve_release_identity(session, card_print)
    release_name_match = (
        release.identity.classify_match(extracted.get("release_text"))
        if release.identity is not None
        else None
    )

    identity_reasons = validate_identity(
        mapping=mapping,
        card_print=card_print,
        canonical=canonical,
        classification=classification,
        extraction=extraction,
        artwork_comparison=artwork_comparison,
        card_code_authority=card_code_authority,
        release=release,
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
            card_code_authority=card_code_authority.authority if card_code_authority else None,
            card_code_evidence=card_code_authority.evidence_url if card_code_authority else None,
            card_code_evidence_type=card_code_authority.evidence_type if card_code_authority else None,
            release_name_match_authority=release_name_match,
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
        card_code_authority=card_code_authority.authority if card_code_authority else None,
        card_code_evidence=card_code_authority.evidence_url if card_code_authority else None,
        card_code_evidence_type=card_code_authority.evidence_type if card_code_authority else None,
        release_name_match_authority=release_name_match,
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
