"""Frozen Market Value membership: read, freeze and rebuild (owner plan A, 2026-10-28).

A membership is the basket a published day was calculated with: every active,
verified Japanese physical print with its release, plus the coded releases that
had a scope. It is frozen when a day is first published and never changes after.

- ``live_membership``: today's catalogue, as the next new day will use it. Its
  revision (``card-print-release-coded-v2:``) digests the prints and the coded
  release set, so two different memberships never share a revision.
- ``load_membership``: the frozen membership a stored revision names.
- ``store_membership``: insert-only; refuses to overwrite a different one.
- ``rebuild_legacy_membership``: the days published before this ledger carry
  the v1 digest of the prints only (``current-corrected-card-print-release-v1:``).
  Their membership is rebuilt from today's catalogue restricted to prints that
  existed by the last publication, and accepted only when it hashes to exactly
  the stored digest and reproduces every stored scope and count.
- ``scope_revision``: what the engine compares for a scope. A release's basket
  changes only when its own prints change, so an import elsewhere never breaks
  an unchanged release's movement chain. Overall keeps the global revision (the
  engine does not compare it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.card_print import CardPrint
from app.models.market_value_membership import (
    MarketValueMembership,
    MarketValueMembershipPrint,
    MarketValueMembershipRelease,
)
from app.models.market_value_point import MarketValuePoint
from app.models.release_product import ReleaseProduct
from app.services.market_value import MarketValueScope
from app.services.market_value_provenance import (
    ActivePrintIdentity,
    membership_revision as revision_v1,
)

REVISION_V2_PREFIX = "card-print-release-coded-v2:"
RELEASE_SCOPE_PREFIX = "release-members-v1:"
TABLES = (
    MarketValueMembership.__tablename__,
    MarketValueMembershipPrint.__tablename__,
    MarketValueMembershipRelease.__tablename__,
)


class MembershipError(RuntimeError):
    """A frozen membership is missing, malformed or contradicted."""


@dataclass(frozen=True)
class CodedRelease:
    release_product_id: int
    official_code: str


@dataclass(frozen=True)
class FrozenMembership:
    revision: str
    prints: tuple[ActivePrintIdentity, ...]
    coded_releases: tuple[CodedRelease, ...]

    def __post_init__(self) -> None:
        prints = tuple(sorted(self.prints, key=lambda row: row.card_print_id))
        coded = tuple(sorted(self.coded_releases, key=lambda row: row.release_product_id))
        object.__setattr__(self, "prints", prints)
        object.__setattr__(self, "coded_releases", coded)
        ids = [row.card_print_id for row in prints]
        if not ids or len(ids) != len(set(ids)):
            raise MembershipError("a membership needs distinct prints")
        if any(row.card_print_id <= 0 or row.release_product_id <= 0 for row in prints):
            raise MembershipError("a membership print needs positive identities")
        releases = [row.release_product_id for row in coded]
        if len(releases) != len(set(releases)):
            raise MembershipError("a membership's coded releases must be distinct")
        if any(not row.official_code.strip() for row in coded):
            raise MembershipError("a coded release needs its official code")
        counts = self.release_counts
        if any(counts.get(row.release_product_id, 0) <= 0 for row in coded):
            raise MembershipError("a coded release scope needs at least one print")

    @cached_property
    def release_by_print(self) -> dict[int, int]:
        return {row.card_print_id: row.release_product_id for row in self.prints}

    @cached_property
    def release_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for row in self.prints:
            counts[row.release_product_id] = counts.get(row.release_product_id, 0) + 1
        return counts

    @cached_property
    def coded_release_ids(self) -> frozenset[int]:
        return frozenset(row.release_product_id for row in self.coded_releases)

    def scope_total(self, scope: MarketValueScope) -> int:
        if scope.release_product_id is None:
            return len(self.prints)
        return self.release_counts.get(scope.release_product_id, 0)

    @cached_property
    def _ids_by_release(self) -> dict[int, tuple[int, ...]]:
        grouped: dict[int, list[int]] = {}
        for row in self.prints:
            grouped.setdefault(row.release_product_id, []).append(row.card_print_id)
        return {release: tuple(ids) for release, ids in grouped.items()}

    def scope_print_ids(self, scope: MarketValueScope) -> tuple[int, ...]:
        if scope.release_product_id is None:
            return tuple(row.card_print_id for row in self.prints)
        return self._ids_by_release.get(scope.release_product_id, ())

    def scope_revision(self, scope: MarketValueScope) -> str:
        if scope.release_product_id is None:
            return self.revision
        payload = "\n".join(map(str, self.scope_print_ids(scope)))
        return (
            f"{RELEASE_SCOPE_PREFIX}{scope.release_product_id}:"
            + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        )


def revision_v2(prints, coded_releases) -> str:
    print_lines = "\n".join(
        f"{row.card_print_id}:{row.release_product_id}"
        for row in sorted(prints, key=lambda row: row.card_print_id)
    )
    release_lines = "\n".join(
        f"{row.release_product_id}:{row.official_code}"
        for row in sorted(coded_releases, key=lambda row: row.release_product_id)
    )
    payload = print_lines + "\n#coded\n" + release_lines
    return REVISION_V2_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def schema_present(db: Session) -> bool:
    inspector = inspect(db.connection())
    return all(inspector.has_table(name) for name in TABLES)


def _live_prints(db: Session, *, created_by: datetime | None = None):
    conditions = [
        CardPrint.is_active.is_(True),
        CardPrint.verification_status == "verified",
        CardPrint.language == "jp",
        CardPrint.release_product_id.is_not(None),
    ]
    if created_by is not None:
        conditions.append(CardPrint.created_at <= created_by)
    return tuple(
        ActivePrintIdentity(card_print_id=row.id, release_product_id=row.release_product_id)
        for row in db.execute(
            select(CardPrint.id, CardPrint.release_product_id)
            .where(*conditions)
            .order_by(CardPrint.id)
        )
    )


def _coded_releases(db: Session, release_ids: set[int]) -> tuple[CodedRelease, ...]:
    """Verified Bandai JP releases with an official code, among `release_ids`."""
    if not release_ids:
        return ()
    return tuple(
        CodedRelease(release_product_id=row.id, official_code=row.official_code)
        for row in db.execute(
            select(ReleaseProduct.id, ReleaseProduct.official_code)
            .where(
                ReleaseProduct.id.in_(sorted(release_ids)),
                ReleaseProduct.source_catalogue == "bandai_jp",
                ReleaseProduct.official_code.is_not(None),
                ReleaseProduct.verification_status == "verified",
            )
            .order_by(ReleaseProduct.id)
        )
    )


def live_membership(db: Session) -> FrozenMembership:
    """Today's catalogue membership, as the next new day is published with."""
    prints = _live_prints(db)
    coded = _coded_releases(db, {row.release_product_id for row in prints})
    return FrozenMembership(revision_v2(prints, coded), prints, coded)


