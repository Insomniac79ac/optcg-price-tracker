"""Exact-print confidence and review reporting for source mappings.

The authoritative subject of a modern confidence result is the durable
``SourceCardMapping -> CardPrint -> CanonicalCard -> ReleaseProduct`` lineage.
``card_id`` remains visible as compatibility metadata, but neither its
presence nor its legacy-card match score can improve or reduce authoritative
exact-print confidence.

Quality GETs calculate current results from the database. Explicit non-dry-run
rechecks persist that calculation in the existing confidence columns; there is
no automatic backfill and no mapping state is changed here.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.services.card_matching import (
    calculate_candidate_match,
    confidence_label,
    detect_variant,
    extract_card_code,
    normalize_card_code,
    normalize_text,
    rank_candidate_matches,
)
from app.services.source_mapping_identity import (
    BROKEN,
    EXACT,
    LEGACY_COMPATIBILITY,
    SourceMappingIdentity,
    classify_mapping_identity,
    load_source_mapping_identities,
    load_source_mapping_identity,
)

ISSUE_TYPES = (
    "low_confidence",
    "card_code_mismatch",
    "set_code_mismatch",  # Deprecated legacy compatibility diagnostic.
    "variant_mismatch",  # Deprecated legacy compatibility diagnostic.
    "treatment_mismatch",
    "duplicate_source_url",
    "inactive_with_recent_price",
    "active_without_recent_price",
    "stale_mapping",
    "unverified_mapping",
    "missing_source_url",
    "missing_card_reference",  # Filter compatibility; never emitted for exact.
    "legacy_compatibility_mapping",
    "broken_mapping_identity",
)

CONFIDENCE_LABELS = ("exact", "high", "medium", "low", "very_low", "unknown")
RISK_LEVELS = ("ok", "review", "warning", "critical")

LOW_CONFIDENCE_SCORE_THRESHOLD = 55
STALE_MAPPING_DAYS = 90
RECENT_PRICE_DAYS = 30

COMPATIBILITY_CARD_ABSENT = "absent"
COMPATIBILITY_CARD_PRESENT_VALID = "present_valid"
COMPATIBILITY_CARD_BROKEN_REFERENCE = "broken_reference"
COMPATIBILITY_CARD_CONFLICTING = "conflicting"

CONFIDENCE_SCOPE_EXACT = "exact_print"
CONFIDENCE_SCOPE_COMPATIBILITY = "compatibility_only"
CONFIDENCE_SCOPE_BROKEN = "structural_failure"

_NOT_PROVIDED = object()


@dataclass
class MappingQualityItem:
    mapping_id: int
    identity_classification: str
    confidence_scope: str
    source_name: str | None
    source_url: str | None
    source_card_id: str
    card_print_id: int | None
    canonical_card_id: int | None
    release_product_id: int | None
    compatibility_card_id: int | None
    compatibility_card_status: str
    compatibility_issue_types: list[str]
    compatibility_match_confidence: int | None
    compatibility_match_confidence_label: str | None
    exact_confidence_dimensions: dict[str, Any]
    canonical_card_code: str | None
    canonical_name_en: str | None
    canonical_name_jp: str | None
    print_language: str | None
    release_product_code: str | None
    release_product_name: str | None
    official_asset_variant: str | None
    treatment: str | None
    official_rarity: str | None
    # Deprecated legacy-card presentation fields. They remain readable but
    # never feed exact confidence.
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    is_active: bool
    manual_verified: bool
    review_status: str
    match_confidence: int | None
    match_confidence_label: str
    risk_level: str
    issue_types: list[str]
    explanation: dict[str, list[str]]
    latest_price_observed_at: datetime | None
    last_match_checked_at: datetime | None
    canonical_source_listing_identity: str | None = None
    superseded_at: datetime | None = None
    superseded_by_mapping_id: int | None = None
    supersession_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_source_listing_identity": self.canonical_source_listing_identity,
            "mapping_lifecycle": "current" if self.superseded_at is None else "superseded",
            "superseded_at": self.superseded_at,
            "superseded_by_mapping_id": self.superseded_by_mapping_id,
            "supersession_reason": self.supersession_reason,
            "mapping_id": self.mapping_id,
            "identity_classification": self.identity_classification,
            "confidence_scope": self.confidence_scope,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_card_id": self.source_card_id,
            "card_print_id": self.card_print_id,
            "canonical_card_id": self.canonical_card_id,
            "release_product_id": self.release_product_id,
            "compatibility_card_id": self.compatibility_card_id,
            "compatibility_card_status": self.compatibility_card_status,
            "compatibility_issue_types": self.compatibility_issue_types,
            "compatibility_match_confidence": self.compatibility_match_confidence,
            "compatibility_match_confidence_label": self.compatibility_match_confidence_label,
            "exact_confidence_dimensions": self.exact_confidence_dimensions,
            "canonical_card_code": self.canonical_card_code,
            "canonical_name_en": self.canonical_name_en,
            "canonical_name_jp": self.canonical_name_jp,
            "print_language": self.print_language,
            "release_product_code": self.release_product_code,
            "release_product_name": self.release_product_name,
            "official_asset_variant": self.official_asset_variant,
            "treatment": self.treatment,
            "official_rarity": self.official_rarity,
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "is_active": self.is_active,
            "manual_verified": self.manual_verified,
            "review_status": self.review_status,
            "match_confidence": self.match_confidence,
            "match_confidence_label": self.match_confidence_label,
            "risk_level": self.risk_level,
            "issue_types": self.issue_types,
            "explanation": self.explanation,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat()
                if self.latest_price_observed_at
                else None
            ),
            "last_match_checked_at": (
                self.last_match_checked_at.isoformat()
                if self.last_match_checked_at
                else None
            ),
        }

    def persisted_explanation(self, existing: dict | None) -> dict[str, Any]:
        """Merge confidence data without erasing unrelated evidence namespaces."""
        document = copy.deepcopy(existing) if isinstance(existing, dict) else {}
        document.update(self.explanation)
        document["identity_classification"] = self.identity_classification
        document["confidence_scope"] = self.confidence_scope
        document["exact_confidence_dimensions"] = self.exact_confidence_dimensions
        document["compatibility_card"] = {
            "id": self.compatibility_card_id,
            "status": self.compatibility_card_status,
            "issue_types": self.compatibility_issue_types,
            "match_confidence": self.compatibility_match_confidence,
            "match_confidence_label": self.compatibility_match_confidence_label,
        }
        return document


@dataclass
class MappingSuggestions:
    mapping_id: int
    identity_classification: str
    authoritative_card_print_id: int | None
    suggestion_scope: str
    message: str
    matches: list[Any]


@dataclass
class _MappingCandidateAdapter:
    """The stored listing identity in the legacy card scorer's input shape."""

    title: str | None
    normalized_title: str | None
    raw_text: str | None
    detected_card_code: str | None
    detected_set_code: str | None = None
    detected_rarity: str | None = None
    detected_variant: str | None = None
    condition_label: str | None = None


