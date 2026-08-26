"""CLI: fill `canonical_cards.name_en` from the frozen Bandai Asia-EN snapshot.

    # plan only - the default. Classifies every card and writes nothing.
    python -m app.backfill_canonical_english_names --database-url postgresql+psycopg://...

    # apply - requires the exact confirmation phrase, nothing else works
    python -m app.backfill_canonical_english_names --database-url ... \\
        --apply --confirm BACKFILL_CANONICAL_ENGLISH_NAMES

WHAT `name_en` MEANS AFTER THIS RUN

    "Bandai's verbatim Asia-EN canonical card name for this card_code."

That is the whole contract, and every rule below exists to keep it true. The
stored string is the published one, byte for byte: nothing is normalised
before storage, nothing is translated, nothing is inferred from a Japanese
name, and no value is ever chosen by "first occurrence" or by product order.

THE ONE THING THAT IS SET ASIDE, AND WHY IT IS NOT NORMALISATION. A card code
is published once per official artwork, so `EB01-012` appears as both
'Cavendish' and 'Cavendish (Parallel)'. `(Parallel)` is a *printing* label -
Atlas already records that distinction in `card_prints.official_asset_variant`
- and attaching it to a card-level name would file a printing fact under the
wrong entity. So a trailing tag from a closed allow-list (VARIANT_NAME_TAGS)
is set aside when reading occurrences, and the remaining string is stored
untouched. The allow-list is deliberately not "any trailing parenthetical":
four cards published by Bandai carry a character alias in exactly that shape -
'Mr.1(Daz.Bonez)', 'Miss Doublefinger(Zala)' - and stripping those would
corrupt the name.

FAIL-CLOSED GATES. Nothing is written unless all of these hold:

    1. the snapshot on disk is the reviewed one - its three record files
       hash to the digests in its own manifest, and that manifest's
       snapshot_identity equals REVIEWED_SNAPSHOT_IDENTITY;
    2. every card_code in the snapshot resolves to exactly one name;
    3. every non-NULL `name_en` already stored either equals the official
       name, or is one of the three specifically reviewed punctuation
       reconciliations below. Any other disagreement aborts the whole run.

WHAT IS WRITTEN, AND WHAT IS NOT. One UPDATE per affected card, all inside one
transaction, touching one column. `name_jp` never appears in a SET clause and
is never read for matching. No print, product, mapping, observation or index
row is read or written, and this module has no code path that creates a row.

THE THREE RECONCILIATIONS. Twelve of the fifteen pre-existing `name_en` values
already agree with Bandai verbatim. Three differ only in punctuation, because
they were hand-entered with spaces where Bandai writes dot-separated names.
They are reconciled here - deliberately, with each old value named in
REVIEWED_RECONCILIATIONS - so the column has one semantic contract rather than
two. A stored value that is neither the official name nor the exact reviewed
old value is an unexpected disagreement and aborts.

IDEMPOTENCY. A card is only written when its stored value differs from the
official name, so a second run against unchanged state selects nothing and
writes nothing. There is no upsert and no unconditional UPDATE.

Exit codes
----------
    0  the plan was produced, or the apply succeeded
    1  a fail-closed gate refused the run
    2  usage error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.models import CanonicalCard

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

CONFIRM_PHRASE = "BACKFILL_CANONICAL_ENGLISH_NAMES"

DEFAULT_SNAPSHOT = Path("data/official_snapshots/bandai_asia_en/current")
SOURCE_CATALOGUE = "bandai_asia_en"

# The snapshot audited in 4E-2: 62 series, 4,901 entries, 2,809 card codes,
# zero material name conflicts. Pinned so a differently-shaped snapshot - a
# refetch, a partial run, an edited file - cannot be applied without being
# reviewed and this constant being updated deliberately.
REVIEWED_SNAPSHOT_IDENTITY = (
    "549f3a39281a3bf78f3299017e7134555244ff4edb6252d335e9d65b02199978"
)
RECORD_FILES = ("series.jsonl", "entries.jsonl", "assets.jsonl")

# Trailing tags that name a *printing* rather than the card. Closed on
# purpose - see the module docstring's note about character aliases.
VARIANT_NAME_TAGS = ("Parallel",)
_VARIANT_TAG_RE = re.compile(
    r"\s*\((?:" + "|".join(re.escape(t) for t in VARIANT_NAME_TAGS) + r")\)\s*$"
)

# card_code -> the exact stored value a reconciliation is allowed to replace.
# Naming the old string, rather than "overwrite anything that differs", is what
# keeps this an explicit review decision instead of a general licence to
# overwrite.
REVIEWED_RECONCILIATIONS: dict[str, str] = {
    "OP02-013": "Portgas D. Ace",
    "OP03-001": "Portgas D. Ace",
    "OP04-090": "Monkey D. Luffy",
}


class BackfillRefused(RuntimeError):
    """A fail-closed gate said no. Reported, never worked around.

    Carries the plan when one was built, so the caller can print exactly which
    rows caused the refusal instead of only saying that something did.
    """

    def __init__(self, message: str, plan: "BackfillPlan | None" = None) -> None:
        super().__init__(message)
        self.plan = plan


def emit(line: str = "") -> None:
    print(line, flush=True)


# --- the snapshot ------------------------------------------------------------


def verify_snapshot_identity(root: Path) -> dict[str, Any]:
    """Prove this directory is the reviewed snapshot, or refuse.

    Two independent checks, because they catch different accidents: hashing
    the record files catches an edited or truncated file whose manifest still
    claims the old digest, and comparing the manifest's own identity to the
    pinned constant catches a *different* snapshot that is internally
    consistent - a refetch, say - being applied without review.
    """
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise BackfillRefused(f"no manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    catalogue = manifest.get("source_catalogue")
    if catalogue != SOURCE_CATALOGUE:
        raise BackfillRefused(
            f"snapshot source_catalogue is {catalogue!r}, expected {SOURCE_CATALOGUE!r}"
        )

    claimed = manifest.get("file_digests") or {}
    for name in RECORD_FILES:
        path = root / name
        if not path.exists():
            raise BackfillRefused(f"snapshot is missing {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if claimed.get(name) != actual:
            raise BackfillRefused(
                f"{name} does not match its manifest digest - the snapshot has been "
                f"altered since it was written"
            )

    recomputed = hashlib.sha256(
        json.dumps(claimed, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if recomputed != manifest.get("snapshot_identity"):
        raise BackfillRefused("manifest snapshot_identity does not match its own digests")
    if recomputed != REVIEWED_SNAPSHOT_IDENTITY:
        raise BackfillRefused(
            f"snapshot identity {recomputed} is not the reviewed snapshot "
            f"{REVIEWED_SNAPSHOT_IDENTITY} - review it and update the constant"
        )
    return manifest


def strip_variant_tag(name: str) -> str:
    """Set aside a printing label. Never a general strip - see the docstring."""
    return _VARIANT_TAG_RE.sub("", name).strip()


def resolve_names(root: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(card_code -> the one published name, card_code -> conflicting names).

    A code whose occurrences disagree on the name is returned as a conflict
    and gets no entry in the resolved map, so it can never be written. No
    winner is chosen - not the first occurrence, not the most common, not the
    one from the earliest product.
    """
    by_code: dict[str, set[str]] = {}
    with (root / "entries.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line)
            code = entry.get("card_code")
            name = (entry.get("card_name") or "").strip()
            if not code or not name:
                continue
            by_code.setdefault(code, set()).add(strip_variant_tag(name))

    resolved: dict[str, str] = {}
    conflicts: dict[str, list[str]] = {}
    for code, names in by_code.items():
        cleaned = {n for n in names if n}
        if len(cleaned) == 1:
            resolved[code] = next(iter(cleaned))
        elif cleaned:
            conflicts[code] = sorted(cleaned)
    return resolved, conflicts


# --- the plan ----------------------------------------------------------------


@dataclass
class BackfillPlan:
    """What one run would do, decided before anything is written."""

    snapshot_identity: str
    fills: list[tuple[int, str, str]] = field(default_factory=list)
    reconciliations: list[tuple[int, str, str, str]] = field(default_factory=list)
    already_matching: list[str] = field(default_factory=list)
    unpublished: list[str] = field(default_factory=list)
    unexpected_conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    source_conflicts: dict[str, list[str]] = field(default_factory=dict)

    @property
    def write_count(self) -> int:
        return len(self.fills) + len(self.reconciliations)

    def counts(self) -> dict[str, int]:
        return {
            "null_to_fill": len(self.fills),
            "existing_exact_match": len(self.already_matching),
            "reviewed_reconciliations": len(self.reconciliations),
            "unpublished_remain_null": len(self.unpublished),
            "unexpected_conflicts": len(self.unexpected_conflicts),
            "source_name_conflicts": len(self.source_conflicts),
            "total_writes": self.write_count,
        }


def build_plan(
    db: Session,
    resolved: dict[str, str],
    source_conflicts: dict[str, list[str]],
    snapshot_identity: str,
) -> BackfillPlan:
    """Classify every canonical card. Reads only; decides nothing by guessing."""
    plan = BackfillPlan(snapshot_identity=snapshot_identity, source_conflicts=source_conflicts)

    rows = db.execute(
        select(CanonicalCard.id, CanonicalCard.card_code, CanonicalCard.name_en)
        .order_by(CanonicalCard.id.asc())
    ).all()

    for card_id, card_code, stored in rows:
        official = resolved.get(card_code)
        if official is None:
            # Either genuinely unpublished in English, or a code whose source
            # names conflict. Both mean "no authoritative value", both stay NULL.
            plan.unpublished.append(card_code)
            continue
        if stored is None:
            plan.fills.append((card_id, card_code, official))
        elif stored == official:
            plan.already_matching.append(card_code)
        elif REVIEWED_RECONCILIATIONS.get(card_code) == stored:
            plan.reconciliations.append((card_id, card_code, stored, official))
        else:
            plan.unexpected_conflicts.append((card_code, stored, official))

    return plan


def apply_plan(db: Session, plan: BackfillPlan) -> int:
    """Write the plan inside the caller's transaction.

    One executemany UPDATE keyed on the primary key, with `name_en` as the
    only column in the SET clause - `name_jp` never appears there and is never
    read. Batched rather than row-by-row so 2,694 writes are one statement
    instead of 2,694 round trips.
    """
    payload = [
        {"id": card_id, "name_en": official}
        for card_id, _code, official in plan.fills
    ] + [
        {"id": card_id, "name_en": official}
        for card_id, _code, _old, official in plan.reconciliations
    ]
    if not payload:
        return 0
    db.execute(update(CanonicalCard), payload)
    return len(payload)


def print_plan(plan: BackfillPlan) -> None:
    emit(f"snapshot_identity: {plan.snapshot_identity}")
    for key, value in plan.counts().items():
        emit(f"{key}: {value}")
    if plan.reconciliations:
        emit()
        emit("reviewed punctuation reconciliations:")
        for _id, code, old, new in plan.reconciliations:
            emit(f"  {code}: {old!r} -> {new!r}")
    if plan.unpublished:
        emit()
        emit("remaining NULL (no authoritative Asia-EN name):")
        for code in plan.unpublished:
            emit(f"  {code}")
    if plan.unexpected_conflicts:
        emit()
        emit("UNEXPECTED existing name_en disagreements:")
        for code, stored, official in plan.unexpected_conflicts:
            emit(f"  {code}: stored={stored!r} official={official!r}")
    if plan.source_conflicts:
        emit()
        emit("card codes whose Asia-EN occurrences disagree:")
        for code, names in plan.source_conflicts.items():
            emit(f"  {code}: {names}")


def guard_plan(plan: BackfillPlan) -> None:
    """Refuse the run rather than write a partially-trusted result."""
    if plan.source_conflicts:
        raise BackfillRefused(
            f"{len(plan.source_conflicts)} card code(s) resolve to more than one "
            f"Asia-EN name; no winner is chosen and nothing is written",
            plan,
        )
    if plan.unexpected_conflicts:
        raise BackfillRefused(
            f"{len(plan.unexpected_conflicts)} card(s) already carry a name_en that is "
            f"neither the official name nor a reviewed reconciliation",
            plan,
        )


def run(
    db: Session,
    snapshot_root: Path,
    *,
    apply: bool = False,
) -> BackfillPlan:
    """Verify, plan, guard, and - only with `apply` - write."""
    manifest = verify_snapshot_identity(snapshot_root)
    resolved, source_conflicts = resolve_names(snapshot_root)
    plan = build_plan(db, resolved, source_conflicts, manifest["snapshot_identity"])
    guard_plan(plan)
    if apply:
        apply_plan(db, plan)
        db.commit()
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True, help="SQLAlchemy URL to write to.")
    parser.add_argument(
        "--snapshot", default=str(DEFAULT_SNAPSHOT),
        help=f"Frozen Asia-EN snapshot directory (default: {DEFAULT_SNAPSHOT}).",
    )
    parser.add_argument("--apply", action="store_true", help="Write. Without it, plan only.")
    parser.add_argument("--confirm", default=None, help=f"Must be {CONFIRM_PHRASE!r} to apply.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.confirm != CONFIRM_PHRASE:
        emit(f"REFUSED: --apply requires --confirm {CONFIRM_PHRASE}")
        return EXIT_USAGE

    engine = create_engine(args.database_url)
    try:
        with Session(engine) as db:
            try:
                plan = run(db, Path(args.snapshot), apply=args.apply)
            except BackfillRefused as exc:
                # A refusal never leaves a partial write - nothing has been
                # committed - but it must still name the rows that caused it,
                # or an operator cannot act on the report.
                db.rollback()
                emit(f"REFUSED: {exc}")
                if exc.plan is not None:
                    emit()
                    print_plan(exc.plan)
                return EXIT_REFUSED
            emit("applied: " + ("yes" if args.apply else "no (plan only)"))
            print_plan(plan)
    finally:
        engine.dispose()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
