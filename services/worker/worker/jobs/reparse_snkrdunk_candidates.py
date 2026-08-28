"""Re-derive stored SNKRDUNK candidate fields under the CURRENT rules, offline.

WHY THIS EXISTS. Discovery writes a candidate's derived fields at the moment
it parses the page. The rules then move on - a product alias is added, a
parser is sharpened - and rows written under the old rules keep their old
answers forever. Run 1 left candidates carrying `detected_set_code = NULL`
for "Extra Booster Memorial Collection" because the EB-01 alias did not exist
yet; the alias exists now and those rows still say NULL. Nothing about the
listing changed. Only our reading of it did.

Refetching to fix that would be the obvious move and the wrong one: it puts
network traffic, rate limits, and a *different day's* page content in the path
of what is purely a re-interpretation. So this job fetches nothing. It reads
the evidence already stored on the row - `title` and `image_url`, which is the
whole of what the derivation ever consults - and runs the same code discovery
runs today.

ONE INTERPRETATION, NOT TWO. The derivation is
`snkrdunk_listing_evidence.evidence_from_listing` and the field mapping is
`discover_snkrdunk_sitemap.evidence_to_candidate_fields`, both imported, both
the live discovery path's own functions. Nothing here re-reads a card code, a
product label, an alias, a rarity token or an image filename. If this module
ever grows its own regex for any of those, the thing it exists to prevent has
happened.

WHAT IT MAY REWRITE. Only the five derived fields:

    normalized_title, detected_card_code, detected_set_code,
    detected_rarity, detected_variant

Source evidence (`source_url`, `title`, `image_url`, `price_jpy`,
`listing_count`, `condition_label`, `raw_text`, `discovery_run_id`) is what the
re-derivation READS. Rewriting it would destroy the input and make the next
reparse a re-interpretation of this job's output rather than of the source.
Review state (`match_status`, `matched_card_id`, match/review columns) is a
human's decision and is never touched.

THE SAFETY CONTRACT, in the order it is enforced:

  1. Planning is the default. `--apply` is required to write anything.
  2. Scope is explicit. `--discovery-run-id` and/or `--candidate-ids`; with
     neither, the job refuses rather than defaulting to every row in the
     database.
  3. Only `match_status = 'unmatched'` rows are rewritable. A row that has
     progressed into review or approval is REFUSED - reported, not modified,
     and not silently skipped either, because a stale row that someone has
     already acted on is a fact the operator needs to see.
  4. Apply demands the confirmation phrase, typed exactly.
  5. One transaction for the whole batch.
  6. A parse failure aborts the batch. There is no partial write.
  7. A field is written only when its value actually changes, so a second
     apply against identical rules and evidence writes nothing.

No schema migration: every column read and written already exists.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.db import SessionLocal
from worker.jobs.discover_snkrdunk_sitemap import evidence_to_candidate_fields
from worker.matching.snkrdunk_listing_evidence import evidence_from_listing
from worker.models import SnkrdunkCandidate

# The five derived fields, and the only columns this job may write.
DERIVED_FIELDS = (
    "normalized_title",
    "detected_card_code",
    "detected_set_code",
    "detected_rarity",
    "detected_variant",
)

# Rewriting is confined to rows no one has acted on yet.
REWRITABLE_MATCH_STATUS = "unmatched"

CONFIRM_PHRASE = "reparse candidates"


class ReparseError(RuntimeError):
    """Refusal or failure. Raised before any write, or to abort the batch."""


@dataclass
class CandidatePlan:
    """What would happen to one candidate, decided without writing."""

    candidate_id: int
    source_url: str
    match_status: str
    before: dict[str, str | None]
    after: dict[str, str | None] | None = None
    refused_reason: str | None = None

    @property
    def refused(self) -> bool:
        return self.refused_reason is not None

    @property
    def changed_fields(self) -> list[str]:
        """Fields whose value differs. Empty for a refused row: nothing is
        offered as a change when the row may not be changed."""
        if self.after is None:
            return []
        return [f for f in DERIVED_FIELDS if self.before[f] != self.after[f]]

    @property
    def changed(self) -> bool:
        return bool(self.changed_fields)

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "source_url": self.source_url,
            "match_status": self.match_status,
            "before": self.before,
            "after": self.after,
            "changed_fields": self.changed_fields,
            "refused_reason": self.refused_reason,
        }


@dataclass
class ReparseReport:
    """The whole batch. Counts are derived, never accumulated by hand."""

    plans: list[CandidatePlan] = field(default_factory=list)
    applied: bool = False

    @property
    def changed(self) -> list[CandidatePlan]:
        return [p for p in self.plans if p.changed]

    @property
    def unchanged(self) -> list[CandidatePlan]:
        return [p for p in self.plans if not p.refused and not p.changed]

    @property
    def refused(self) -> list[CandidatePlan]:
        return [p for p in self.plans if p.refused]

    @property
    def writes(self) -> int:
        """Rows actually written. Zero on a plan, and zero on an apply whose
        rows all already carry the current derivation."""
        return len(self.changed) if self.applied else 0

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "scoped": len(self.plans),
            "changed": len(self.changed),
            "unchanged": len(self.unchanged),
            "refused": len(self.refused),
            "writes": self.writes,
            "candidates": [p.as_dict() for p in self.plans],
        }


def _current_derived(candidate: SnkrdunkCandidate) -> dict[str, str | None]:
    return {f: getattr(candidate, f) for f in DERIVED_FIELDS}


def _rederive(candidate: SnkrdunkCandidate) -> dict[str, str | None]:
    """The current rules applied to this row's stored evidence.

    Both calls are the live discovery path's own functions - see the module
    docstring. `title` and `image_url` are the only inputs, and they are read
    from the row rather than from the network.
    """
    evidence = evidence_from_listing(
        candidate.source_url, candidate.title, candidate.image_url
    )
    fields = evidence_to_candidate_fields(evidence)
    return {f: fields[f] for f in DERIVED_FIELDS}


def select_candidates(
    db: Session,
    discovery_run_id: int | None = None,
    candidate_ids: list[int] | None = None,
) -> list[SnkrdunkCandidate]:
    """The scoped rows, in id order.

    Refuses an empty scope. "Reparse everything" is a decision an operator
    makes explicitly by naming a run or a list of ids, never one this job
    makes for them by defaulting.
    """
    if discovery_run_id is None and not candidate_ids:
        raise ReparseError(
            "Refusing an unscoped reparse: pass --discovery-run-id and/or "
            "--candidate-ids. This job will not rewrite every candidate in the "
            "database by default."
        )

    stmt = select(SnkrdunkCandidate)
    if discovery_run_id is not None and candidate_ids:
        stmt = stmt.where(
            (SnkrdunkCandidate.discovery_run_id == discovery_run_id)
            | (SnkrdunkCandidate.id.in_(candidate_ids))
        )
    elif discovery_run_id is not None:
        stmt = stmt.where(SnkrdunkCandidate.discovery_run_id == discovery_run_id)
    else:
        stmt = stmt.where(SnkrdunkCandidate.id.in_(candidate_ids))

    rows = list(db.scalars(stmt.order_by(SnkrdunkCandidate.id)))

    if candidate_ids:
        found = {r.id for r in rows}
        missing = sorted(set(candidate_ids) - found)
        if missing:
            raise ReparseError(
                f"Refusing: candidate id(s) {missing} do not exist. Nothing was read "
                "or written."
            )
    return rows


def plan_reparse(
    db: Session,
    discovery_run_id: int | None = None,
    candidate_ids: list[int] | None = None,
) -> ReparseReport:
    """Decide the whole batch without writing anything.

    A parse failure on ANY row raises here, before a single field is set, so
    the batch cannot be half-applied on the way to discovering a bad row.
    """
    report = ReparseReport()
    for candidate in select_candidates(db, discovery_run_id, candidate_ids):
        before = _current_derived(candidate)

        if candidate.match_status != REWRITABLE_MATCH_STATUS:
            report.plans.append(
                CandidatePlan(
                    candidate_id=candidate.id,
                    source_url=candidate.source_url,
                    match_status=candidate.match_status,
                    before=before,
                    refused_reason=(
                        f"match_status is {candidate.match_status!r}, not "
                        f"{REWRITABLE_MATCH_STATUS!r}: this row has progressed into "
                        "review or approval and its derived fields are no longer "
                        "the job's to rewrite."
                    ),
                )
            )
            continue

        try:
            after = _rederive(candidate)
        except Exception as exc:  # noqa: BLE001 - re-raised as a batch abort
            raise ReparseError(
                f"Re-derivation failed for candidate {candidate.id} "
                f"({candidate.source_url}): {type(exc).__name__}: {exc}. "
                "The batch was abandoned; nothing was written."
            ) from exc

        report.plans.append(
            CandidatePlan(
                candidate_id=candidate.id,
                source_url=candidate.source_url,
                match_status=candidate.match_status,
                before=before,
                after=after,
            )
        )
    return report


def apply_reparse(
    db: Session,
    discovery_run_id: int | None = None,
    candidate_ids: list[int] | None = None,
    confirm: str | None = None,
    commit: bool = True,
) -> ReparseReport:
    """Plan, then write the planned changes in one transaction.

    The plan is computed first and in full: by the time any field is set,
    every row has already been re-derived successfully, so a parse failure
    cannot leave a partially rewritten batch.
    """
    if confirm != CONFIRM_PHRASE:
        raise ReparseError(
            f"Refusing to apply without the confirmation phrase. Pass "
            f'--confirm "{CONFIRM_PHRASE}".'
        )

    report = plan_reparse(db, discovery_run_id, candidate_ids)

    try:
        by_id = {
            c.id: c for c in select_candidates(db, discovery_run_id, candidate_ids)
        }
        for plan in report.changed:
            candidate = by_id[plan.candidate_id]
            # Only the fields that actually differ, so a no-op apply is a
            # no-op in the database too and not just in the report.
            for name in plan.changed_fields:
                setattr(candidate, name, plan.after[name])
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise

    report.applied = True
    return report


def format_report(report: ReparseReport) -> str:
    lines = []
    mode = "APPLIED" if report.applied else "PLAN (dry run - nothing written)"
    lines.append(f"== SNKRDUNK candidate reparse: {mode} ==")
    for plan in report.plans:
        lines.append("")
        lines.append(f"candidate {plan.candidate_id}  {plan.source_url}")
        if plan.refused:
            lines.append(f"  REFUSED: {plan.refused_reason}")
            continue
        if not plan.changed:
            lines.append("  unchanged")
            continue
        for name in plan.changed_fields:
            lines.append(
                f"  {name}: {plan.before[name]!r} -> {plan.after[name]!r}"
            )
    lines.append("")
    lines.append(
        f"scoped={len(report.plans)} changed={len(report.changed)} "
        f"unchanged={len(report.unchanged)} refused={len(report.refused)} "
        f"writes={report.writes}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Re-derive stored SNKRDUNK candidate fields under the current parsing "
            "and alias rules. Fetches nothing. Plans by default."
        )
    )
    parser.add_argument("--discovery-run-id", type=int, default=None)
    parser.add_argument(
        "--candidate-ids",
        default=None,
        help="Comma-separated candidate ids.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the planned changes. Requires --confirm.",
    )
    parser.add_argument("--confirm", default=None, help=f'Exactly: "{CONFIRM_PHRASE}"')
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    ids = (
        [int(x) for x in args.candidate_ids.split(",") if x.strip()]
        if args.candidate_ids
        else None
    )

    db = SessionLocal()
    try:
        if args.apply:
            report = apply_reparse(
                db, args.discovery_run_id, ids, confirm=args.confirm
            )
        else:
            report = plan_reparse(db, args.discovery_run_id, ids)
    except ReparseError as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        db.close()

    print(json.dumps(report.as_dict(), indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