def _adapt_mapping(mapping: SourceCardMapping) -> _MappingCandidateAdapter:
    source_card_id = mapping.source_card_id or None
    return _MappingCandidateAdapter(
        title=source_card_id,
        normalized_title=source_card_id,
        raw_text=mapping.source_url,
        detected_card_code=(
            normalize_card_code(source_card_id) if source_card_id else None
        ),
    )


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _is_stale(mapping: SourceCardMapping, now: datetime) -> bool:
    cutoff = _naive(now) - timedelta(days=STALE_MAPPING_DAYS)
    if mapping.last_verified_at is not None:
        return _naive(mapping.last_verified_at) < cutoff
    return mapping.created_at is not None and _naive(mapping.created_at) < cutoff


def _risk_level(issue_types: list[str], confidence_label_value: str) -> str:
    if "broken_mapping_identity" in issue_types or "card_code_mismatch" in issue_types:
        return "critical"
    if confidence_label_value == "very_low" or "duplicate_source_url" in issue_types:
        return "critical"
    if (
        "low_confidence" in issue_types
        or "treatment_mismatch" in issue_types
        or "inactive_with_recent_price" in issue_types
        or "active_without_recent_price" in issue_types
    ):
        return "warning"
    if (
        "legacy_compatibility_mapping" in issue_types
        or "stale_mapping" in issue_types
        or "unverified_mapping" in issue_types
        or "missing_source_url" in issue_types
    ):
        return "review"
    return "ok"


