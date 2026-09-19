"""Read-only raw snapshot retention planning.

This module models a possible future retention policy. It never imports or
calls the existing pruning implementation, and it has no mutation path. Every
database statement is a SELECT over narrow metadata columns; raw_content is
used only inside a database-side size expression and is never returned.

Eligibility is deliberately fail-closed. A row is ``potentially_eligible``
only when its role is understood from durable metadata and every protection
test is false. Missing role, identity, or audit metadata protects the row as
``unclassified_protected`` rather than treating a NULL foreign key as proof
that the body is disposable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import LargeBinary, cast, func, select
from sqlalchemy.orm import Session

from app.models import (
    PriceObservation,
    RawSnapshot,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
    YuyuteiCandidate,
)

POLICY_VERSION = "raw-snapshot-retention-foundation-1a-v1"
DEFAULT_FULL_RETENTION_DAYS = 90
LONG_EVIDENCE_RETENTION_DAYS = 365

PROTECTION_REASONS = (
    "recent_full_retention",
    "observation_linked",
    "attempt_failure_evidence",
    "source_denied_evidence",
    "snkrdunk_sales_history_evidence",
    "discovery_evidence",
    "candidate_or_identity_evidence",
    "daily_representative_required",
    "audit_or_lineage_hold",
    "unclassified_protected",
)
RESULT_CATEGORIES = PROTECTION_REASONS + ("potentially_eligible",)

AGE_BUCKETS = (
    "<7 days",
    "7-30 days",
    "31-90 days",
    "91-180 days",
    "181-365 days",
    ">365 days",
)

_ATTEMPT_SUCCESS_STATUSES = frozenset({"written"})
_SNKR_SALES_HISTORY_RE = re.compile(
    r"^https://snkrdunk\.com/apparels/(\d+)/sales-histories$"
)
_SNKR_PRODUCT_RES = (
    re.compile(r"^https://snkrdunk\.com/apparels/(\d+)(?:[?#].*)?$"),
    re.compile(r"^https://snkrdunk\.com/en/trading-cards/(\d+)(?:[?#].*)?$"),
)
_YUYUTEI_PRODUCT_RE = re.compile(
    r"^https://yuyu-tei\.jp/sell/opc/card/([a-z0-9][a-z0-9-]*)/(\d+)(?:[?#].*)?$"
)


@dataclass(frozen=True)
class CanonicalSnapshotUrl:
    """A conservative representative key and the role proven by the URL.

    ``equivalence_proven`` is true only for URL forms covered by existing
    repository identity rules. Unknown shapes retain their exact stripped URL
    as the key, so two ambiguous spellings are never collapsed.
    """

    key: str | None
    role: str | None
    equivalence_proven: bool


@dataclass(frozen=True)
class _SnapshotRow:
    id: int
    source_id: int
    source_name: str
    source_url: str
    fetched_at: datetime
    http_status: int
    parser_version: str | None
    estimated_stored_bytes: int


@dataclass(frozen=True)
class _ObservationLink:
    card_print_id: int | None
    source_card_mapping_id: int | None
    candidate_id: int | None


@dataclass(frozen=True)
class _AttemptLink:
    status: str
    failure_stage: str | None
    failure_reason: str | None
    source_denied: bool

    @property
    def is_failure(self) -> bool:
        return (
            self.status not in _ATTEMPT_SUCCESS_STATUSES
            or self.failure_stage is not None
            or self.failure_reason is not None
            or self.source_denied
        )


@dataclass(frozen=True)
class RawSnapshotRetentionPlan:
    generated_at: str
    sample_limit: int
    totals: dict
    categories: dict
    by_source: dict
    by_age_bucket: dict
    overlaps: dict
    classification_gaps: dict
    storage_estimate: dict
    read_only: bool = True

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "policy_version": POLICY_VERSION,
            "read_only": self.read_only,
            "sample_limit": self.sample_limit,
            "policy": {
                "default_full_retention_days": DEFAULT_FULL_RETENTION_DAYS,
                "long_evidence_retention_days": LONG_EVIDENCE_RETENTION_DAYS,
                "retain_observation_linked": True,
                "retain_failure_and_source_denied_for_long_window": True,
                "retain_snkrdunk_sales_history_evidence": True,
                "retain_daily_representative_per_source_url_utc_day": True,
                "retain_audit_lineage_and_identity_evidence": True,
                "null_foreign_keys_are_never_sufficient_for_eligibility": True,
                "execution_enabled": False,
            },
            "storage_estimate": self.storage_estimate,
            "totals": self.totals,
            "categories": self.categories,
            "potentially_eligible": self.categories["potentially_eligible"],
            "lacking_sufficient_classification": self.categories[
                "unclassified_protected"
            ],
            "by_source": self.by_source,
            "by_age_bucket": self.by_age_bucket,
            "overlaps": self.overlaps,
            "classification_gaps": self.classification_gaps,
        }


def canonicalize_snapshot_url(
    source_name: str, source_url: str | None
) -> CanonicalSnapshotUrl:
    """Return a conservative key for daily representative grouping.

    Existing exact URL rules are reused and nothing broader is inferred:

    * the two published SNKRDUNK product paths merge by numeric listing id;
    * the exact, separately published SNKRDUNK sales-history path has a
      different role/key and can never merge with its product page;
    * Yuyu product URLs merge only by the existing (set_slug, product_id)
      rule; and
    * every unknown shape retains its exact spelling. Query strings, path
      variants, and hosts are not normalised for an unknown URL.
    """
    if source_url is None or not source_url.strip():
        return CanonicalSnapshotUrl(None, None, False)

    exact_url = source_url.strip()
    if source_name == "snkrdunk":
        sales_match = _SNKR_SALES_HISTORY_RE.match(exact_url)
        if sales_match is not None:
            return CanonicalSnapshotUrl(
                f"snkrdunk:sales_history:{sales_match.group(1)}",
                "snkrdunk_sales_history",
                True,
            )
        for product_pattern in _SNKR_PRODUCT_RES:
            product_match = product_pattern.match(exact_url)
            if product_match is not None:
                return CanonicalSnapshotUrl(
                    f"snkrdunk:product:{product_match.group(1)}",
                    "product",
                    True,
                )

    if source_name == "yuyutei":
        product_match = _YUYUTEI_PRODUCT_RE.match(exact_url)
        if product_match is not None:
            set_slug, product_id = product_match.groups()
            return CanonicalSnapshotUrl(
                f"yuyutei:product:{set_slug}:{product_id}",
                "product",
                True,
            )

    # Exact fallback is deliberately source-scoped and byte-for-byte after
    # trimming only surrounding whitespace. Ambiguity never grants merging.
    return CanonicalSnapshotUrl(
        f"exact:{source_name}:{exact_url}",
        None,
        False,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_bucket(fetched_at: datetime, now: datetime) -> str:
    age = now - _as_utc(fetched_at)
    if age < timedelta(days=7):
        return "<7 days"
    if age < timedelta(days=31):
        return "7-30 days"
    if age < timedelta(days=91):
        return "31-90 days"
    if age < timedelta(days=181):
        return "91-180 days"
    if age < timedelta(days=366):
        return "181-365 days"
    return ">365 days"


def _empty_bucket() -> dict:
    return {"count": 0, "estimated_stored_bytes": 0, "sample_ids": []}


def _record(bucket: dict, row: _SnapshotRow, sample_limit: int) -> None:
    bucket["count"] += 1
    bucket["estimated_stored_bytes"] += row.estimated_stored_bytes
    if len(bucket["sample_ids"]) < sample_limit:
        bucket["sample_ids"].append(row.id)


def _known_product_capture(row: _SnapshotRow, url: CanonicalSnapshotUrl) -> bool:
    if url.role != "product":
        return False
    parser_version = row.parser_version or ""
    if row.source_name == "snkrdunk":
        return parser_version.startswith("snkrdunk-collector-")
    if row.source_name == "yuyutei":
        return parser_version.startswith(("yuyutei-collector-", "yuyutei-live-"))
    return False


def _is_discovery_capture(row: _SnapshotRow) -> bool:
    return (row.parser_version or "").startswith("snkrdunk-discovery-")


def _stored_size_expression(db: Session):
    """Database-side body size without selecting the body itself."""
    if db.get_bind().dialect.name == "postgresql":
        return func.pg_column_size(RawSnapshot.raw_content)
    # SQLite tests have no TOAST/compression. Byte length is the closest
    # deterministic stand-in and keeps the same no-body-returned boundary.
    return func.length(cast(RawSnapshot.raw_content, LargeBinary))


def _load_snapshots(db: Session) -> tuple[list[_SnapshotRow], str]:
    size_expression = _stored_size_expression(db).label("estimated_stored_bytes")
    rows = db.execute(
        select(
            RawSnapshot.id,
            RawSnapshot.source_id,
            Source.name,
            RawSnapshot.source_url,
            RawSnapshot.fetched_at,
            RawSnapshot.http_status,
            RawSnapshot.parser_version,
            size_expression,
        )
        .join(Source, Source.id == RawSnapshot.source_id)
        .order_by(RawSnapshot.id)
    ).all()
    method = (
        "PostgreSQL stored-value byte estimate"
        if db.get_bind().dialect.name == "postgresql"
        else "body byte length; SQLite test approximation"
    )
    return (
        [
            _SnapshotRow(
                id=row[0],
                source_id=row[1],
                source_name=row[2],
                source_url=row[3],
                fetched_at=row[4],
                http_status=row[5],
                parser_version=row[6],
                estimated_stored_bytes=int(row[7] or 0),
            )
            for row in rows
        ],
        method,
    )


def _load_observation_links(db: Session) -> dict[int, list[_ObservationLink]]:
    links: dict[int, list[_ObservationLink]] = defaultdict(list)
    rows = db.execute(
        select(
            PriceObservation.raw_snapshot_id,
            PriceObservation.card_print_id,
            PriceObservation.source_card_mapping_id,
            PriceObservation.candidate_id,
        ).where(PriceObservation.raw_snapshot_id.is_not(None))
    ).all()
    for snapshot_id, card_print_id, mapping_id, candidate_id in rows:
        links[snapshot_id].append(
            _ObservationLink(card_print_id, mapping_id, candidate_id)
        )
    return links


def _load_attempt_links(db: Session) -> dict[int, list[_AttemptLink]]:
    links: dict[int, list[_AttemptLink]] = defaultdict(list)
    rows = db.execute(
        select(
            SourceCollectionAttempt.raw_snapshot_id,
            SourceCollectionAttempt.status,
            SourceCollectionAttempt.failure_stage,
            SourceCollectionAttempt.failure_reason,
            SourceCollectionAttempt.source_denied,
        ).where(SourceCollectionAttempt.raw_snapshot_id.is_not(None))
    ).all()
    for snapshot_id, status, stage, reason, source_denied in rows:
        links[snapshot_id].append(
            _AttemptLink(status, stage, reason, bool(source_denied))
        )
    return links


def _load_identity_keys(
    db: Session, sources_by_id: dict[int, str]
) -> tuple[set[tuple[int, str]], int]:
    """Exact/canonical URL correlations add protection, never eligibility.

    The returned count records how many evidence URLs could not be represented
    by a source-specific canonical rule and therefore remained exact-only.
    """
    keys: set[tuple[int, str]] = set()
    exact_only_count = 0

    mapping_rows = db.execute(
        select(
            SourceCardMapping.source_id,
            SourceCardMapping.source_url,
            SourceCardMapping.card_print_id,
            SourceCardMapping.manual_verified,
        ).where(SourceCardMapping.source_url.is_not(None))
    ).all()
    for source_id, source_url, card_print_id, manual_verified in mapping_rows:
        if card_print_id is None and not manual_verified:
            continue
        canonical = canonicalize_snapshot_url(
            sources_by_id.get(source_id, "<missing>"), source_url
        )
        if canonical.key is not None:
            keys.add((source_id, canonical.key))
            if not canonical.equivalence_proven:
                exact_only_count += 1

    source_ids_by_name = {name: source_id for source_id, name in sources_by_id.items()}
    candidate_rows = [
        ("snkrdunk", source_url)
        for (source_url,) in db.execute(select(SnkrdunkCandidate.source_url)).all()
    ] + [
        ("yuyutei", source_url)
        for (source_url,) in db.execute(select(YuyuteiCandidate.source_url)).all()
    ]
    for source_name, source_url in candidate_rows:
        source_id = source_ids_by_name.get(source_name)
        if source_id is None:
            continue
        canonical = canonicalize_snapshot_url(source_name, source_url)
        if canonical.key is not None:
            keys.add((source_id, canonical.key))
            if not canonical.equivalence_proven:
                exact_only_count += 1

    return keys, exact_only_count


def build_raw_snapshot_retention_plan(
    db: Session,
    *,
    sample_limit: int = 10,
    now: datetime | None = None,
) -> RawSnapshotRetentionPlan:
    if sample_limit < 0:
        raise ValueError("sample_limit must be >= 0")
    now = _as_utc(now or datetime.now(timezone.utc))

    # Prevent a caller's unrelated pending ORM changes from being flushed by
    # these SELECTs. The planner neither commits nor rolls back the caller.
    with db.no_autoflush:
        source_rows = db.execute(select(Source.id, Source.name)).all()
        sources_by_id = dict(source_rows)
        snapshots, size_method = _load_snapshots(db)
        observation_links = _load_observation_links(db)
        attempt_links = _load_attempt_links(db)
        identity_keys, exact_only_identity_urls = _load_identity_keys(db, sources_by_id)

    canonical_by_id = {
        row.id: canonicalize_snapshot_url(row.source_name, row.source_url)
        for row in snapshots
    }

    # At least one successful response per exact/canonical URL and UTC day.
    # Unknown URL forms remain exact strings, so ambiguity creates MORE
    # representatives rather than collapsing unrelated identities.
    representative_by_group: dict[tuple[str, str, object], _SnapshotRow] = {}
    for row in snapshots:
        canonical = canonical_by_id[row.id]
        if not (200 <= row.http_status < 300) or canonical.key is None:
            continue
        group = (
            row.source_name,
            canonical.key,
            _as_utc(row.fetched_at).date(),
        )
        current = representative_by_group.get(group)
        if current is None or (_as_utc(row.fetched_at), row.id) < (
            _as_utc(current.fetched_at),
            current.id,
        ):
            representative_by_group[group] = row
    representative_ids = {row.id for row in representative_by_group.values()}

    categories = {category: _empty_bucket() for category in RESULT_CATEGORIES}
    by_source: dict[str, dict] = {}
    by_age_bucket = {bucket: _empty_bucket() for bucket in AGE_BUCKETS}
    overlaps: dict[str, dict] = {}

    unclassified_missing_url = 0
    unclassified_unknown_role = 0
    exact_only_snapshot_urls = 0

    for row in snapshots:
        canonical = canonical_by_id[row.id]
        observations = observation_links.get(row.id, [])
        attempts = attempt_links.get(row.id, [])
        age = now - _as_utc(row.fetched_at)
        within_long_window = age < timedelta(days=LONG_EVIDENCE_RETENTION_DAYS)
        reasons: set[str] = set()

        if age < timedelta(days=DEFAULT_FULL_RETENTION_DAYS):
            reasons.add("recent_full_retention")
        if observations:
            reasons.add("observation_linked")
            if any(
                link.card_print_id is None
                or link.source_card_mapping_id is None
                or link.candidate_id is not None
                for link in observations
            ):
                reasons.add("audit_or_lineage_hold")

        response_is_failure = not (200 <= row.http_status < 300)
        attempt_is_failure = any(link.is_failure for link in attempts)
        source_denied = row.http_status in {403, 429} or any(
            link.source_denied for link in attempts
        )
        if within_long_window and (response_is_failure or attempt_is_failure):
            reasons.add("attempt_failure_evidence")
        if within_long_window and source_denied:
            reasons.add("source_denied_evidence")

        if canonical.role == "snkrdunk_sales_history":
            reasons.add("snkrdunk_sales_history_evidence")
        discovery_capture = _is_discovery_capture(row)
        if discovery_capture:
            reasons.add("discovery_evidence")
        if (
            canonical.key is not None
            and (row.source_id, canonical.key) in identity_keys
        ):
            reasons.add("candidate_or_identity_evidence")
        if row.id in representative_ids:
            reasons.add("daily_representative_required")

        known_role = (
            canonical.role == "snkrdunk_sales_history"
            or discovery_capture
            or bool(observations)
            or bool(attempts)
            or _known_product_capture(row, canonical)
            or (
                canonical.key is not None
                and (row.source_id, canonical.key) in identity_keys
            )
        )
        if canonical.key is None:
            unclassified_missing_url += 1
        if not canonical.equivalence_proven:
            exact_only_snapshot_urls += 1
        if not known_role:
            reasons.add("unclassified_protected")
            unclassified_unknown_role += 1

        category_names = sorted(reasons) if reasons else ["potentially_eligible"]
        for category in category_names:
            _record(categories[category], row, sample_limit)

        source_bucket = by_source.setdefault(
            row.source_name,
            {
                "count": 0,
                "estimated_stored_bytes": 0,
                "potentially_eligible_count": 0,
                "potentially_eligible_estimated_stored_bytes": 0,
            },
        )
        source_bucket["count"] += 1
        source_bucket["estimated_stored_bytes"] += row.estimated_stored_bytes
        if not reasons:
            source_bucket["potentially_eligible_count"] += 1
            source_bucket[
                "potentially_eligible_estimated_stored_bytes"
            ] += row.estimated_stored_bytes

        age_bucket = by_age_bucket[_age_bucket(row.fetched_at, now)]
        _record(age_bucket, row, sample_limit)

        if len(reasons) > 1:
            overlap_key = "+".join(sorted(reasons))
            overlap = overlaps.setdefault(overlap_key, _empty_bucket())
            _record(overlap, row, sample_limit)

    total_bytes = sum(row.estimated_stored_bytes for row in snapshots)
    classification_gaps = {
        "missing_durable_metadata": [
            {
                "field": "snapshot_role",
                "impact": (
                    "Cannot reliably distinguish every product, discovery, "
                    "sales-history, challenge, or other capture from the row alone."
                ),
            },
            {
                "field": "source_card_mapping_id_or_collection_context",
                "impact": (
                    "Daily grouping uses conservative source URL identity because "
                    "raw_snapshots has no direct mapping/run role."
                ),
            },
            {
                "field": "candidate_or_identity_evidence_link",
                "impact": (
                    "Candidate/mapping protection can only be added from exact or "
                    "existing canonical URL correlation, never removed from its absence."
                ),
            },
            {
                "field": "audit_or_lineage_hold",
                "impact": (
                    "No durable hold marker exists; only observation lineage metadata "
                    "can currently prove a hold."
                ),
            },
        ],
        "unclassified_snapshot_count": categories["unclassified_protected"]["count"],
        "missing_or_blank_url_count": unclassified_missing_url,
        "unknown_role_count": unclassified_unknown_role,
        "snapshot_urls_kept_exact_due_to_unproven_equivalence": exact_only_snapshot_urls,
        "identity_evidence_urls_kept_exact_due_to_unproven_equivalence": exact_only_identity_urls,
    }

    return RawSnapshotRetentionPlan(
        generated_at=now.isoformat(),
        sample_limit=sample_limit,
        totals={
            "snapshot_count": len(snapshots),
            "estimated_stored_bytes": total_bytes,
            "protected_snapshot_count": len(snapshots)
            - categories["potentially_eligible"]["count"],
            "potentially_eligible_snapshot_count": categories["potentially_eligible"][
                "count"
            ],
        },
        categories=categories,
        by_source=dict(sorted(by_source.items())),
        by_age_bucket=by_age_bucket,
        overlaps=dict(sorted(overlaps.items())),
        classification_gaps=classification_gaps,
        storage_estimate={
            "scope": "snapshot body value only; excludes row, index, and relation overhead",
            "method": size_method,
        },
    )


__all__ = [
    "AGE_BUCKETS",
    "DEFAULT_FULL_RETENTION_DAYS",
    "LONG_EVIDENCE_RETENTION_DAYS",
    "POLICY_VERSION",
    "PROTECTION_REASONS",
    "CanonicalSnapshotUrl",
    "RawSnapshotRetentionPlan",
    "build_raw_snapshot_retention_plan",
    "canonicalize_snapshot_url",
]
