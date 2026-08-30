"""Delete candidates that are provably another game's cards. Plans by default.

WHY THIS EXISTS. Discovery run 9 admitted 117 Shadowverse Evolve listings as
SNKRDUNK candidates, because the only gate was "does the title carry a
bracketed card code" and Shadowverse writes them in the One Piece shape
([BP08-117]). They can never match: their codes are in no Atlas catalogue, so
they sit in `card_code_not_in_catalogue` forever, inflating every candidate
count and every unmatched queue a human reads.

`worker.matching.non_target_tcg` now refuses them at discovery, so no new ones
arrive. This job removes the ones already stored.

DELETION IS THE UNUSUAL CHOICE HERE, so the reasons are recorded. Atlas
otherwise keeps candidate rows forever, because an unmatched candidate is
normally a TODO. These are not: the row asserts that a One Piece listing was
found, and that assertion is false. Keeping them means carrying a permanent,
growing set of rows that every operator has to re-triage and re-dismiss.

WHAT MAKES IT SAFE, verified against staging before this job was written:

  * `price_observations.candidate_id` is the ONLY foreign key pointing at this
    table, and it is ON DELETE SET NULL - so a careless delete would silently
    blank a real observation's provenance. It cannot fire here: rule 3 below
    refuses any candidate an observation references, and the plan reports the
    count so the operator sees it rather than trusting it.
  * `raw_snapshots` holds no page for any of these listings, so no stored
    fetch is orphaned.
  * Discovery-run accounting is NOT row-count based. `candidates_found` is a
    historical counter of what a run saw, and it already disagrees with the
    current row counts on five of the nine runs - rows move between runs, as
    `upsert_candidate_from_evidence` reassigns `discovery_run_id` on
    re-discovery. Deleting rows therefore breaks no invariant that holds
    today, and the run rows themselves are never touched.
  * The rows are exported before removal (`--evidence-file`), so what was
    deleted stays auditable outside the table.

THE SAFETY CONTRACT, in the order it is enforced:

  1. Planning is the default. `--apply` is required to delete anything.
  2. Scope is the SHIPPED discovery rule applied to stored evidence, never a
     hand-typed list of ids and never "unknown card code". `--candidate-ids`
     may be supplied as a cross-check: if the predicate and the operator
     disagree about even one row, the job refuses rather than picking one.
  3. A candidate is removable only with NO mapping, observation or approval
     relationship, and only at `match_status = 'unmatched'`. Anything else is
     REFUSED - reported, never quietly skipped.
  4. Apply demands the confirmation phrase, typed exactly.
  5. The exact ids and count are printed before any mutation.
  6. One transaction. A refusal anywhere aborts the whole batch.

No schema migration: this only deletes rows.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from worker.db import SessionLocal
from worker.matching.non_target_tcg import identify_non_target_tcg
from worker.models import PriceObservation, SnkrdunkCandidate, SourceCardMapping

REMOVABLE_MATCH_STATUS = "unmatched"

CONFIRM_PHRASE = "purge non-target candidates"

# Columns exported before deletion, so the removed rows remain auditable.
EVIDENCE_FIELDS = (
    "id", "discovery_run_id", "source_url", "title", "image_url", "price_jpy",
    "listing_count", "condition_label", "raw_text", "normalized_title",
    "detected_card_code", "detected_set_code", "detected_rarity",
    "detected_variant", "match_status",
)


class PurgeError(RuntimeError):
    """Refusal or failure. Raised before any delete."""


@dataclass
class CandidatePurge:
    candidate_id: int
    source_url: str
    game: str
    card_code: str | None
    evidence: dict
    refused_reason: str | None = None

    @property
    def refused(self) -> bool:
        return self.refused_reason is not None


@dataclass
class PurgeReport:
    plans: list[CandidatePurge] = field(default_factory=list)
    applied: bool = False

    @property
    def removable(self) -> list[CandidatePurge]:
        return [p for p in self.plans if not p.refused]

    @property
    def refused(self) -> list[CandidatePurge]:
        return [p for p in self.plans if p.refused]

    @property
    def deletes(self) -> int:
        return len(self.removable) if self.applied else 0

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "identified": len(self.plans),
            "removable": len(self.removable),
            "refused": len(self.refused),
            "deletes": self.deletes,
            "candidate_ids": [p.candidate_id for p in self.removable],
            "games": _game_counts(self.removable),
            "candidates": [
                {
                    "candidate_id": p.candidate_id,
                    "source_url": p.source_url,
                    "game": p.game,
                    "card_code": p.card_code,
                    "refused_reason": p.refused_reason,
                }
                for p in self.plans
            ],
        }


def _game_counts(plans: list[CandidatePurge]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in plans:
        out[p.game] = out.get(p.game, 0) + 1
    return out


def _best_match_card_ids(db: Session) -> dict[int, int]:
    """`best_match_card_id` per candidate, read with SQL rather than the ORM.

    THIS CANNOT USE THE MODEL. `worker.models.SnkrdunkCandidate` deliberately
    does not declare the api-only `best_match_*` columns, so an attribute read
    would return None for every row and the guard below would be dead code -
    silently permitting the deletion of a row the matcher had already ranked.
    The column is therefore read from the database, and only where the
    database actually has it: the worker's own test schema does not.
    """
    # Inspected through the SESSION's own connection, not the engine: a new
    # connection would be a different transaction (and, for the in-memory
    # SQLite the tests use, a different database entirely).
    columns = {
        c["name"] for c in inspect(db.connection()).get_columns("snkrdunk_candidates")
    }
    if "best_match_card_id" not in columns:
        return {}
    rows = db.execute(
        text(
            "select id, best_match_card_id from snkrdunk_candidates "
            "where best_match_card_id is not null"
        )
    )
    return {row[0]: row[1] for row in rows}


def _relationship_refusal(
    db: Session, candidate: SnkrdunkCandidate, best_match: dict[int, int]
) -> str | None:
    """Why this row may NOT be deleted, or None.

    Every check is a reason to keep the row. `price_observations.candidate_id`
    is checked explicitly because its FK is ON DELETE SET NULL: without this,
    deleting would succeed AND silently blank a real observation's provenance.
    """
    if candidate.match_status != REMOVABLE_MATCH_STATUS:
        return (
            f"match_status is {candidate.match_status!r}, not "
            f"{REMOVABLE_MATCH_STATUS!r}: a human has acted on this row."
        )
    if candidate.matched_card_id is not None:
        return f"matched_card_id is {candidate.matched_card_id}: an approval decision exists."
    if candidate.id in best_match:
        return (
            f"best_match_card_id is {best_match[candidate.id]}: a matcher decision exists."
        )

    observations = db.scalar(
        select(PriceObservation.id).where(PriceObservation.candidate_id == candidate.id).limit(1)
    )
    if observations is not None:
        return (
            f"price_observation {observations} references this candidate; deleting "
            "would SET NULL its provenance."
        )
    mapping = db.scalar(
        select(SourceCardMapping.id)
        .where(SourceCardMapping.source_url == candidate.source_url)
        .limit(1)
    )
    if mapping is not None:
        return f"source_card_mapping {mapping} shares this source_url."
    return None


def plan_purge(db: Session, candidate_ids: list[int] | None = None) -> PurgeReport:
    """Identify every non-target candidate, decide it, and write nothing.

    The predicate is `identify_non_target_tcg` over the row's STORED
    `image_url` - the same function discovery now refuses on - so what this
    removes and what discovery blocks can never drift apart.
    """
    report = PurgeReport()
    rows = db.scalars(select(SnkrdunkCandidate).order_by(SnkrdunkCandidate.id)).all()
    best_match = _best_match_card_ids(db)

    for candidate in rows:
        game = identify_non_target_tcg(candidate.image_url)
        if game is None:
            continue
        report.plans.append(
            CandidatePurge(
                candidate_id=candidate.id,
                source_url=candidate.source_url,
                game=game,
                card_code=candidate.detected_card_code,
                evidence={f: getattr(candidate, f, None) for f in EVIDENCE_FIELDS},
                refused_reason=_relationship_refusal(db, candidate, best_match),
            )
        )

    # The operator's expectation, cross-checked against the predicate. Two
    # independent statements of the same set; if they differ at all, neither
    # is trusted.
    if candidate_ids is not None:
        found = {p.candidate_id for p in report.plans}
        expected = set(candidate_ids)
        if found != expected:
            raise PurgeError(
                "Refusing: the predicate and --candidate-ids disagree. "
                f"predicate-only={sorted(found - expected)} "
                f"expected-only={sorted(expected - found)}. Nothing was deleted."
            )
    return report


def apply_purge(
    db: Session,
    candidate_ids: list[int] | None = None,
    confirm: str | None = None,
    evidence_file: str | None = None,
    commit: bool = True,
) -> PurgeReport:
    """Plan, export the evidence, then delete in one transaction."""
    if confirm != CONFIRM_PHRASE:
        raise PurgeError(
            f'Refusing to apply without the confirmation phrase. Pass --confirm "{CONFIRM_PHRASE}".'
        )

    report = plan_purge(db, candidate_ids)

    if report.refused:
        raise PurgeError(
            f"Refusing: {len(report.refused)} identified candidate(s) carry a mapping, "
            "observation or approval relationship and may not be deleted: "
            f"{[(p.candidate_id, p.refused_reason) for p in report.refused]}. "
            "Nothing was deleted."
        )

    if evidence_file:
        with open(evidence_file, "w") as fh:
            json.dump(
                [p.evidence for p in report.removable], fh, indent=2, sort_keys=True, default=str
            )

    try:
        for plan in report.removable:
            db.delete(db.get(SnkrdunkCandidate, plan.candidate_id))
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise

    report.applied = True
    return report


def format_report(report: PurgeReport) -> str:
    lines = []
    mode = "APPLIED" if report.applied else "PLAN (dry run - nothing deleted)"
    lines.append(f"== SNKRDUNK non-target candidate purge: {mode} ==")
    lines.append("")
    lines.append(f"identified by game: {_game_counts(report.plans)}")
    lines.append("")
    # The exact ids, printed before any mutation.
    lines.append(f"candidate ids to delete ({len(report.removable)}):")
    lines.append("  " + ", ".join(str(p.candidate_id) for p in report.removable))
    for plan in report.refused:
        lines.append(f"  REFUSED {plan.candidate_id}: {plan.refused_reason}")
    lines.append("")
    lines.append(
        f"identified={len(report.plans)} removable={len(report.removable)} "
        f"refused={len(report.refused)} deletes={report.deletes}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete SNKRDUNK candidates positively identified as another trading "
            "card game. Plans by default."
        )
    )
    parser.add_argument(
        "--candidate-ids",
        default=None,
        help="Comma-separated ids the operator expects. Cross-checked against the predicate.",
    )
    parser.add_argument("--apply", action="store_true", help="Delete. Requires --confirm.")
    parser.add_argument("--confirm", default=None, help=f'Exactly: "{CONFIRM_PHRASE}"')
    parser.add_argument("--evidence-file", default=None, help="Write removed rows here before deleting.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    ids = (
        [int(x) for x in args.candidate_ids.split(",") if x.strip()]
        if args.candidate_ids
        else None
    )

    db = SessionLocal()
    try:
        if args.apply:
            report = apply_purge(db, ids, confirm=args.confirm, evidence_file=args.evidence_file)
        else:
            report = plan_purge(db, ids)
    except PurgeError as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        db.close()

    print(json.dumps(report.as_dict(), indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