def _latest_exact_price_observed_at(
    db: Session, mapping_id: int, source_id: int, card_print_id: int
) -> datetime | None:
    """Latest observation whose complete lineage agrees with this mapping."""
    return db.scalar(
        select(func.max(PriceObservation.observed_at)).where(
            PriceObservation.source_card_mapping_id == mapping_id,
            PriceObservation.source_id == source_id,
            PriceObservation.card_print_id == card_print_id,
        )
    )


def _duplicate_mapping_ids(mappings: list[SourceCardMapping]) -> set[int]:
    groups: dict[tuple[int, str], list[int]] = {}
    for mapping in mappings:
        if mapping.superseded_at is not None:
            continue
        if not mapping.source_url:
            continue
        normalized = mapping.canonical_source_listing_identity or mapping.source_url.strip().lower()
        if normalized:
            groups.setdefault((mapping.source_id, normalized), []).append(mapping.id)
    return {mapping_id for ids in groups.values() if len(ids) > 1 for mapping_id in ids}


def _identity_for_mapping(
    db: Session,
    mapping: SourceCardMapping,
    *,
    card: Card | None = None,
    source: Source | None = None,
) -> SourceMappingIdentity:
    if mapping.id is not None:
        identity = load_source_mapping_identity(db, mapping.id)
        if identity is not None:
            return identity

    # Import validation creates a transient legacy row. It still goes through
    # the shared classifier rather than acquiring a local definition.
    source = source or db.get(Source, mapping.source_id)
    if card is None and mapping.card_id is not None:
        card = db.get(Card, mapping.card_id)
    classification = classify_mapping_identity(
        mapping,
        source=source,
        card_print=None,
        canonical_card=None,
        release_product=None,
        compatibility_card=card,
    )
    return SourceMappingIdentity(
        mapping=mapping,
        source=source,
        card_print=None,
        canonical_card=None,
        release_product=None,
        compatibility_card=card,
        classification=classification,
    )


def _compatibility_card_diagnostics(
    identity: SourceMappingIdentity,
) -> tuple[str, list[str], int | None, str | None]:
    mapping = identity.mapping
    compatibility_card = identity.compatibility_card
    if mapping.card_id is None:
        return COMPATIBILITY_CARD_ABSENT, [], None, None
    if compatibility_card is None:
        return (
            COMPATIBILITY_CARD_BROKEN_REFERENCE,
            ["compatibility_card_reference_broken"],
            None,
            None,
        )

    issues: list[str] = []
    status = COMPATIBILITY_CARD_PRESENT_VALID
    canonical = identity.canonical_card
    card_print = identity.card_print
    if canonical is not None:
        compatibility_code = normalize_card_code(compatibility_card.card_code)
        canonical_code = normalize_card_code(canonical.card_code)
        if compatibility_code != canonical_code:
            issues.append("compatibility_card_code_conflict")
    if (
        card_print is not None
        and compatibility_card.language
        and card_print.language
        and compatibility_card.language.lower() != card_print.language.lower()
    ):
        issues.append("compatibility_card_language_conflict")
    if issues:
        status = COMPATIBILITY_CARD_CONFLICTING

    result = calculate_candidate_match(_adapt_mapping(mapping), compatibility_card)
    return status, issues, result.score, result.confidence_label


def _expected_release_codes(identity: SourceMappingIdentity) -> list[str]:
    values = [
        identity.card_print.release_product_code if identity.card_print else None,
        identity.release_product.official_code if identity.release_product else None,
        identity.release_product.source_series_id if identity.release_product else None,
    ]
    return list(dict.fromkeys(value for value in values if value))


