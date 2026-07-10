"""Shared candidate persistence + matching helpers, used by both the live
SNKRDUNK discovery job and the manual CSV import job so both paths run
through the exact same dedup/matching/mapping logic.
"""

import logging

from sqlalchemy.orm import Session

from worker.adapters.snkrdunk_discovery import SnkrdunkCandidateData
from worker.matching.opcg_normalizer import (
    extract_card_code,
    extract_rarity,
    extract_set_code,
    extract_variant,
    normalize_title,
)
from worker.matching.snkrdunk_matcher import match_candidate
from worker.models import Card, SnkrdunkCandidate, Source, SourceCardMapping

logger = logging.getLogger(__name__)


def get_snkrdunk_source(db: Session) -> Source:
    source = db.query(Source).filter_by(name="snkrdunk").one_or_none()
    if source is None:
        raise RuntimeError("No 'snkrdunk' row in sources table; run db seed data first.")
    return source


def upsert_candidate(
    db: Session, discovery_run_id: int | None, parsed: SnkrdunkCandidateData
) -> tuple[SnkrdunkCandidate, bool]:
    """Insert or update a candidate row, deduplicated by source_url. Returns
    (candidate, is_new). Descriptive fields are always refreshed, but a prior
    match decision (match_status != 'pending') is left untouched here - the
    caller decides whether to re-run matching."""
    basis_text = parsed.title or parsed.raw_text
    normalized = normalize_title(basis_text)
    card_code = extract_card_code(basis_text)
    set_code = extract_set_code(basis_text, card_code)
    rarity = extract_rarity(basis_text)
    variant = extract_variant(basis_text)

    existing = db.query(SnkrdunkCandidate).filter_by(source_url=parsed.source_url).one_or_none()

    fields = dict(
        discovery_run_id=discovery_run_id,
        title=parsed.title,
        price_jpy=parsed.price_jpy,
        image_url=parsed.image_url,
        listing_count=parsed.listing_count,
        condition_label=parsed.condition_label,
        raw_text=parsed.raw_text,
        normalized_title=normalized,
        detected_card_code=card_code,
        detected_set_code=set_code,
        detected_rarity=rarity,
        detected_variant=variant,
    )

    if existing is None:
        candidate = SnkrdunkCandidate(source_url=parsed.source_url, **fields)
        db.add(candidate)
        db.flush()
        return candidate, True

    for key, value in fields.items():
        setattr(existing, key, value)
    return existing, False


def apply_match(
    db: Session,
    source: Source,
    candidate: SnkrdunkCandidate,
    cards: list[Card],
    auto_match_threshold: float,
) -> str:
    """Runs the shared matcher against `candidate`, records the outcome on
    it, and - only when auto-matched - creates/updates the corresponding
    source_card_mappings row (never overriding a manually verified one)."""
    result = match_candidate(candidate, cards, auto_match_threshold)
    candidate.matched_card_id = result.matched_card_id
    candidate.match_confidence = result.match_confidence
    candidate.match_status = result.match_status

    if result.match_status == "auto_matched":
        existing_mapping = (
            db.query(SourceCardMapping)
            .filter_by(card_id=result.matched_card_id, source_id=source.id)
            .one_or_none()
        )
        if existing_mapping is not None and existing_mapping.manual_verified:
            logger.info(
                "Not overriding manually verified mapping for card_id=%s source=snkrdunk (candidate %s).",
                result.matched_card_id,
                candidate.source_url,
            )
        elif existing_mapping is not None:
            existing_mapping.source_card_id = candidate.detected_card_code or candidate.source_url
            existing_mapping.source_url = candidate.source_url
            existing_mapping.match_confidence = result.match_confidence
            existing_mapping.manual_verified = False
            # Auto-matched (not manually verified) mappings are flagged for
            # admin review rather than silently trusted.
            existing_mapping.review_status = "needs_review"
        else:
            db.add(
                SourceCardMapping(
                    card_id=result.matched_card_id,
                    source_id=source.id,
                    source_card_id=candidate.detected_card_code or candidate.source_url,
                    source_url=candidate.source_url,
                    match_confidence=result.match_confidence,
                    manual_verified=False,
                    review_status="needs_review",
                )
            )

    return result.match_status
