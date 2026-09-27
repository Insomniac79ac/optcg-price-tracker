"""Read-only database adapter for the pure Market Value engine.

This module projects immutable ``market_index_snapshots`` and the current
corrected ``CardPrint.release_product_id`` catalogue into
``app.services.market_value`` input types.  It performs SELECTs only.  The CLI
edge in ``app.market_value_replay_report`` additionally requires PostgreSQL to
confirm ``transaction_read_only=on`` before calling this module.

Historical limitation, made explicit: the snapshot archive does not store a
release/status membership revision.  Initial A2 replay therefore uses one
digest of today's corrected active, verified Japanese physical-print
catalogue for every historical day.  That digest records the replay basis; it
does not claim the same membership was historically published.  A future
persisted series needs the immutable membership ledger specified by A1.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.models.release_product import ReleaseProduct
from app.services.market_index_change import eligible_contributor_set
from app.services.market_value import (
    METHODOLOGY_VERSION,
    MarketValueDay,
    MarketValueObservation,
    MarketValueScope,
    MarketValueWindow,
    TrackedValueResult,
    current_tracked_value,
    evaluate_market_value_window,
    replay_market_value,
)
from app.services.market_value_persistence import (
    MarketValuePointDraft,
    publication_reasons_text,
    version_pairs_text,
)
from app.services.print_market_index import get_market_index_for_prints
from app.snapshot_market_index import select_snapshottable_print_ids


@dataclass(frozen=True)
class ActivePrintIdentity:
    card_print_id: int
    release_product_id: int


@dataclass(frozen=True)
class ActiveCodedRelease:
    release_product_id: int
    official_code: str
    active_physical_print_count: int


@dataclass(frozen=True)
class MarketValueReplayInput:
    catalogue_membership_revision: str
    archive_dates: tuple[date, ...]
    observations_by_date: dict[date, tuple[MarketValueObservation, ...]]
    active_prints: tuple[ActivePrintIdentity, ...]
    coded_releases: tuple[ActiveCodedRelease, ...]
    current_observations: tuple[MarketValueObservation, ...]
    current_as_of: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _contributors(source_values: Any) -> frozenset[tuple[str, str]] | None:
    contributors = eligible_contributor_set(source_values)
    return frozenset(contributors) if contributors is not None else None


def _compact_contributors(
    pairs: Any,
) -> frozenset[tuple[str, str]] | None:
    """Read contributor pairs already validated by the PostgreSQL projection."""
    if not isinstance(pairs, list):
        return None
    contributors: set[tuple[str, str]] = set()
    for pair in pairs:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(value, str) and value for value in pair)
        ):
            return None
        contributors.add((pair[0], pair[1]))
    return frozenset(contributors)


def _load_archive_rows(
    db: Session, *, through: date | None = None
) -> list[Any]:
    """Load exact archive inputs without shipping unrelated JSON over the wire.

    ``through`` is applied in SQL, not after loading.  Operator-controlled
    persistence runs can therefore freeze their archive boundary without even
    reading a snapshot day that is outside the intended batch.
    """
    if db.get_bind().dialect.name == "postgresql":
        # The archive keeps complete provenance JSON. A remote replay only
        # needs the contributor identity set, but it must preserve
        # eligible_contributor_set's fail-closed behavior. This projection
        # returns NULL when source_values is not an array, a required field is
        # absent, source/type is not a string, or contributes_to_index is
        # unknown. Otherwise it returns the compact contributing pairs.
        through_clause = (
            "AND snapshot.snapshot_date <= :through" if through is not None else ""
        )
        statement = text(
            f"""
                    SELECT
                        snapshot.snapshot_date,
                        snapshot.card_print_id,
                        snapshot.index_value_jpy,
                        snapshot.index_version,
                        snapshot.source_semantics_version,
                        CASE
                            WHEN jsonb_typeof(
                                snapshot.provenance->'source_values'
                            ) IS DISTINCT FROM 'array'
                                THEN NULL
                            WHEN EXISTS (
                                SELECT 1
                                FROM jsonb_array_elements(
                                    snapshot.provenance->'source_values'
                                ) AS entry
                                WHERE NOT (
                                    entry ?& ARRAY[
                                        'source',
                                        'reference_type',
                                        'contributes_to_index',
                                        'value_jpy'
                                    ]
                                )
                                OR jsonb_typeof(entry->'source')
                                    IS DISTINCT FROM 'string'
                                OR jsonb_typeof(entry->'reference_type')
                                    IS DISTINCT FROM 'string'
                                OR entry->'contributes_to_index' = 'null'::jsonb
                            ) THEN NULL
                            ELSE (
                                SELECT COALESCE(
                                    jsonb_agg(
                                        jsonb_build_array(
                                            entry->>'source',
                                            entry->>'reference_type'
                                        )
                                        ORDER BY
                                            entry->>'source',
                                            entry->>'reference_type'
                                    ),
                                    '[]'::jsonb
                                )
                                FROM jsonb_array_elements(
                                    snapshot.provenance->'source_values'
                                ) AS entry
                                WHERE entry->'contributes_to_index' = 'true'::jsonb
                                AND entry->'value_jpy' <> 'null'::jsonb
                            )
                        END AS contributor_pairs
                    FROM market_index_snapshots AS snapshot
                    JOIN card_prints AS print
                        ON print.id = snapshot.card_print_id
                    WHERE print.is_active IS TRUE
                    AND print.verification_status = 'verified'
                    AND print.language = 'jp'
                    AND print.release_product_id IS NOT NULL
                    {through_clause}
                    ORDER BY snapshot.snapshot_date, snapshot.card_print_id
                    """
        )
        parameters = {"through": through} if through is not None else {}
        return list(db.execute(statement, parameters))

    # SQLite/local-test fallback. It intentionally uses the same Python
    # helper as existing Market Index change calculations.
    conditions = [
        CardPrint.is_active.is_(True),
        CardPrint.verification_status == "verified",
        CardPrint.language == "jp",
        CardPrint.release_product_id.is_not(None),
    ]
    if through is not None:
        conditions.append(MarketIndexSnapshot.snapshot_date <= through)
    return list(
        db.execute(
            select(
                MarketIndexSnapshot.snapshot_date,
                MarketIndexSnapshot.card_print_id,
                MarketIndexSnapshot.index_value_jpy,
                MarketIndexSnapshot.index_version,
                MarketIndexSnapshot.source_semantics_version,
                MarketIndexSnapshot.provenance,
            )
            .join(CardPrint, CardPrint.id == MarketIndexSnapshot.card_print_id)
            .where(*conditions)
            .order_by(
                MarketIndexSnapshot.snapshot_date,
                MarketIndexSnapshot.card_print_id,
            )
        )
    )


def _membership_revision(active_prints: list[ActivePrintIdentity]) -> str:
    payload = "\n".join(
        f"{row.card_print_id}:{row.release_product_id}"
        for row in sorted(active_prints, key=lambda row: row.card_print_id)
    )
    return "current-corrected-card-print-release-v1:" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def load_market_value_replay_input(
    db: Session,
    *,
    through: date | None = None,
    include_current: bool = True,
) -> MarketValueReplayInput:
    """Load archive and catalogue inputs by SELECT.

    Reporting keeps ``include_current=True`` for its live literal-sum panel.
    Persistence callers set it to false because current observations do not
    contribute to archived point drafts and must not widen a fixed backfill's
    read surface.
    """
    active_rows = db.execute(
        select(CardPrint.id, CardPrint.release_product_id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == "jp",
            CardPrint.release_product_id.is_not(None),
        )
        .order_by(CardPrint.id)
    ).all()
    active_prints = [
        ActivePrintIdentity(
            card_print_id=row.id,
            release_product_id=row.release_product_id,
        )
        for row in active_rows
    ]
    release_by_print = {
        row.card_print_id: row.release_product_id for row in active_prints
    }
    active_ids = set(release_by_print)
    revision = _membership_revision(active_prints)

    release_counts = Counter(release_by_print.values())
    release_rows = db.execute(
        select(ReleaseProduct.id, ReleaseProduct.official_code)
        .where(
            ReleaseProduct.source_catalogue == "bandai_jp",
            ReleaseProduct.official_code.is_not(None),
            ReleaseProduct.verification_status == "verified",
        )
        .order_by(ReleaseProduct.official_code, ReleaseProduct.id)
    ).all()
    coded_releases = tuple(
        ActiveCodedRelease(
            release_product_id=row.id,
            official_code=row.official_code,
            active_physical_print_count=release_counts[row.id],
        )
        for row in release_rows
        if release_counts[row.id] > 0
    )

    snapshots = _load_archive_rows(db, through=through)
    archive_dates = tuple(sorted({row.snapshot_date for row in snapshots}))
    grouped: dict[date, list[MarketValueObservation]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.snapshot_date].append(
            MarketValueObservation(
                card_print_id=snapshot.card_print_id,
                value_jpy=snapshot.index_value_jpy,
                index_version=snapshot.index_version,
                source_semantics_version=snapshot.source_semantics_version,
                contributors=(
                    _compact_contributors(snapshot.contributor_pairs)
                    if hasattr(snapshot, "contributor_pairs")
                    else _contributors(
                        snapshot.provenance.get("source_values")
                        if isinstance(snapshot.provenance, dict)
                        else None
                    )
                ),
                release_product_id=release_by_print[snapshot.card_print_id],
            )
        )
    observations_by_date = {
        point_date: tuple(
            sorted(grouped.get(point_date, []), key=lambda row: row.card_print_id)
        )
        for point_date in archive_dates
    }

    if include_current:
        snapshottable_ids = [
            print_id
            for print_id in select_snapshottable_print_ids(db)
            if print_id in active_ids
        ]
        live_by_print = get_market_index_for_prints(db, snapshottable_ids)
        current_observations = tuple(
            MarketValueObservation(
                card_print_id=print_id,
                value_jpy=value.index_value_jpy,
                index_version=value.index_version,
                source_semantics_version=value.source_semantics_version,
                contributors=_contributors(value.source_values),
                release_product_id=release_by_print[print_id],
            )
            for print_id, value in sorted(live_by_print.items())
        )
        # The batch resolver takes one clock instant for every print. That exact
        # UTC instant is the honest as-of time for the live literal sum; it is
        # never joined to an archived movement step by this adapter.
        current_as_of = (
            _as_utc(next(iter(live_by_print.values())).calculated_at)
            if live_by_print
            else datetime.now(timezone.utc)
        )
    else:
        current_observations = ()
        # This field is irrelevant to persistence drafts.  Keep the skipped
        # current-value projection deterministic rather than consulting the
        # wall clock.
        current_as_of = (
            datetime.combine(archive_dates[-1], time.min, tzinfo=timezone.utc)
            if archive_dates
            else datetime(1970, 1, 1, tzinfo=timezone.utc)
        )
    return MarketValueReplayInput(
        catalogue_membership_revision=revision,
        archive_dates=archive_dates,
        observations_by_date=observations_by_date,
        active_prints=tuple(active_prints),
        coded_releases=coded_releases,
        current_observations=current_observations,
        current_as_of=current_as_of,
    )


def _scope_observations(
    observations: tuple[MarketValueObservation, ...], scope: MarketValueScope
) -> tuple[MarketValueObservation, ...]:
    if scope.release_product_id is None:
        return observations
    return tuple(
        row
        for row in observations
        if row.release_product_id == scope.release_product_id
    )


def scope_replay_days(
    loaded: MarketValueReplayInput,
    *,
    scope: MarketValueScope,
    total_physical_print_count: int,
) -> tuple[MarketValueDay, ...]:
    """Project current corrected FK membership onto every real archive date."""
    return tuple(
        MarketValueDay(
            point_date=point_date,
            observations=_scope_observations(
                loaded.observations_by_date[point_date], scope
            ),
            total_physical_print_count=total_physical_print_count,
            membership_revision=loaded.catalogue_membership_revision,
        )
        for point_date in loaded.archive_dates
    )


def current_scope_value(
    loaded: MarketValueReplayInput,
    *,
    scope: MarketValueScope,
    total_physical_print_count: int,
) -> TrackedValueResult:
    return current_tracked_value(
        _scope_observations(loaded.current_observations, scope),
        total_physical_print_count=total_physical_print_count,
        scope=scope,
    )


def _day_version_pairs(
    day: MarketValueDay,
) -> frozenset[tuple[int, int]]:
    return frozenset(
        (row.index_version, row.source_semantics_version)
        for row in day.observations
        if row.has_usable_value
    )


def _scope_point_drafts(
    loaded: MarketValueReplayInput,
    *,
    scope: MarketValueScope,
    total_physical_print_count: int,
) -> tuple[MarketValuePointDraft, ...]:
    """Derive persistence-shaped facts without writing or recalculating A2."""
    days = scope_replay_days(
        loaded,
        scope=scope,
        total_physical_print_count=total_physical_print_count,
    )
    days_by_date = {day.point_date: day for day in days}
    replay = replay_market_value(days, scope=scope)
    scope_kind = "overall" if scope.release_product_id is None else "release"
    drafts: list[MarketValuePointDraft] = []
    for point in replay:
        step = point.step
        publication = point.publication
        if step is None:
            prior_point_date = None
            step_days = None
            prior_tracked_value_jpy = None
            prior_priced_print_count = None
            prior_total_physical_print_count = None
            comparable_print_count = None
            prior_comparable_value_jpy = None
            current_comparable_value_jpy = None
            step_ratio = None
            step_publication_eligible = None
            publication_reasons = None
            prior_version_pairs = None
            current_pairs = _day_version_pairs(days_by_date[point.point_date])
        else:
            assert publication is not None
            prior_point_date = step.prior_date
            step_days = step.step_days
            prior_tracked_value_jpy = step.prior_tracked.value_jpy
            prior_priced_print_count = step.prior_tracked.priced_print_count
            prior_total_physical_print_count = (
                step.prior_tracked.total_physical_print_count
            )
            comparable_print_count = step.comparable_print_count
            prior_comparable_value_jpy = step.comparable_prior_value_jpy
            current_comparable_value_jpy = step.comparable_current_value_jpy
            step_ratio = step.ratio
            step_publication_eligible = publication.publishable
            publication_reasons = publication_reasons_text(publication.reasons)
            prior_version_pairs = version_pairs_text(step.prior_version_pairs)
            current_pairs = step.current_version_pairs

        drafts.append(
            MarketValuePointDraft(
                scope_kind=scope_kind,
                release_product_id=scope.release_product_id,
                methodology_version=METHODOLOGY_VERSION,
                point_date=point.point_date,
                tracked_value_jpy=point.tracked.value_jpy,
                priced_print_count=point.tracked.priced_print_count,
                total_physical_print_count=point.tracked.total_physical_print_count,
                prior_point_date=prior_point_date,
                step_days=step_days,
                prior_tracked_value_jpy=prior_tracked_value_jpy,
                prior_priced_print_count=prior_priced_print_count,
                prior_total_physical_print_count=prior_total_physical_print_count,
                comparable_print_count=comparable_print_count,
                prior_comparable_value_jpy=prior_comparable_value_jpy,
                current_comparable_value_jpy=current_comparable_value_jpy,
                step_ratio=step_ratio,
                segment_number=point.segment_number,
                performance_factor=point.performance_factor,
                step_publication_eligible=step_publication_eligible,
                publication_reasons=publication_reasons,
                membership_revision=days_by_date[
                    point.point_date
                ].membership_revision,
                prior_version_pairs=prior_version_pairs,
                current_version_pairs=version_pairs_text(current_pairs),
            )
        )
    return tuple(drafts)


def build_market_value_point_drafts(
    loaded: MarketValueReplayInput,
) -> tuple[MarketValuePointDraft, ...]:
    """Build Overall and every active coded release draft, in stable order."""
    drafts = list(
        _scope_point_drafts(
            loaded,
            scope=MarketValueScope.overall(),
            total_physical_print_count=len(loaded.active_prints),
        )
    )
    for release in sorted(
        loaded.coded_releases,
        key=lambda row: (row.release_product_id, row.official_code),
    ):
        drafts.extend(
            _scope_point_drafts(
                loaded,
                scope=MarketValueScope.release(release.release_product_id),
                total_physical_print_count=release.active_physical_print_count,
            )
        )
    return tuple(
        sorted(
            drafts,
            key=lambda row: (
                row.scope_kind,
                row.release_product_id or 0,
                row.methodology_version,
                row.point_date,
            ),
        )
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _tracked_payload(tracked: TrackedValueResult) -> dict[str, Any]:
    return {
        "value_jpy": tracked.value_jpy,
        "priced_physical_prints": tracked.priced_print_count,
        "total_physical_prints": tracked.total_physical_print_count,
        "physical_coverage_fraction": _decimal_text(
            tracked.physical_coverage_fraction
        ),
        "physical_coverage_pct": _decimal_text(tracked.physical_coverage_pct),
        "status": tracked.status.value,
        "is_partial": tracked.is_partial,
        "headline_eligible": tracked.headline_eligible,
    }


def _window_payload(window: MarketValueWindow) -> dict[str, Any]:
    return {
        "available": window.available,
        "from_date": str(window.from_date),
        "to_date": str(window.to_date),
        "movement_fraction": _decimal_text(window.movement_fraction),
        "movement_pct": _decimal_text(window.movement_pct),
        "primary_reason": window.primary_reason.value,
        "reasons": [reason.value for reason in window.reasons],
        "min_comparable_print_count": window.min_comparable_print_count,
        "min_physical_coverage_fraction": _decimal_text(
            window.min_physical_coverage_fraction
        ),
        "min_comparable_value_fraction": _decimal_text(
            window.min_comparable_value_fraction
        ),
    }


def _scope_summary(
    loaded: MarketValueReplayInput,
    *,
    scope: MarketValueScope,
    total_physical_print_count: int,
) -> dict[str, Any]:
    days = scope_replay_days(
        loaded,
        scope=scope,
        total_physical_print_count=total_physical_print_count,
    )
    current = current_scope_value(
        loaded,
        scope=scope,
        total_physical_print_count=total_physical_print_count,
    )
    if not days:
        windows = {
            str(window_days): {
                "available": False,
                "primary_reason": "insufficient_window_continuity",
            }
            for window_days in (7, 30)
        }
        return {"current": _tracked_payload(current), "windows": windows}

    end_date = days[-1].point_date
    windows = {
        str(window_days): _window_payload(
            evaluate_market_value_window(
                days,
                scope=scope,
                window_days=window_days,
                end_date=end_date,
            )
        )
        for window_days in (7, 30)
    }
    replay = replay_market_value(days, scope=scope)
    usable_dates = [
        point.point_date
        for point in replay
        if point.publication is not None and point.publication.publishable
    ]
    break_counts = Counter(
        point.break_reason.value
        for point in replay
        if point.break_reason is not None
    )
    gap_dates = [
        str(point.point_date)
        for point in replay
        if point.step is not None and point.step.step_days != 1
    ]
    return {
        "current": _tracked_payload(current),
        "archive_first_date": str(days[0].point_date),
        "archive_last_date": str(days[-1].point_date),
        "earliest_usable_movement_date": str(min(usable_dates)) if usable_dates else None,
        "latest_usable_movement_date": str(max(usable_dates)) if usable_dates else None,
        "break_counts": dict(sorted(break_counts.items())),
        "gap_dates": gap_dates,
        "windows": windows,
    }


def build_market_value_replay_report(db: Session) -> dict[str, Any]:
    """Build the complete in-memory Overall and coded-release diagnostic."""
    loaded = load_market_value_replay_input(db)
    overall_scope = MarketValueScope.overall()
    overall_total = len(loaded.active_prints)
    overall = _scope_summary(
        loaded,
        scope=overall_scope,
        total_physical_print_count=overall_total,
    )

    releases = []
    for release in loaded.coded_releases:
        scope = MarketValueScope.release(release.release_product_id)
        summary = _scope_summary(
            loaded,
            scope=scope,
            total_physical_print_count=release.active_physical_print_count,
        )
        current = summary["current"]
        releases.append(
            {
                "release_product_id": release.release_product_id,
                "official_code": release.official_code,
                "active_physical_print_count": release.active_physical_print_count,
                "current_priced_print_count": current["priced_physical_prints"],
                "tracked_value_jpy": current["value_jpy"],
                "physical_coverage_fraction": current["physical_coverage_fraction"],
                "seven_day": summary["windows"]["7"],
                "thirty_day": summary["windows"]["30"],
                "primary_unavailability_reason": (
                    None
                    if summary["windows"]["7"]["available"]
                    else summary["windows"]["7"]["primary_reason"]
                ),
            }
        )

    return {
        "read_only_projection": True,
        "historical_membership_basis": "current_corrected_card_print_release_product_id",
        "catalogue_membership_revision": loaded.catalogue_membership_revision,
        "current_as_of": loaded.current_as_of.isoformat(),
        "archive_first_date": str(loaded.archive_dates[0]) if loaded.archive_dates else None,
        "archive_last_date": str(loaded.archive_dates[-1]) if loaded.archive_dates else None,
        "overall": overall,
        "coded_release_count": len(releases),
        "releases": releases,
        "release_publication_counts": {
            "7d": sum(release["seven_day"]["available"] for release in releases),
            "30d": sum(release["thirty_day"]["available"] for release in releases),
        },
        "release_publication_codes": {
            "7d": [
                release["official_code"]
                for release in releases
                if release["seven_day"]["available"]
            ],
            "30d": [
                release["official_code"]
                for release in releases
                if release["thirty_day"]["available"]
            ],
        },
    }


__all__ = [
    "ActiveCodedRelease",
    "ActivePrintIdentity",
    "MarketValueReplayInput",
    "build_market_value_replay_report",
    "build_market_value_point_drafts",
    "current_scope_value",
    "load_market_value_replay_input",
    "scope_replay_days",
]