def _contains_standalone_code(text: str | None, code: str) -> bool:
    """Exact separator-tolerant token check; a card-code prefix is excluded."""
    if not text:
        return False
    compact = re.sub(r"[-_\s]", "", code.upper())
    match = re.fullmatch(r"([A-Z]+)(\d+)", compact)
    if match is None:
        return False
    letters, digits = match.groups()
    pattern = rf"(?<![A-Z0-9]){re.escape(letters)}[-_\s]?{digits}(?![-A-Z0-9])"
    return re.search(pattern, text.upper()) is not None


def _observed_asset_variant(identity: SourceMappingIdentity) -> str | None:
    mapping = identity.mapping
    canonical = identity.canonical_card
    if canonical is None or not mapping.source_url:
        return None
    code = re.escape(canonical.card_code)
    match = re.search(rf"{code}[_-]([pr][1-9][0-9]*)\b", mapping.source_url, re.I)
    return match.group(1).lower() if match else None


def _exact_confidence(
    identity: SourceMappingIdentity,
) -> tuple[int | None, str, list[str], dict[str, list[str]], dict[str, Any]]:
    mapping = identity.mapping
    card_print = identity.card_print
    canonical = identity.canonical_card
    product = identity.release_product
    assert card_print is not None and canonical is not None

    issue_types: list[str] = []
    positive: list[str] = []
    negative: list[str] = []
    caps_applied: list[str] = []
    dimensions: dict[str, Any] = {}

    observed_code = extract_card_code(mapping.source_card_id)
    code_origin = "source_card_id"
    if observed_code is None:
        observed_code = extract_card_code(mapping.source_url)
        code_origin = "source_url"
    expected_code = normalize_card_code(canonical.card_code)
    observed_code_norm = normalize_card_code(observed_code)
    score: int | None
    if observed_code_norm is None:
        score = None
        dimensions["card_code"] = {
            "status": "not_observed",
            "expected": canonical.card_code,
            "observed": None,
        }
    elif observed_code_norm == expected_code:
        score = 60 if code_origin == "source_card_id" else 50
        positive.append(
            "exact canonical card_code match"
            if code_origin == "source_card_id"
            else "canonical card_code match from source_url"
        )
        dimensions["card_code"] = {
            "status": "match",
            "expected": canonical.card_code,
            "observed": observed_code,
            "evidence": code_origin,
        }
    else:
        score = 0
        issue_types.append("card_code_mismatch")
        negative.append("canonical card_code mismatch")
        dimensions["card_code"] = {
            "status": "mismatch",
            "expected": canonical.card_code,
            "observed": observed_code,
            "evidence": code_origin,
        }

    release_codes = _expected_release_codes(identity)
    observed_release = next(
        (code for code in release_codes if _contains_standalone_code(mapping.source_url, code)),
        None,
    )
    dimensions["release_product"] = {
        "status": "match" if observed_release else "not_observed",
        "release_product_id": identity.release_product_id,
        "expected_codes": release_codes,
        "observed": observed_release,
        "name": product.display_name if product else None,
    }
    if observed_release and score is not None:
        score += 10
        positive.append("exact release_product code present in source_url")

    observed_asset_variant = _observed_asset_variant(identity)
    expected_asset_variant = card_print.official_asset_variant
    asset_status = "not_observed"
    if observed_asset_variant is not None:
        asset_status = "match" if observed_asset_variant == expected_asset_variant else "mismatch"
    dimensions["official_asset_variant"] = {
        "status": asset_status,
        "expected": expected_asset_variant,
        "observed": observed_asset_variant,
    }

    listing_text = " ".join(
        value for value in (mapping.source_card_id, mapping.source_url) if value
    )
    observed_treatment = detect_variant(listing_text)
    expected_treatment = normalize_text(card_print.treatment) or None
    treatment_status = "not_observed"
    if observed_treatment is not None and expected_treatment is not None:
        if observed_treatment == expected_treatment:
            treatment_status = "match"
            if score is not None:
                score += 12
            positive.append("descriptive treatment match")
        else:
            treatment_status = "mismatch"
            if score is not None:
                score -= 20
            issue_types.append("treatment_mismatch")
            negative.append("descriptive treatment mismatch")
    dimensions["treatment"] = {
        "status": treatment_status,
        "expected": card_print.treatment,
        "observed": observed_treatment,
    }

    # The mapping row stores no listing title, rarity, or language assertion.
    # URL alphabet and canonical original-set metadata are not substitutes.
    dimensions["language"] = {
        "status": "not_observed",
        "expected": card_print.language,
        "observed": None,
    }
    dimensions["official_name"] = {
        "status": "not_observed",
        "expected": card_print.official_name,
        "observed": None,
    }
    dimensions["official_rarity"] = {
        "status": "not_observed",
        "expected": card_print.official_rarity,
        "observed": None,
    }
    dimensions["source_listing_identity"] = {
        "status": "present" if mapping.source_card_id else "missing",
        "source_card_id": mapping.source_card_id,
        "source_url_present": bool(mapping.source_url),
    }

    if score is None:
        label = "unknown"
    else:
        score = max(0, min(100, score))
        label = confidence_label(score)
        if score < LOW_CONFIDENCE_SCORE_THRESHOLD:
            issue_types.append("low_confidence")

    return (
        score,
        label,
        issue_types,
        {"positive": positive, "negative": negative, "caps_applied": caps_applied},
        dimensions,
    )


