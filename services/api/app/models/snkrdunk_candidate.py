from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# unmatched: no automated match reaches the "suggested" bar (score < 75, or
#   no candidate cards score above 0 at all) - the pre-migration "pending"
#   state folds in here too (see the migration that introduced this vocabulary).
# suggested: rank_candidate_matches found an unambiguous best match scoring
#   >= 75 - a human still has to confirm it via approve-match.
# ambiguous: the top two ranked matches are within
#   app.services.card_matching.AMBIGUOUS_TIE_MARGIN points of each other -
#   never auto-suggested, always needs a human pick.
# matched: a human approved a match via approve-match (or the pre-existing
#   manual /snkrdunk/candidates/{id}/match endpoint) - a source_card_mappings
#   row exists for it.
# rejected: a human explicitly rejected every candidate match.
MATCH_STATUSES = ("unmatched", "suggested", "ambiguous", "matched", "rejected")


class SnkrdunkCandidate(Base):
    __tablename__ = "snkrdunk_candidates"
    __table_args__ = (
        CheckConstraint(
            "match_status IN ('unmatched', 'suggested', 'ambiguous', 'matched', 'rejected')",
            name="ck_snkrdunk_candidates_match_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("snkrdunk_discovery_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_url: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detected_card_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detected_set_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detected_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detected_variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    match_status: Mapped[str] = mapped_column(
        String(32), default="unmatched", server_default="unmatched", index=True
    )
    matched_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
    )
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Populated by app.services.card_matching.rank_candidate_matches (see
    # GET/POST /admin/snkrdunk-candidates/*) - the latest *automated
    # suggestion*, always 0-100. Distinct from matched_card_id/
    # match_confidence above, which only ever change on an explicit human
    # action (approve-match, or the pre-existing manual /snkrdunk/
    # candidates/{id}/match endpoint) and match_confidence's own legacy
    # 0.0-1.0 scale from that endpoint.
    best_match_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
    )
    best_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_match_confidence_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    match_explanation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ambiguous_matches_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