def load_membership(db: Session, revision: str) -> FrozenMembership | None:
    row = db.scalar(
        select(MarketValueMembership).where(MarketValueMembership.revision == revision)
    )
    if row is None:
        return None
    prints = tuple(
        ActivePrintIdentity(card_print_id=p.card_print_id, release_product_id=p.release_product_id)
        for p in db.scalars(
            select(MarketValueMembershipPrint)
            .where(MarketValueMembershipPrint.membership_id == row.id)
            .order_by(MarketValueMembershipPrint.card_print_id)
        )
    )
    coded = tuple(
        CodedRelease(release_product_id=r.release_product_id, official_code=r.official_code)
        for r in db.scalars(
            select(MarketValueMembershipRelease)
            .where(MarketValueMembershipRelease.membership_id == row.id)
            .order_by(MarketValueMembershipRelease.release_product_id)
        )
    )
    membership = FrozenMembership(row.revision, prints, coded)
    expected = (
        revision_v1(prints)
        if row.revision.startswith("current-corrected-card-print-release-v1:")
        else revision_v2(prints, coded)
    )
    if (
        expected != row.revision
        or row.print_count != len(prints)
        or row.release_count != len(coded)
    ):
        raise MembershipError(f"frozen membership {row.revision} does not match its rows")
    return membership


def store_membership(db: Session, membership: FrozenMembership, *, origin: str, note: str | None = None) -> bool:
    """Insert once. True when inserted, False when the identical membership exists."""
    existing = load_membership(db, membership.revision)
    if existing is not None:
        if existing != membership:
            raise MembershipError(f"membership {membership.revision} already frozen differently")
        return False
    row = MarketValueMembership(
        revision=membership.revision,
        origin=origin,
        print_count=len(membership.prints),
        release_count=len(membership.coded_releases),
        note=note,
    )
    db.add(row)
    db.flush()
    db.add_all(
        MarketValueMembershipPrint(
            membership_id=row.id,
            card_print_id=p.card_print_id,
            release_product_id=p.release_product_id,
        )
        for p in membership.prints
    )
    db.add_all(
        MarketValueMembershipRelease(
            membership_id=row.id,
            release_product_id=r.release_product_id,
            official_code=r.official_code,
        )
        for r in membership.coded_releases
    )
    db.flush()
    if load_membership(db, membership.revision) != membership:
        raise MembershipError("stored membership does not read back identically")
    return True


@dataclass(frozen=True)
class LegacyRebuild:
    revision: str
    as_of: datetime | None
    membership: FrozenMembership | None
    facts: dict

    @property
    def ok(self) -> bool:
        return self.membership is not None