def evaluate_source_mapping(
    db: Session,
    mapping: SourceCardMapping,
    *,
    card: Card | None = None,
    source: Source | None = None,
    identity: SourceMappingIdentity | None = None,
    latest_price_observed_at: datetime | None | object = _NOT_PROVIDED,
    is_duplicate: bool | None = None,
    now: datetime | None = None,
) -> MappingQualityItem:
    """Evaluate current exact identity without consulting persisted scores."""
    now = now or datetime.now(timezone.utc)
    identity = identity or _identity_for_mapping(db, mapping, card=card, source=source)
    source = identity.source
    compatibility_card = identity.compatibility_card

    compatibility_status, compatibility_issues, compatibility_score, compatibility_label = (
        _compatibility_card_diagnostics(identity)
    )

    issue_types: list[str] = []
    score: int | None = None
    label = "unknown"
    explanation = {"positive": [], "negative": [], "caps_applied": []}
    exact_dimensions: dict[str, Any] = {}

    if identity.classification == EXACT:
        score, label, exact_issues, explanation, exact_dimensions = _exact_confidence(identity)
        issue_types.extend(exact_issues)
        confidence_scope = CONFIDENCE_SCOPE_EXACT
    elif identity.classification == LEGACY_COMPATIBILITY:
        confidence_scope = CONFIDENCE_SCOPE_COMPATIBILITY
        issue_types.append("legacy_compatibility_mapping")
        explanation["negative"].append(
            "compatibility-only mapping has no authoritative CardPrint lineage"
        )
    else:
        confidence_scope = CONFIDENCE_SCOPE_BROKEN
        issue_types.append("broken_mapping_identity")
        explanation["negative"].append("mapping identity lineage is structurally broken")

    if not mapping.source_url:
        issue_types.append("missing_source_url")
    if is_duplicate is None:
        source_mappings = db.scalars(
            select(SourceCardMapping).where(SourceCardMapping.source_id == mapping.source_id)
        ).all()
        is_duplicate = mapping.id in _duplicate_mapping_ids(list(source_mappings))
    if is_duplicate:
        issue_types.append("duplicate_source_url")

    if identity.classification == EXACT:
        if latest_price_observed_at is _NOT_PROVIDED:
            latest_price_observed_at = _latest_exact_price_observed_at(
                db, mapping.id, mapping.source_id, identity.card_print_id
            )
        recent_cutoff = _naive(now) - timedelta(days=RECENT_PRICE_DAYS)
        has_recent_price = (
            latest_price_observed_at is not None
            and _naive(latest_price_observed_at) >= recent_cutoff
        )
        if not mapping.is_active and has_recent_price:
            issue_types.append("inactive_with_recent_price")
        if mapping.is_active and not has_recent_price:
            issue_types.append("active_without_recent_price")
    else:
        # Historical observations cannot establish an exact physical print.
        latest_price_observed_at = None

    if _is_stale(mapping, now):
        issue_types.append("stale_mapping")
    if not mapping.manual_verified:
        issue_types.append("unverified_mapping")

    risk_level = _risk_level(issue_types, label)
    card_print = identity.card_print
    canonical = identity.canonical_card
    release_product = identity.release_product

    return MappingQualityItem(
        canonical_source_listing_identity=mapping.canonical_source_listing_identity,
        superseded_at=mapping.superseded_at,
        superseded_by_mapping_id=mapping.superseded_by_mapping_id,
        supersession_reason=mapping.supersession_reason,
        mapping_id=mapping.id,
        identity_classification=identity.classification,
        confidence_scope=confidence_scope,
        source_name=source.name if source is not None else None,
        source_url=mapping.source_url,
        source_card_id=mapping.source_card_id,
        card_print_id=identity.card_print_id,
        canonical_card_id=identity.canonical_card_id,
        release_product_id=identity.release_product_id,
        compatibility_card_id=mapping.card_id,
        compatibility_card_status=compatibility_status,
        compatibility_issue_types=compatibility_issues,
        compatibility_match_confidence=compatibility_score,
        compatibility_match_confidence_label=compatibility_label,
        exact_confidence_dimensions=exact_dimensions,
        canonical_card_code=canonical.card_code if canonical else None,
        canonical_name_en=canonical.name_en if canonical else None,
        canonical_name_jp=canonical.name_jp if canonical else None,
        print_language=card_print.language if card_print else None,
        release_product_code=(
            release_product.official_code
            if release_product is not None
            else (card_print.release_product_code if card_print else None)
        ),
        release_product_name=release_product.display_name if release_product else None,
        official_asset_variant=card_print.official_asset_variant if card_print else None,
        treatment=card_print.treatment if card_print else None,
        official_rarity=card_print.official_rarity if card_print else None,
        card_id=mapping.card_id,
        card_code=compatibility_card.card_code if compatibility_card else None,
        name_en=compatibility_card.name_en if compatibility_card else None,
        name_jp=compatibility_card.name_jp if compatibility_card else None,
        set_code=compatibility_card.set_code if compatibility_card else None,
        rarity=compatibility_card.rarity if compatibility_card else None,
        variant=compatibility_card.variant if compatibility_card else None,
        is_active=mapping.is_active,
        manual_verified=mapping.manual_verified,
        review_status=mapping.review_status,
        match_confidence=score,
        match_confidence_label=label,
        risk_level=risk_level,
        issue_types=list(dict.fromkeys(issue_types)),
        explanation=explanation,
        latest_price_observed_at=(
            latest_price_observed_at
            if isinstance(latest_price_observed_at, datetime)
            else None
        ),
        last_match_checked_at=mapping.last_match_checked_at,
    )


