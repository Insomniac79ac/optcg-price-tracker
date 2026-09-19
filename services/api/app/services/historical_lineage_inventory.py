"""Read-only inventory of historical market-pricing lineage.

This module classifies existing source mappings and price observations. It
does not repair, infer or assign lineage. In particular, a current mapping is
never historical proof by itself: a lineage-less observation is only called a
``unique_evidence_candidate`` when an immutable URL retained by its raw
snapshot or SNKRDUNK candidate resolves by deterministic source-listing
identity to one valid exact mapping. Identity is exact source-and-URL equality
except for the two published SNKRDUNK URL forms, whose shared numeric listing
ID is already the repository's exact (non-fuzzy) identity rule. That label is
an inventory finding, not permission to backfill.

Only narrow columns are selected. RawSnapshot.raw_content and candidate text
or image fields are deliberately never loaded.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Card,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.services.snkrdunk_urls import listing_id as snkrdunk_listing_id

MAPPING_CATEGORIES = (
    "exact_valid",
    "exact_but_invalid",
    "legacy_card_only",
    "entityless",
)

OBSERVATION_CATEGORIES = (
    "exact",
    "exact_broken",
    "unique_evidence_candidate",
    "ambiguous",
    "legacy_only",
    "entityless",
)

PROVENANCE_COUNTERS = (
    "raw_snapshot_references",
    "resolved_raw_snapshots",
    "candidate_references",
    "resolved_candidates",
    "observations_with_usable_url_evidence",
)

PROVENANCE_NOTICE = (
    "unique_evidence_candidate is not automatically safe to backfill; current "
    "mapping state is mutable and is not historical proof"
)


@dataclass(frozen=True)
class HistoricalLineageInventory:
    generated_at: str
    sample_limit: int
    mappings: dict
    observations: dict
    read_only: bool = True

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "read_only": self.read_only,
            "provenance_notice": PROVENANCE_NOTICE,
            "sample_limit": self.sample_limit,
            "mappings": self.mappings,
            "observations": self.observations,
        }


@dataclass(frozen=True)
class _MappingRow:
    id: int
    card_id: int | None
    source_id: int
    card_print_id: int | None
    source_url: str | None


@dataclass(frozen=True)
class _ObservationRow:
    id: int
    card_id: int | None
    source_id: int
    source_card_mapping_id: int | None
    card_print_id: int | None
    raw_snapshot_id: int | None
    candidate_id: int | None


@dataclass(frozen=True)
class _SnapshotRow:
    source_id: int
    source_url: str


_ProvenanceKey = tuple[int, str, str]


def _category_summary(categories: tuple[str, ...]) -> dict[str, dict]:
    return {category: {"count": 0, "sample_ids": []} for category in categories}


def _record_category(summary: dict[str, dict], category: str, row_id: int, limit: int) -> None:
    bucket = summary[category]
    bucket["count"] += 1
    if len(bucket["sample_ids"]) < limit:
        bucket["sample_ids"].append(row_id)


def _source_label(source_id: int, sources: dict[int, str]) -> str:
    return sources.get(source_id, f"<missing:{source_id}>")


def _provenance_key(
    source_id: int, source_url: str | None, sources: dict[int, str]
) -> _ProvenanceKey | None:
    """Return a strict, source-scoped key for immutable URL evidence.

    SNKRDUNK deliberately retains its discovered URL on candidates while a
    mapping stores the language-specific published URL for the same numeric
    listing. Parsing that shared listing ID is an existing exact repository
    rule, not identity inference. Every other source uses the stored URL
    string exactly; unknown/blank shapes fail closed.
    """
    if source_url is None or not source_url.strip():
        return None
    if sources.get(source_id) == "snkrdunk":
        parsed_listing_id = snkrdunk_listing_id(source_url)
        if parsed_listing_id is not None:
            return (source_id, "snkrdunk_listing_id", parsed_listing_id)
    return (source_id, "exact_source_url", source_url)


def _render_source_counts(
    counts: dict[str, Counter], categories: tuple[str, ...]
) -> dict[str, dict]:
    return {
        source: {
            "total": sum(source_counts.values()),
            "categories": {
                category: source_counts.get(category, 0) for category in categories
            },
        }
        for source, source_counts in sorted(counts.items())
    }


def _classify_mapping(
    mapping: _MappingRow,
    *,
    card_ids: set[int],
    print_ids: set[int],
    source_ids: set[int],
) -> str:
    if mapping.card_print_id is not None:
        if mapping.card_print_id in print_ids and mapping.source_id in source_ids:
            return "exact_valid"
        return "exact_but_invalid"
    if mapping.card_id is not None and mapping.card_id in card_ids:
        return "legacy_card_only"
    return "entityless"


def _compatibility_conflicts(
    mappings: list[_MappingRow], print_ids: set[int], sample_limit: int
) -> dict[str, object]:
    cards_by_print: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    prints_by_card: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    for mapping in mappings:
        if mapping.card_id is None or mapping.card_print_id not in print_ids:
            continue
        cards_by_print[mapping.card_print_id][mapping.card_id].append(mapping.id)
        prints_by_card[mapping.card_id][mapping.card_print_id].append(mapping.id)

    print_conflicts = []
    for print_id, card_groups in sorted(cards_by_print.items()):
        if len(card_groups) <= 1:
            continue
        mapping_ids = sorted(
            mapping_id
            for group_mapping_ids in card_groups.values()
            for mapping_id in group_mapping_ids
        )
        print_conflicts.append(
            {
                "card_print_id": print_id,
                "card_id_count": len(card_groups),
                "card_ids": sorted(card_groups)[:sample_limit],
                "mapping_count": len(mapping_ids),
                "mapping_ids": mapping_ids[:sample_limit],
            }
        )

    card_conflicts = []
    for card_id, print_groups in sorted(prints_by_card.items()):
        if len(print_groups) <= 1:
            continue
        mapping_ids = sorted(
            mapping_id
            for group_mapping_ids in print_groups.values()
            for mapping_id in group_mapping_ids
        )
        card_conflicts.append(
            {
                "card_id": card_id,
                "card_print_id_count": len(print_groups),
                "card_print_ids": sorted(print_groups)[:sample_limit],
                "mapping_count": len(mapping_ids),
                "mapping_ids": mapping_ids[:sample_limit],
            }
        )

    return {
        "total_groups": len(print_conflicts) + len(card_conflicts),
        "card_print_with_multiple_card_ids": {
            "count": len(print_conflicts),
            "samples": print_conflicts[:sample_limit],
        },
        "card_with_multiple_card_print_ids": {
            "count": len(card_conflicts),
            "samples": card_conflicts[:sample_limit],
        },
    }


def _classify_observation(
    observation: _ObservationRow,
    *,
    mappings_by_id: dict[int, _MappingRow],
    mapping_categories: dict[int, str],
    mappings_by_provenance: dict[_ProvenanceKey, list[_MappingRow]],
    snapshots_by_id: dict[int, _SnapshotRow],
    candidates_by_id: dict[int, str],
    sources: dict[int, str],
    card_ids: set[int],
    print_ids: set[int],
    provenance_counts: Counter,
) -> str:
    attempted_exact = (
        observation.card_print_id is not None
        or observation.source_card_mapping_id is not None
    )
    if attempted_exact:
        mapping = mappings_by_id.get(observation.source_card_mapping_id)
        if (
            observation.card_print_id in print_ids
            and observation.source_id in sources
            and mapping is not None
            and mapping_categories[mapping.id] == "exact_valid"
            and mapping.source_id == observation.source_id
            and mapping.card_print_id == observation.card_print_id
        ):
            return "exact"
        return "exact_broken"

    signals: list[_ProvenanceKey] = []
    inconsistent_signal = False

    if observation.raw_snapshot_id is not None:
        provenance_counts["raw_snapshot_references"] += 1
        snapshot = snapshots_by_id.get(observation.raw_snapshot_id)
        if snapshot is not None:
            provenance_counts["resolved_raw_snapshots"] += 1
            signal = _provenance_key(
                snapshot.source_id, snapshot.source_url, sources
            )
            if signal is not None:
                signals.append(signal)
            if snapshot.source_id != observation.source_id:
                inconsistent_signal = True

    if observation.candidate_id is not None:
        provenance_counts["candidate_references"] += 1
        candidate_url = candidates_by_id.get(observation.candidate_id)
        if candidate_url is not None:
            provenance_counts["resolved_candidates"] += 1
            signal = _provenance_key(
                observation.source_id, candidate_url, sources
            )
            if signal is not None:
                signals.append(signal)
            if sources.get(observation.source_id) != "snkrdunk":
                inconsistent_signal = True

    if not signals:
        if observation.card_id is not None and observation.card_id in card_ids:
            return "legacy_only"
        return "entityless"

    provenance_counts["observations_with_usable_url_evidence"] += 1
    matched_mapping_ids: set[int] = set()
    all_signals_uniquely_resolved = True
    for signal in set(signals):
        matches = mappings_by_provenance.get(signal, [])
        if len(matches) != 1:
            all_signals_uniquely_resolved = False
            continue
        matched_mapping_ids.add(matches[0].id)

    if (
        inconsistent_signal
        or not all_signals_uniquely_resolved
        or len(matched_mapping_ids) != 1
    ):
        return "ambiguous"

    mapping = mappings_by_id[next(iter(matched_mapping_ids))]
    if mapping_categories[mapping.id] != "exact_valid":
        return "ambiguous"
    if (
        observation.card_id is not None
        and mapping.card_id is not None
        and observation.card_id != mapping.card_id
    ):
        return "ambiguous"
    return "unique_evidence_candidate"


def build_historical_lineage_inventory(
    db: Session,
    *,
    sample_limit: int = 10,
    now: datetime | None = None,
) -> HistoricalLineageInventory:
    """Return a structured inventory using SELECTs only.

    ``db.no_autoflush`` is intentional: even a caller with unrelated pending
    ORM changes cannot cause this inventory call to flush them.
    """
    if sample_limit < 0:
        raise ValueError("sample_limit must be >= 0")

    with db.no_autoflush:
        sources = dict(db.execute(select(Source.id, Source.name)).all())
        source_ids = set(sources)
        card_ids = set(db.scalars(select(Card.id)).all())
        print_ids = set(db.scalars(select(CardPrint.id)).all())

        mappings = [
            _MappingRow(*row)
            for row in db.execute(
                select(
                    SourceCardMapping.id,
                    SourceCardMapping.card_id,
                    SourceCardMapping.source_id,
                    SourceCardMapping.card_print_id,
                    SourceCardMapping.source_url,
                ).order_by(SourceCardMapping.id)
            ).all()
        ]
        mappings_by_id = {mapping.id: mapping for mapping in mappings}

        mapping_summary = _category_summary(MAPPING_CATEGORIES)
        mapping_source_counts: dict[str, Counter] = defaultdict(Counter)
        mapping_categories: dict[int, str] = {}
        mappings_by_provenance: dict[_ProvenanceKey, list[_MappingRow]] = defaultdict(
            list
        )

        for mapping in mappings:
            category = _classify_mapping(
                mapping,
                card_ids=card_ids,
                print_ids=print_ids,
                source_ids=source_ids,
            )
            mapping_categories[mapping.id] = category
            _record_category(mapping_summary, category, mapping.id, sample_limit)
            mapping_source_counts[_source_label(mapping.source_id, sources)][category] += 1
            provenance_key = _provenance_key(
                mapping.source_id, mapping.source_url, sources
            )
            if provenance_key is not None:
                mappings_by_provenance[provenance_key].append(mapping)

        observations = [
            _ObservationRow(*row)
            for row in db.execute(
                select(
                    PriceObservation.id,
                    PriceObservation.card_id,
                    PriceObservation.source_id,
                    PriceObservation.source_card_mapping_id,
                    PriceObservation.card_print_id,
                    PriceObservation.raw_snapshot_id,
                    PriceObservation.candidate_id,
                ).order_by(PriceObservation.id)
            ).all()
        ]
        referenced_snapshot_ids = {
            observation.raw_snapshot_id
            for observation in observations
            if observation.raw_snapshot_id is not None
        }
        referenced_candidate_ids = {
            observation.candidate_id
            for observation in observations
            if observation.candidate_id is not None
        }
        snapshots_by_id = {
            snapshot_id: _SnapshotRow(source_id, source_url)
            for snapshot_id, source_id, source_url in db.execute(
                select(RawSnapshot.id, RawSnapshot.source_id, RawSnapshot.source_url).where(
                    RawSnapshot.id.in_(referenced_snapshot_ids)
                )
            ).all()
        }
        candidates_by_id = dict(
            db.execute(
                select(SnkrdunkCandidate.id, SnkrdunkCandidate.source_url).where(
                    SnkrdunkCandidate.id.in_(referenced_candidate_ids)
                )
            ).all()
        )

        observation_summary = _category_summary(OBSERVATION_CATEGORIES)
        observation_source_counts: dict[str, Counter] = defaultdict(Counter)
        provenance_counts: Counter = Counter({name: 0 for name in PROVENANCE_COUNTERS})

        for observation in observations:
            category = _classify_observation(
                observation,
                mappings_by_id=mappings_by_id,
                mapping_categories=mapping_categories,
                mappings_by_provenance=mappings_by_provenance,
                snapshots_by_id=snapshots_by_id,
                candidates_by_id=candidates_by_id,
                sources=sources,
                card_ids=card_ids,
                print_ids=print_ids,
                provenance_counts=provenance_counts,
            )
            _record_category(observation_summary, category, observation.id, sample_limit)
            observation_source_counts[
                _source_label(observation.source_id, sources)
            ][category] += 1

    generated_at = (now or datetime.now(timezone.utc)).isoformat()
    return HistoricalLineageInventory(
        generated_at=generated_at,
        sample_limit=sample_limit,
        mappings={
            "total": len(mappings),
            "categories": mapping_summary,
            "by_source": _render_source_counts(
                mapping_source_counts, MAPPING_CATEGORIES
            ),
            "compatibility_conflicts": _compatibility_conflicts(
                mappings, print_ids, sample_limit
            ),
        },
        observations={
            "total": len(observations),
            "categories": observation_summary,
            "by_source": _render_source_counts(
                observation_source_counts, OBSERVATION_CATEGORIES
            ),
            "provenance_signals": {
                name: provenance_counts[name] for name in PROVENANCE_COUNTERS
            },
        },
    )
