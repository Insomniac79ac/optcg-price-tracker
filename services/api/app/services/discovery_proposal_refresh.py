"""Version refreshed discovery evidence in the caller's transaction."""

from collections import Counter
from sqlalchemy import select
from app.models import SourceMappingProposalGroup
from app.services.source_mapping_proposals import (
    ProposalFilters,
    analyse_source_mapping_proposals,
    persist_proposals,
)


def refresh_discovery_proposals(session, source, candidate_ids):
    ids = set(candidate_ids)
    if not ids:
        return {"created": 0, "reused": 0, "superseded": 0, "resolutions": {}}
    session.flush()
    reviewed = set(
        session.scalars(
            select(SourceMappingProposalGroup.source_candidate_id).where(
                SourceMappingProposalGroup.source_candidate_type
                == f"{source}_candidate",
                SourceMappingProposalGroup.source_candidate_id.in_(ids),
                SourceMappingProposalGroup.superseded_at.is_(None),
                SourceMappingProposalGroup.review_status != "pending",
            )
        )
    )
    analysis = analyse_source_mapping_proposals(
        session, ProposalFilters(source=source), build_report=False
    )
    plans = [p for p in analysis.plans if p.source_candidate_id in ids - reviewed]
    result = persist_proposals(session, plans)
    return {
        "created": result.created_groups,
        "reused": result.reused_groups,
        "superseded": result.superseded_groups,
        "resolutions": dict(Counter(p.resolution_status for p in plans)),
        "reviewed_preserved": len(reviewed),
    }