@dataclass
class MappingQualityFilters:
    source: str | None = None
    review_status: str | None = None
    is_active: bool | None = None
    manual_verified: bool | None = None
    confidence_label: str | None = None
    risk_level: str | None = None
    issue_type: str | None = None
    q: str | None = None


def _base_query(filters: MappingQualityFilters):
    query = (
        select(SourceCardMapping)
        .outerjoin(Card, SourceCardMapping.card_id == Card.id)
        .outerjoin(CardPrint, SourceCardMapping.card_print_id == CardPrint.id)
        .outerjoin(CanonicalCard, CardPrint.canonical_card_id == CanonicalCard.id)
        .outerjoin(ReleaseProduct, CardPrint.release_product_id == ReleaseProduct.id)
        .join(Source, SourceCardMapping.source_id == Source.id)
    )
    conditions = []
    if filters.review_status is not None:
        conditions.append(SourceCardMapping.review_status == filters.review_status)
    if filters.is_active is not None:
        conditions.append(SourceCardMapping.is_active == filters.is_active)
    if filters.manual_verified is not None:
        conditions.append(SourceCardMapping.manual_verified == filters.manual_verified)
    if filters.source is not None:
        conditions.append(Source.name == filters.source)
    if filters.q:
        like = f"%{filters.q}%"
        conditions.append(
            (SourceCardMapping.source_url.ilike(like))
            | (SourceCardMapping.source_card_id.ilike(like))
            | (Card.card_code.ilike(like))
            | (CanonicalCard.card_code.ilike(like))
            | (ReleaseProduct.official_code.ilike(like))
            | (ReleaseProduct.display_name.ilike(like))
        )
    if conditions:
        query = query.where(*conditions)
    return query


