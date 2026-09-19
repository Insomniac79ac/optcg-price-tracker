"""Catalogue-wide, source-neutral exact-print proposal analysis.

The resolver is deliberately pure with respect to database state: analysis
issues SELECTs only.  ``persist_proposals`` is a separate, explicit operation
that writes proposal rows but never candidates, mappings, observations, or
collector state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    ReleaseProductAlias,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.services.official_asset_variant import parse_official_asset_variant
from app.services.snkrdunk_urls import listing_id as snkrdunk_listing_id
from app.services.yuyutei_urls import listing_identity as yuyutei_listing_identity


RESOLVER_VERSION = "source-mapping-proposals/1.0"
SUPPORTED_SOURCES = ("yuyutei", "snkrdunk")
TARGET_LANGUAGE = "jp"
_ASSET_VARIANT = re.compile(r"^(?:base|[pr][1-9][0-9]*)$")
_SNK_PRODUCT_LABEL = re.compile(r"\(([^()]+)\)\s*$")


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    return result or None


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text_digest(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


@dataclass(frozen=True)
class ProposalFilters:
    source: str = "all"
    release_product_id: int | None = None
    release_code: str | None = None
    resolution_status: str | None = None
    candidate_id: int | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class AlternativePlan:
    card_print_id: int
    recommended: bool
    supporting_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    conflict_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_print_id": self.card_print_id,
            "recommended": self.recommended,
            "supporting_evidence": list(self.supporting_evidence),
            "missing_evidence": list(self.missing_evidence),
            "conflict_reasons": list(self.conflict_reasons),
        }


@dataclass(frozen=True)
class ProposalPlan:
    source_id: int
    source_name: str
    canonical_source_listing_identity: str
    source_url: str
    source_candidate_type: str
    source_candidate_id: int
    canonical_card_id: int | None
    card_code: str | None
    release_product_id: int | None
    resolution_status: str
    resolver_version: str
    evidence_digest: str
    evidence_summary: dict[str, Any]
    resolution_reasons: tuple[str, ...]
    alternatives: tuple[AlternativePlan, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source": self.source_name,
            "canonical_source_listing_identity": self.canonical_source_listing_identity,
            "source_url": self.source_url,
            "source_candidate_type": self.source_candidate_type,
            "source_candidate_id": self.source_candidate_id,
            "canonical_card_id": self.canonical_card_id,
            "card_code": self.card_code,
            "release_product_id": self.release_product_id,
            "resolution_status": self.resolution_status,
            "review_status": "pending",
            "resolver_version": self.resolver_version,
            "evidence_digest": self.evidence_digest,
            "evidence_summary": self.evidence_summary,
            "resolution_reasons": list(self.resolution_reasons),
            "alternatives": [item.to_dict() for item in self.alternatives],
        }


@dataclass(frozen=True)
class CandidateOutcome:
    source_name: str
    candidate_id: int
    release_product_id: int | None
    canonical_card_id: int | None
    covered_print_ids: frozenset[int]
    already_exactly_mapped: bool
    resolution_status: str
    proposal: ProposalPlan | None


@dataclass
class ProposalAnalysis:
    plans: list[ProposalPlan]
    outcomes: list[CandidateOutcome]
    report: dict[str, Any]

    def to_dict(self, *, include_groups: bool = True) -> dict[str, Any]:
        result = dict(self.report)
        if include_groups:
            result["proposal_groups"] = [plan.to_dict() for plan in self.plans]
        return result


def _mapping_listing_identity(source_name: str, url: str | None) -> str | None:
    if source_name == "yuyutei":
        parsed = yuyutei_listing_identity(url)
        return f"{parsed[0]}:{parsed[1]}" if parsed else None
    parsed = snkrdunk_listing_id(url)
    return parsed


def _candidate_payload(candidate: Any, source_name: str) -> dict[str, Any]:
    if source_name == "yuyutei":
        return {
            "candidate_id": candidate.id,
            "discovery_run_id": candidate.discovery_run_id,
            "set_slug": candidate.set_slug,
            "product_id": candidate.product_id,
            "source_url": candidate.source_url,
            "detected_card_code": candidate.detected_card_code,
            "detected_rarity": candidate.detected_rarity,
            "name_jp": candidate.name_jp,
            "image_url": candidate.image_url,
            "price_jpy": candidate.price_jpy,
            "availability": candidate.availability,
            "raw_listing_digest": _text_digest(candidate.raw_listing_text),
            "candidate_match_status": candidate.match_status,
            "candidate_matched_card_print_id": candidate.matched_card_print_id,
        }
    return {
        "candidate_id": candidate.id,
        "discovery_run_id": candidate.discovery_run_id,
        "source_url": candidate.source_url,
        "title": candidate.title,
        "image_url": candidate.image_url,
        "listing_count": candidate.listing_count,
        "condition_label": candidate.condition_label,
        "raw_text_digest": _text_digest(candidate.raw_text),
        "detected_card_code": candidate.detected_card_code,
        "detected_set_code": candidate.detected_set_code,
        "detected_rarity": candidate.detected_rarity,
        "detected_variant": candidate.detected_variant,
        # These remain evidence about a legacy Card-family decision only.
        "legacy_match_status": candidate.match_status,
        "legacy_matched_card_id": candidate.matched_card_id,
        "legacy_best_match_card_id": candidate.best_match_card_id,
    }


def _make_plan(
    *,
    source: Source,
    candidate: Any,
    candidate_type: str,
    listing_identity: str,
    canonical: CanonicalCard | None,
    release: ReleaseProduct | None,
    status: str,
    reasons: list[str],
    alternatives: list[AlternativePlan],
    candidate_payload: dict[str, Any],
    eligible_prints: list[CardPrint],
) -> ProposalPlan:
    evidence = {
        **candidate_payload,
        "resolved_canonical_card_id": canonical.id if canonical else None,
        "resolved_release_product_id": release.id if release else None,
        "eligible_print_identity": [
            {
                "card_print_id": row.id,
                "release_product_id": row.release_product_id,
                "official_asset_variant": row.official_asset_variant,
            }
            for row in sorted(eligible_prints, key=lambda item: item.id)
        ],
    }
    return ProposalPlan(
        source_id=source.id,
        source_name=source.name,
        canonical_source_listing_identity=listing_identity,
        source_url=candidate.source_url,
        source_candidate_type=candidate_type,
        source_candidate_id=candidate.id,
        canonical_card_id=canonical.id if canonical else None,
        card_code=candidate.detected_card_code,
        release_product_id=release.id if release else None,
        resolution_status=status,
        resolver_version=RESOLVER_VERSION,
        evidence_digest=_digest(evidence),
        evidence_summary=evidence,
        resolution_reasons=tuple(reasons),
        alternatives=tuple(alternatives),
    )


def _source_alias_resolution(
    aliases: dict[tuple[int, str], list[ReleaseProduct]], source_id: int, label: str | None
) -> tuple[ReleaseProduct | None, bool]:
    if not label:
        return None, False
    rows = aliases.get((source_id, label), [])
    unique = {row.id: row for row in rows}
    if len(unique) == 1:
        return next(iter(unique.values())), False
    return None, len(unique) > 1


def analyse_source_mapping_proposals(
    db: Session, filters: ProposalFilters | None = None
) -> ProposalAnalysis:
    filters = filters or ProposalFilters()
    if filters.source not in ("all", *SUPPORTED_SOURCES):
        raise ValueError(f"unsupported source {filters.source!r}")

    sources = {row.name: row for row in db.scalars(select(Source)).all()}
    missing = [name for name in SUPPORTED_SOURCES if name not in sources]
    if missing:
        raise RuntimeError(f"missing source rows: {missing}")

    releases = db.scalars(select(ReleaseProduct).order_by(ReleaseProduct.id)).all()
    release_by_id = {row.id: row for row in releases}
    release_by_code: dict[str, list[ReleaseProduct]] = defaultdict(list)
    for row in releases:
        if row.source_catalogue == "bandai_jp" and _norm(row.official_code):
            release_by_code[_norm(row.official_code)].append(row)

    selected_release_ids = {row.id for row in releases}
    if filters.release_product_id is not None:
        selected_release_ids &= {filters.release_product_id}
    if filters.release_code is not None:
        selected_release_ids &= {
            row.id for row in releases if _norm(row.official_code) == _norm(filters.release_code)
        }

    canonicals = db.scalars(select(CanonicalCard)).all()
    canonical_by_code: dict[str, list[CanonicalCard]] = defaultdict(list)
    for row in canonicals:
        canonical_by_code[_norm(row.card_code)].append(row)

    target_prints = db.scalars(
        select(CardPrint).where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == TARGET_LANGUAGE,
        )
    ).all()
    prints_by_family_release: dict[tuple[int, int], list[CardPrint]] = defaultdict(list)
    for row in target_prints:
        if row.release_product_id is not None:
            prints_by_family_release[(row.canonical_card_id, row.release_product_id)].append(row)

    source_aliases: dict[tuple[int, str], list[ReleaseProduct]] = defaultdict(list)
    alias_columns = {column["name"] for column in inspect(db.connection()).get_columns("release_product_aliases")}
    if "source_id" in alias_columns:
        for alias in db.scalars(
            select(ReleaseProductAlias).where(ReleaseProductAlias.alias_kind == "source_rendering")
        ).all():
            if alias.source_id is not None and alias.product_id in release_by_id:
                source_aliases[(alias.source_id, alias.alias_name)].append(release_by_id[alias.product_id])

    mappings = db.scalars(select(SourceCardMapping)).all()
    source_name_by_id = {row.id: row.name for row in sources.values()}
    exact_mapping_by_listing: dict[tuple[str, str], list[SourceCardMapping]] = defaultdict(list)
    approved_mapping_prints: dict[str, set[int]] = defaultdict(set)
    exact_mapping_print_ids: dict[str, list[int]] = defaultdict(list)
    for mapping in mappings:
        source_name = source_name_by_id.get(mapping.source_id)
        if source_name not in SUPPORTED_SOURCES or mapping.card_print_id is None:
            continue
        identity = _mapping_listing_identity(source_name, mapping.source_url)
        if identity:
            exact_mapping_by_listing[(source_name, identity)].append(mapping)
        if mapping.is_active and mapping.review_status == "approved":
            approved_mapping_prints[source_name].add(mapping.card_print_id)
            exact_mapping_print_ids[source_name].append(mapping.card_print_id)

    yuyu_runs = {row.id: row for row in db.scalars(select(YuyuteiDiscoveryRun)).all()}
    later_completed: dict[str, set[int]] = defaultdict(set)
    completed_runs = [row for row in yuyu_runs.values() if row.status == "completed"]
    for run in completed_runs:
        for slug in run.requested_set_slugs or []:
            later_completed[slug].add(run.id)

    candidates_by_source: dict[str, list[Any]] = {
        "yuyutei": db.scalars(select(YuyuteiCandidate).order_by(YuyuteiCandidate.id)).all(),
        "snkrdunk": db.scalars(select(SnkrdunkCandidate).order_by(SnkrdunkCandidate.id)).all(),
    }

    outcomes: list[CandidateOutcome] = []
    for source_name in SUPPORTED_SOURCES:
        if filters.source not in ("all", source_name):
            continue
        source = sources[source_name]
        for candidate in candidates_by_source[source_name]:
            if filters.candidate_id is not None and candidate.id != filters.candidate_id:
                continue
            payload = _candidate_payload(candidate, source_name)
            reasons: list[str] = []
            status: str | None = None
            release: ReleaseProduct | None = None
            listing_identity: str | None = None

            if source_name == "yuyutei":
                parsed = yuyutei_listing_identity(candidate.source_url)
                if parsed is None or parsed != (candidate.set_slug, candidate.product_id):
                    status = "conflict"
                    reasons.append("source_url_identity_conflicts_with_candidate_natural_key")
                    listing_identity = f"invalid:yuyutei-candidate:{candidate.id}"
                else:
                    listing_identity = f"{parsed[0]}:{parsed[1]}"
                release_rows = release_by_code.get(_norm(candidate.set_slug), [])
                if len(release_rows) == 1:
                    release = release_rows[0]
                elif len(release_rows) > 1:
                    status = "conflict"
                    reasons.append("source_series_resolves_to_multiple_release_products")
                elif status is None:
                    status = "release_unresolved"
                    reasons.append("source_series_does_not_resolve_to_release_product")

                run = yuyu_runs.get(candidate.discovery_run_id)
                if run is None or run.status != "completed":
                    status = "stale"
                    reasons.append("candidate_discovery_run_not_completed")
                else:
                    metrics = (run.per_slug_metrics_json or {}).get(candidate.set_slug)
                    if not metrics or not metrics.get("enumeration_complete"):
                        status = "stale"
                        reasons.append("source_series_enumeration_incomplete")
                    elif any(run_id > run.id for run_id in later_completed[candidate.set_slug]):
                        status = "superseded"
                        reasons.append("later_completed_source_series_enumeration_exists")
            else:
                parsed = snkrdunk_listing_id(candidate.source_url)
                if parsed is None:
                    status = "conflict"
                    reasons.append("source_url_has_no_canonical_numeric_listing_identity")
                    listing_identity = f"invalid:snkrdunk-candidate:{candidate.id}"
                else:
                    listing_identity = parsed
                direct_rows = release_by_code.get(_norm(candidate.detected_set_code), [])
                direct = direct_rows[0] if len(direct_rows) == 1 else None
                label_match = _SNK_PRODUCT_LABEL.search(candidate.title or "")
                label = label_match.group(1).strip() if label_match else None
                alias, alias_conflict = _source_alias_resolution(source_aliases, source.id, label)
                if len(direct_rows) > 1 or alias_conflict:
                    status = "conflict"
                    reasons.append("source_release_evidence_resolves_to_multiple_products")
                elif direct is not None and alias is not None and direct.id != alias.id:
                    status = "conflict"
                    reasons.append("stored_set_code_conflicts_with_source_scoped_alias")
                else:
                    release = direct or alias
                    if release is None and status is None:
                        status = "release_unresolved"
                        reasons.append("stored_source_release_evidence_unresolved")
                payload["source_product_label"] = label
                payload["source_alias_release_product_id"] = alias.id if alias else None

            canonical_rows = canonical_by_code.get(_norm(candidate.detected_card_code), [])
            canonical = canonical_rows[0] if len(canonical_rows) == 1 else None
            if len(canonical_rows) > 1:
                status = "conflict"
                reasons.append("card_code_resolves_to_multiple_canonical_cards")
            elif canonical is None and status not in ("conflict", "stale", "superseded"):
                status = "unresolved_identity"
                reasons.append("card_code_does_not_resolve_to_canonical_card")

            eligible = (
                list(prints_by_family_release.get((canonical.id, release.id), []))
                if canonical is not None and release is not None
                else []
            )
            eligible.sort(key=lambda row: row.id)
            covered = frozenset(row.id for row in eligible)
            if canonical is not None and release is not None and not eligible and status is None:
                status = "conflict"
                reasons.append("canonical_family_has_no_eligible_print_in_resolved_release")

            alternatives: list[AlternativePlan] = []
            if status is None:
                variant: str | None = None
                if source_name == "snkrdunk" and _ASSET_VARIANT.fullmatch(
                    (candidate.detected_variant or "").strip().lower()
                ):
                    variant = candidate.detected_variant.strip().lower()
                elif source_name == "yuyutei":
                    variant = parse_official_asset_variant(
                        candidate.image_url, candidate.detected_card_code
                    )
                variant_matches = [
                    row for row in eligible if row.official_asset_variant == variant
                ] if variant else []
                if variant and not variant_matches:
                    status = "conflict"
                    reasons.append("stored_exact_asset_variant_conflicts_with_release_siblings")
                    alternatives = [
                        AlternativePlan(
                            row.id, False,
                            supporting_evidence=("canonical_family", "release_product"),
                            conflict_reasons=("stored_exact_asset_variant_mismatch",),
                        ) for row in eligible
                    ]
                elif len(eligible) == 1:
                    status = "exact"
                    alternatives = [AlternativePlan(
                        eligible[0].id,
                        True,
                        supporting_evidence=(
                            "canonical_source_listing_identity",
                            "canonical_card_family",
                            "authoritative_release_product",
                            "only_active_verified_japanese_print_in_release",
                        ),
                    )]
                    reasons.append("exactly_one_eligible_print_in_resolved_release")
                elif len(variant_matches) == 1:
                    status = "exact"
                    alternatives = [AlternativePlan(
                        variant_matches[0].id,
                        True,
                        supporting_evidence=(
                            "canonical_card_family", "authoritative_release_product",
                            "stored_exact_asset_variant",
                        ),
                    )]
                    reasons.append("stored_exact_asset_variant_resolves_one_release_sibling")
                elif len(eligible) > 1:
                    status = "ambiguous"
                    alternatives = [AlternativePlan(
                        row.id,
                        False,
                        supporting_evidence=("canonical_card_family", "authoritative_release_product"),
                        missing_evidence=("conclusive_exact_artwork_or_variant_evidence",),
                    ) for row in eligible]
                    reasons.append("multiple_eligible_sibling_prints_in_resolved_release")
            assert status is not None

            exact_mappings = exact_mapping_by_listing.get((source_name, listing_identity or ""), [])
            already_mapped = bool(exact_mappings)
            if already_mapped and eligible:
                eligible_ids = {row.id for row in eligible}
                mapped_ids = {row.card_print_id for row in exact_mappings}
                if not mapped_ids <= eligible_ids:
                    status = "conflict"
                    reasons.append("existing_exact_mapping_conflicts_with_candidate_family_or_release")

            plan: ProposalPlan | None = None
            if not already_mapped:
                plan = _make_plan(
                    source=source,
                    candidate=candidate,
                    candidate_type=(
                        "yuyutei_candidate" if source_name == "yuyutei" else "snkrdunk_candidate"
                    ),
                    listing_identity=listing_identity or f"invalid:{source_name}:{candidate.id}",
                    canonical=canonical,
                    release=release,
                    status=status,
                    reasons=reasons,
                    alternatives=alternatives,
                    candidate_payload=payload,
                    eligible_prints=eligible,
                )
            outcomes.append(CandidateOutcome(
                source_name=source_name,
                candidate_id=candidate.id,
                release_product_id=release.id if release else None,
                canonical_card_id=canonical.id if canonical else None,
                covered_print_ids=covered,
                already_exactly_mapped=already_mapped,
                resolution_status=status,
                proposal=plan,
            ))

    plans = [outcome.proposal for outcome in outcomes if outcome.proposal is not None]
    plans = [plan for plan in plans if plan.release_product_id in selected_release_ids or plan.release_product_id is None]
    if filters.resolution_status:
        plans = [plan for plan in plans if plan.resolution_status == filters.resolution_status]
    plans.sort(key=lambda plan: (plan.source_name, plan.source_candidate_id))
    if filters.offset:
        plans = plans[filters.offset:]
    if filters.limit is not None:
        plans = plans[: filters.limit]

    selected_outcomes = [
        outcome for outcome in outcomes
        if outcome.release_product_id in selected_release_ids or outcome.release_product_id is None
    ]
    report = _build_report(
        db=db,
        releases=releases,
        selected_release_ids=selected_release_ids,
        target_prints=target_prints,
        outcomes=selected_outcomes,
        plans=plans,
        approved_mapping_prints=approved_mapping_prints,
        exact_mapping_print_ids=exact_mapping_print_ids,
        selected_sources=(SUPPORTED_SOURCES if filters.source == "all" else (filters.source,)),
    )
    return ProposalAnalysis(plans=plans, outcomes=selected_outcomes, report=report)


def _build_report(
    *,
    db: Session,
    releases: list[ReleaseProduct],
    selected_release_ids: set[int],
    target_prints: list[CardPrint],
    outcomes: list[CandidateOutcome],
    plans: list[ProposalPlan],
    approved_mapping_prints: dict[str, set[int]],
    exact_mapping_print_ids: dict[str, list[int]],
    selected_sources: tuple[str, ...],
) -> dict[str, Any]:
    target_by_release: dict[int, set[int]] = defaultdict(set)
    release_by_print: dict[int, int] = {}
    for row in target_prints:
        if row.release_product_id in selected_release_ids:
            target_by_release[row.release_product_id].add(row.id)
            release_by_print[row.id] = row.release_product_id

    outcomes_by_source_release: dict[tuple[str, int], list[CandidateOutcome]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.release_product_id is not None:
            outcomes_by_source_release[(outcome.source_name, outcome.release_product_id)].append(outcome)
    plans_by_source_release: dict[tuple[str, int], list[ProposalPlan]] = defaultdict(list)
    for plan in plans:
        if plan.release_product_id is not None:
            plans_by_source_release[(plan.source_name, plan.release_product_id)].append(plan)

    source_ids = db.scalars(select(Source.id).where(Source.name.in_(selected_sources))).all()
    observed_prints = set(db.scalars(
        select(PriceObservation.card_print_id).where(
            PriceObservation.source_id.in_(source_ids),
            PriceObservation.card_print_id.is_not(None),
        ).distinct()
    ).all())

    release_rows: list[dict[str, Any]] = []
    for release in releases:
        if release.id not in selected_release_ids:
            continue
        universe = target_by_release.get(release.id, set())
        row: dict[str, Any] = {
            "release_product_id": release.id,
            "official_code": release.official_code,
            "display_name": release.display_name,
            "total_physical_prints": len(universe),
        }
        mapped_any: set[int] = set()
        exact_any: set[int] = set()
        covered_any: set[int] = set()
        ambiguous_total = 0
        candidate_total = 0
        for source_name in selected_sources:
            source_outcomes = outcomes_by_source_release.get((source_name, release.id), [])
            source_plans = plans_by_source_release.get((source_name, release.id), [])
            mapped = approved_mapping_prints[source_name] & universe
            exact = {
                alt.card_print_id
                for plan in source_plans if plan.resolution_status == "exact"
                for alt in plan.alternatives if alt.recommended
            }
            covered = set().union(*(item.covered_print_ids for item in source_outcomes)) if source_outcomes else set()
            unmapped = universe - mapped
            source_metrics = {
                "existing_exact_mapped_prints": len(mapped),
                "candidates_considered": len(source_outcomes),
                "exact_proposal_groups": sum(p.resolution_status == "exact" for p in source_plans),
                "unique_exact_prints_covered": len(exact),
                "ambiguous_proposal_groups": sum(p.resolution_status == "ambiguous" for p in source_plans),
                "unresolved_identity": sum(p.resolution_status == "unresolved_identity" for p in source_plans),
                "release_unresolved": 0,
                "conflicts": sum(p.resolution_status == "conflict" for p in source_plans),
                "physical_prints_with_no_candidate_evidence": len(universe - covered),
                "candidate_backed_but_not_exact": len((covered & unmapped) - exact),
                "remaining_unmapped_after_exact_proposals": len(unmapped - exact),
            }
            row[source_name] = source_metrics
            mapped_any |= mapped
            exact_any |= exact
            covered_any |= covered
            ambiguous_total += source_metrics["ambiguous_proposal_groups"]
            candidate_total += source_metrics["candidates_considered"]
        row.update({
            "existing_exact_mapped_any_source": len(mapped_any),
            "mapped_by_neither": len(universe - mapped_any),
            "usable_price_prints": len(universe & observed_prints),
            "exact_proposal_prints_any_source": len(exact_any),
            "ambiguous_candidate_groups": ambiguous_total,
            "candidates_considered": candidate_total,
            "prints_with_no_candidate_evidence_any_source": len(universe - covered_any),
            "remaining_unmapped_after_all_exact_proposals": len(universe - mapped_any - exact_any),
        })
        release_rows.append(row)

    global_sources: dict[str, Any] = {}
    for source_name in selected_sources:
        source_plans = [plan for plan in plans if plan.source_name == source_name]
        source_outcomes = [item for item in outcomes if item.source_name == source_name]
        mapped = approved_mapping_prints[source_name] & set(release_by_print)
        exact = {
            alt.card_print_id for plan in source_plans if plan.resolution_status == "exact"
            for alt in plan.alternatives if alt.recommended
        }
        covered = set().union(*(item.covered_print_ids for item in source_outcomes)) if source_outcomes else set()
        universe = set(release_by_print)
        global_sources[source_name] = {
            "existing_exact_mapping_rows": sum(
                print_id in universe for print_id in exact_mapping_print_ids[source_name]
            ),
            "existing_exact_mapped_prints": len(mapped),
            "candidates_considered": len(source_outcomes),
            "candidate_listings_already_exactly_mapped": sum(i.already_exactly_mapped for i in source_outcomes),
            "candidate_resolution_counts": {
                status: sum(item.resolution_status == status for item in source_outcomes)
                for status in (
                    "exact", "ambiguous", "unresolved_identity", "release_unresolved",
                    "conflict", "stale", "superseded",
                )
            },
            "exact_proposal_groups": sum(p.resolution_status == "exact" for p in source_plans),
            "unique_exact_prints_covered": len(exact),
            "ambiguous_proposal_groups": sum(p.resolution_status == "ambiguous" for p in source_plans),
            "unresolved_identity": sum(p.resolution_status == "unresolved_identity" for p in source_plans),
            "release_unresolved": sum(p.resolution_status == "release_unresolved" for p in source_plans),
            "conflicts": sum(p.resolution_status == "conflict" for p in source_plans),
            "stale": sum(p.resolution_status == "stale" for p in source_plans),
            "superseded": sum(p.resolution_status == "superseded" for p in source_plans),
            "physical_prints_with_no_candidate_evidence": len(universe - covered),
            "candidate_backed_but_not_exact": len((covered - mapped) - exact),
            "remaining_unmapped_after_all_exact_proposals": len(universe - mapped - exact),
        }

    def ranked(metric: str, *, zero: bool = False) -> list[dict[str, Any]]:
        rows = [row for row in release_rows if (row[metric] == 0 if zero else True)]
        if not zero:
            rows.sort(key=lambda item: (-item[metric], item["release_product_id"]))
        return [
            {
                "release_product_id": row["release_product_id"],
                "official_code": row["official_code"],
                "display_name": row["display_name"],
                metric: row[metric],
            }
            for row in rows
        ]

    return {
        "contract": {
            "resolver_version": RESOLVER_VERSION,
            "target": "active verified Japanese CardPrints grouped by release_product_id",
            "release_membership_from_card_code_prefix": False,
            "dry_run_is_select_only": True,
        },
        "overall": {
            "release_products": len(release_rows),
            "total_physical_prints": sum(row["total_physical_prints"] for row in release_rows),
            "sources": global_sources,
        },
        "releases": release_rows,
        "prioritisation": {
            "zero_usable_prices": ranked("usable_price_prints", zero=True),
            "zero_exact_mappings": ranked("existing_exact_mapped_any_source", zero=True),
            "highest_mapped_neither": ranked("mapped_by_neither"),
            "most_exact_proposals_ready": ranked("exact_proposal_prints_any_source"),
            "most_ambiguous_candidates": ranked("ambiguous_candidate_groups"),
            "most_prints_with_no_candidate_evidence": ranked(
                "prints_with_no_candidate_evidence_any_source"
            ),
        },
    }


@dataclass(frozen=True)
class PersistenceResult:
    created_groups: int
    reused_groups: int
    superseded_groups: int
    created_alternatives: int


def persist_proposals(db: Session, plans: Iterable[ProposalPlan]) -> PersistenceResult:
    """Persist plans idempotently.  Flushes but never commits."""
    created = reused = superseded = alternatives = 0
    now = datetime.now(timezone.utc)
    for plan in plans:
        current = db.scalar(
            select(SourceMappingProposalGroup)
            .options(selectinload(SourceMappingProposalGroup.alternatives))
            .where(
                SourceMappingProposalGroup.source_id == plan.source_id,
                SourceMappingProposalGroup.canonical_source_listing_identity
                == plan.canonical_source_listing_identity,
                SourceMappingProposalGroup.superseded_at.is_(None),
            )
        )
        if current is not None and (
            current.resolver_version == plan.resolver_version
            and current.evidence_digest == plan.evidence_digest
        ):
            expected = {(a.card_print_id, a.recommended) for a in plan.alternatives}
            actual = {(a.card_print_id, a.recommended) for a in current.alternatives}
            if expected != actual or current.resolution_status != plan.resolution_status:
                raise RuntimeError(
                    "stored proposal differs from deterministic resolver output for unchanged evidence"
                )
            reused += 1
            continue
        historical = db.scalar(
            select(SourceMappingProposalGroup)
            .options(selectinload(SourceMappingProposalGroup.alternatives))
            .where(
                SourceMappingProposalGroup.source_id == plan.source_id,
                SourceMappingProposalGroup.canonical_source_listing_identity
                == plan.canonical_source_listing_identity,
                SourceMappingProposalGroup.resolver_version == plan.resolver_version,
                SourceMappingProposalGroup.evidence_digest == plan.evidence_digest,
            )
        )
        if historical is not None:
            expected = {(a.card_print_id, a.recommended) for a in plan.alternatives}
            actual = {(a.card_print_id, a.recommended) for a in historical.alternatives}
            if expected != actual or historical.resolution_status != plan.resolution_status:
                raise RuntimeError(
                    "stored historical proposal differs from deterministic resolver output"
                )
            if current is not None:
                current.superseded_at = now
                db.flush()
                superseded += 1
            historical.superseded_at = None
            reused += 1
            continue
        if current is not None:
            current.superseded_at = now
            superseded += 1
        group = SourceMappingProposalGroup(
            source_id=plan.source_id,
            canonical_source_listing_identity=plan.canonical_source_listing_identity,
            source_url=plan.source_url,
            source_candidate_type=plan.source_candidate_type,
            source_candidate_id=plan.source_candidate_id,
            canonical_card_id=plan.canonical_card_id,
            release_product_id=plan.release_product_id,
            resolution_status=plan.resolution_status,
            review_status="pending",
            resolver_version=plan.resolver_version,
            evidence_digest=plan.evidence_digest,
            evidence_summary_json=plan.evidence_summary,
            resolution_reasons_json=list(plan.resolution_reasons),
        )
        db.add(group)
        db.flush()
        created += 1
        for item in plan.alternatives:
            db.add(SourceMappingProposalAlternative(
                proposal_group_id=group.id,
                card_print_id=item.card_print_id,
                recommended=item.recommended,
                supporting_evidence_json=list(item.supporting_evidence),
                missing_evidence_json=list(item.missing_evidence),
                conflict_reasons_json=list(item.conflict_reasons),
                review_disposition="pending",
            ))
            alternatives += 1
    db.flush()
    return PersistenceResult(created, reused, superseded, alternatives)