def rebuild_legacy_membership(db: Session, revision: str) -> LegacyRebuild:
    """Rebuild the membership a pre-ledger (v1) revision was published with.

    Candidate: today's active/verified/jp prints with a release, created by the
    newest point carrying `revision`. Accepted only when its v1 digest is exactly
    `revision`, the coded releases with prints are exactly the release scopes
    stored under `revision`, and every stored total_physical_print_count (Overall
    and each release, on every date) equals the candidate's count. Anything else
    returns no membership and the facts that disagree. Read only.
    """
    facts: dict = {"revision": revision}
    if not revision.startswith("current-corrected-card-print-release-v1:"):
        facts["refused"] = "not a pre-ledger (v1) revision"
        return LegacyRebuild(revision, None, None, facts)
    points = db.execute(
        select(
            MarketValuePoint.release_product_id,
            MarketValuePoint.total_physical_print_count,
            MarketValuePoint.created_at,
        ).where(MarketValuePoint.membership_revision == revision)
    ).all()
    if not points:
        facts["refused"] = "no point carries this revision"
        return LegacyRebuild(revision, None, None, facts)
    as_of = max(row.created_at for row in points)
    prints = _live_prints(db, created_by=as_of)
    digest = revision_v1(prints)
    candidate_counts: dict[int, int] = {}
    for row in prints:
        candidate_counts[row.release_product_id] = candidate_counts.get(row.release_product_id, 0) + 1
    stored_scopes = {row.release_product_id for row in points if row.release_product_id is not None}
    stored_totals = {
        (row.release_product_id, row.total_physical_print_count) for row in points
    }
    expected_totals = {
        (release_id, len(prints) if release_id is None else candidate_counts.get(release_id, 0))
        for release_id, _ in stored_totals
    }
    coded = _coded_releases(db, set(candidate_counts))
    facts.update(
        as_of=as_of.isoformat(),
        candidate_prints=len(prints),
        candidate_revision=digest,
        digest_matches=digest == revision,
        stored_release_scopes=len(stored_scopes),
        candidate_coded_releases=len(coded),
        scopes_match={row.release_product_id for row in coded} == stored_scopes,
        totals_match=stored_totals == expected_totals,
    )
    if facts["scopes_match"] is False:
        coded_ids = {row.release_product_id for row in coded}
        facts["scopes_only_stored"] = sorted(stored_scopes - coded_ids)[:20]
        facts["scopes_only_candidate"] = sorted(coded_ids - stored_scopes)[:20]
    if not (facts["digest_matches"] and facts["scopes_match"] and facts["totals_match"]):
        return LegacyRebuild(revision, as_of, None, facts)
    return LegacyRebuild(revision, as_of, FrozenMembership(revision, prints, coded), facts)


def _content_sha(value: FrozenMembership) -> str:
    payload = "\n".join(f"{r.card_print_id}:{r.release_product_id}" for r in value.prints)
    payload += "\n#coded\n" + "\n".join(
        f"{r.release_product_id}:{r.official_code}" for r in value.coded_releases
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def legacy_freeze_plan(db: Session):
    """(plan or None, problems, facts). Read only. Every revision stored on points
    without a frozen membership is rebuilt (rebuild_legacy_membership); the plan
    lists each with its counts and content digest. Any rebuild that does not
    reproduce its revision exactly is a problem: nothing is planned."""
    if not schema_present(db):
        return None, ["market value membership schema is absent (apply its migration first)"], {}
    revisions = sorted(set(db.scalars(select(MarketValuePoint.membership_revision).distinct())))
    missing = [r for r in revisions if load_membership(db, r) is None]
    facts: dict = {"stored_revisions": len(revisions), "unfrozen": len(missing), "rebuilds": []}
    problems, entries = [], []
    for revision in missing:
        rebuilt = rebuild_legacy_membership(db, revision)
        facts["rebuilds"].append(rebuilt.facts)
        if not rebuilt.ok:
            problems.append(f"{revision} cannot be rebuilt exactly: {rebuilt.facts.get('refused') or 'see facts'}")
            continue
        entries.append({
            "revision": revision,
            "prints": len(rebuilt.membership.prints),
            "coded_releases": len(rebuilt.membership.coded_releases),
            "content_sha256": _content_sha(rebuilt.membership),
        })
    if not missing:
        problems.append("every stored revision already has a frozen membership")
    if problems:
        return None, problems, facts
    return {"memberships": entries}, [], facts


def apply_legacy_freeze(db: Session, approved: dict) -> list[str]:
    """Freeze exactly the approved rebuilt memberships, after re-planning in this
    transaction. The caller holds the market value writer lock and commits."""
    plan, problems, _ = legacy_freeze_plan(db)
    if problems:
        raise MembershipError("; ".join(problems))
    if plan != approved:
        raise MembershipError("the freeze plan differs from the approved dry run")
    frozen = []
    for entry in plan["memberships"]:
        rebuilt = rebuild_legacy_membership(db, entry["revision"])
        if not rebuilt.ok or _content_sha(rebuilt.membership) != entry["content_sha256"]:
            raise MembershipError(f"{entry['revision']} changed while freezing")
        store_membership(
            db,
            rebuilt.membership,
            origin="legacy_rebuilt",
            note=f"rebuilt as of {rebuilt.as_of.isoformat()} (prints created by the last publication)",
        )
        frozen.append(entry["revision"])
    return frozen


__all__ = [
    "apply_legacy_freeze",
    "legacy_freeze_plan",
    "CodedRelease",
    "FrozenMembership",
    "LegacyRebuild",
    "MembershipError",
    "live_membership",
    "load_membership",
    "rebuild_legacy_membership",
    "revision_v2",
    "schema_present",
    "store_membership",
]