def _evaluate_mapping_batch(
    db: Session, mappings: list[SourceCardMapping], *, now: datetime
) -> list[MappingQualityItem]:
    if not mappings:
        return []
    mapping_ids = [mapping.id for mapping in mappings]
    identities = load_source_mapping_identities(
        db, conditions=(SourceCardMapping.id.in_(mapping_ids),)
    )
    identities_by_id = {
        identity.source_card_mapping_id: identity for identity in identities
    }

    exact_keys = {
        (identity.source_card_mapping_id, identity.source_id, identity.card_print_id)
        for identity in identities
        if identity.classification == EXACT and identity.card_print_id is not None
    }
    latest_by_key: dict[tuple[int, int, int], datetime] = {}
    if exact_keys:
        exact_mapping_ids = [key[0] for key in exact_keys]
        price_rows = db.execute(
            select(
                PriceObservation.source_card_mapping_id,
                PriceObservation.source_id,
                PriceObservation.card_print_id,
                func.max(PriceObservation.observed_at),
            )
            .where(PriceObservation.source_card_mapping_id.in_(exact_mapping_ids))
            .group_by(
                PriceObservation.source_card_mapping_id,
                PriceObservation.source_id,
                PriceObservation.card_print_id,
            )
        ).all()
        latest_by_key = {
            (row[0], row[1], row[2]): row[3]
            for row in price_rows
            if (row[0], row[1], row[2]) in exact_keys
        }

    source_ids = {mapping.source_id for mapping in mappings}
    duplicate_ids: set[int] = set()
    for source_id in source_ids:
        source_mappings = list(
            db.scalars(
                select(SourceCardMapping).where(SourceCardMapping.source_id == source_id)
            ).all()
        )
        duplicate_ids |= _duplicate_mapping_ids(source_mappings)

    items: list[MappingQualityItem] = []
    for mapping in mappings:
        identity = identities_by_id[mapping.id]
        key = (mapping.id, mapping.source_id, identity.card_print_id)
        items.append(
            evaluate_source_mapping(
                db,
                mapping,
                identity=identity,
                latest_price_observed_at=latest_by_key.get(key),
                is_duplicate=mapping.id in duplicate_ids,
                now=now,
            )
        )
    return items


def _evaluate_all(db: Session, filters: MappingQualityFilters) -> list[MappingQualityItem]:
    mappings = list(db.scalars(_base_query(filters)).all())
    items = _evaluate_mapping_batch(db, mappings, now=datetime.now(timezone.utc))
    if filters.confidence_label is not None:
        items = [
            item
            for item in items
            if item.match_confidence_label == filters.confidence_label
        ]
    if filters.risk_level is not None:
        items = [item for item in items if item.risk_level == filters.risk_level]
    if filters.issue_type is not None:
        items = [item for item in items if filters.issue_type in item.issue_types]
    return items


def evaluate_source_mappings(
    db: Session, filters: MappingQualityFilters, limit: int = 100, offset: int = 0
) -> tuple[list[MappingQualityItem], int, dict[str, int]]:
    items = _evaluate_all(db, filters)
    summary = _summarize(items)
    total = len(items)
    return items[offset : offset + limit], total, summary


def _summarize(items: list[MappingQualityItem]) -> dict[str, int]:
    def count_issue(issue_type: str) -> int:
        return sum(1 for item in items if issue_type in item.issue_types)

    return {
        "total_mappings": len(items),
        "exact_mapping_count": sum(item.identity_classification == EXACT for item in items),
        "legacy_compatibility_mapping_count": sum(
            item.identity_classification == LEGACY_COMPATIBILITY for item in items
        ),
        "broken_mapping_count": sum(item.identity_classification == BROKEN for item in items),
        "ok_count": sum(item.risk_level == "ok" for item in items),
        "review_count": sum(item.risk_level == "review" for item in items),
        "warning_count": sum(item.risk_level == "warning" for item in items),
        "critical_count": sum(item.risk_level == "critical" for item in items),
        "low_confidence_count": count_issue("low_confidence"),
        "duplicate_source_url_count": count_issue("duplicate_source_url"),
        "stale_mapping_count": count_issue("stale_mapping"),
        "unverified_count": count_issue("unverified_mapping"),
        "inactive_with_recent_price_count": count_issue("inactive_with_recent_price"),
        "active_without_recent_price_count": count_issue("active_without_recent_price"),
    }


def summarize_mapping_quality(db: Session) -> dict[str, int]:
    return _summarize(_evaluate_all(db, MappingQualityFilters()))


@dataclass
class RecheckSummary:
    selected: int = 0
    would_update: int = 0
    updated: int = 0
    ok: int = 0
    review: int = 0
    warning: int = 0
    critical: int = 0


def bulk_recheck_source_mappings(
    db: Session,
    filters: MappingQualityFilters,
    limit: int = 100,
    dry_run: bool = True,
) -> tuple[RecheckSummary, list[MappingQualityItem]]:
    """Recalculate current semantics; persist only when explicitly requested."""
    mappings = list(db.scalars(_base_query(filters).limit(limit)).all())
    preview = _evaluate_mapping_batch(db, mappings, now=datetime.now(timezone.utc))
    summary = RecheckSummary(selected=len(mappings))

    for mapping, item in zip(mappings, preview, strict=True):
        summary.would_update += 1
        setattr(summary, item.risk_level, getattr(summary, item.risk_level) + 1)
        if not dry_run:
            mapping.match_confidence = item.match_confidence
            mapping.match_confidence_label = item.match_confidence_label
            mapping.match_explanation_json = item.persisted_explanation(
                mapping.match_explanation_json
            )
            mapping.last_match_checked_at = datetime.now(timezone.utc)
            summary.updated += 1

    if not dry_run:
        db.commit()
    return summary, preview


def suggested_cards_for_mapping(
    db: Session, mapping: SourceCardMapping, limit: int = 10
) -> MappingSuggestions:
    """Return only compatibility suggestions; never imply print replacement."""
    identity = _identity_for_mapping(db, mapping)
    if identity.classification == EXACT:
        return MappingSuggestions(
            mapping_id=mapping.id,
            identity_classification=EXACT,
            authoritative_card_print_id=identity.card_print_id,
            suggestion_scope="exact_print_review_required",
            message=(
                "No legacy Card suggestion is authoritative for this mapping. "
                "Changing card_id would not change its CardPrint pricing identity; "
                "exact-print suggestions require a separate review workflow."
            ),
            matches=[],
        )
    if identity.classification == BROKEN:
        return MappingSuggestions(
            mapping_id=mapping.id,
            identity_classification=BROKEN,
            authoritative_card_print_id=None,
            suggestion_scope="structural_repair_required",
            message=(
                "This mapping has broken identity lineage. No automatic or legacy "
                "Card suggestion can repair authoritative pricing identity."
            ),
            matches=[],
        )
    return MappingSuggestions(
        mapping_id=mapping.id,
        identity_classification=LEGACY_COMPATIBILITY,
        authoritative_card_print_id=None,
        suggestion_scope="legacy_compatibility_only",
        message=(
            "Suggestions below concern only the legacy card_id compatibility pointer; "
            "they do not establish or change authoritative CardPrint identity."
        ),
        matches=rank_candidate_matches(db, _adapt_mapping(mapping), limit=limit),
    )
