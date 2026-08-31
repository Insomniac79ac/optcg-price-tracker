"""Write DECLARED storefront renderings for products that already exist.

WHY THIS EXISTS SEPARATELY FROM THE CATALOGUE IMPORTER. Source renderings
normally reach the database through
`import_frozen_bandai_to_canonical_staging`, which establishes an uncoded
product from Bandai evidence and records the storefront spellings for it in
the same transaction. That is the right shape when the product is NEW.

It is the wrong shape when the product already exists and only a spelling is
missing. Re-running the catalogue importer to add three alias rows would put
product creation, print import and canonical-card creation back in the path of
a change that touches none of them - a large blast radius for a small, purely
additive fact. So this command does exactly one thing.

WHAT IT MAY WRITE, and nothing else:

    INSERT INTO release_product_aliases (product_id, alias_name,
                                         alias_kind='source_rendering',
                                         source_url=NULL)

No product is created, renamed, verified or unverified. No print, canonical
card, mapping, candidate or observation is touched. There is no UPDATE and no
DELETE anywhere in this module.

WHERE THE ROWS COME FROM. `app.services.uncoded_source_renderings`, and only
there. This command cannot be given an arbitrary label on the command line -
a rendering has to be declared in that table, with its observed card codes and
its evidence, before it can reach the database. That is the whole point of the
table, and a CLI flag that bypassed it would make the evidence standard
optional.

`source_url` is left NULL deliberately, matching
canonical_import_apply._create_source_renderings: the provenance of a source
rendering is the declared table, and minting a plausible storefront URL to
fill the column would fabricate exactly the evidence the column is for.

THE PRODUCT IS MATCHED BY NAME, EXACTLY. `release_products.display_name` or
`first_seen_name` must equal the rendering's `product_name` verbatim - no
normalisation, no fuzzy matching, no "closest product". A name that matches no
product, or more than one, is REFUSED and nothing in the batch is written:
attaching a storefront spelling to the wrong product is precisely the error
that would then teach the collector to accept a wrong release.

Plans by default. `--apply` requires `--confirm "add source renderings"`.
Idempotent: a rendering already present is reported as `present` and re-running
writes nothing.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReleaseProduct, ReleaseProductAlias
from app.services.uncoded_source_renderings import (
    SOURCE_RENDERING,
    UNCODED_SOURCE_RENDERINGS,
    SourceRendering,
)

CONFIRM_PHRASE = "add source renderings"


class SourceRenderingError(RuntimeError):
    """Refusal. Raised before any write, so a refused batch writes nothing."""


@dataclass
class RenderingPlan:
    source_name: str
    source_label: str
    product_name: str
    membership_relation: str
    observed_card_codes: tuple[str, ...]
    product_id: int | None = None
    product_official_code: str | None = None
    action: str = "refuse"
    refusal: str | None = None

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_label": self.source_label,
            "product_name": self.product_name,
            "product_id": self.product_id,
            "product_official_code": self.product_official_code,
            "membership_relation": self.membership_relation,
            "observed_card_codes": list(self.observed_card_codes),
            "action": self.action,
            "refusal": self.refusal,
        }


@dataclass
class RenderingReport:
    plans: list[RenderingPlan] = field(default_factory=list)
    applied: bool = False

    @property
    def to_create(self) -> list[RenderingPlan]:
        return [p for p in self.plans if p.action == "create"]

    @property
    def present(self) -> list[RenderingPlan]:
        return [p for p in self.plans if p.action == "present"]

    @property
    def refused(self) -> list[RenderingPlan]:
        return [p for p in self.plans if p.action == "refuse"]

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "scoped": len(self.plans),
            "to_create": len(self.to_create),
            "already_present": len(self.present),
            "refused": len(self.refused),
            "writes": len(self.to_create) if self.applied else 0,
            "renderings": [p.as_dict() for p in self.plans],
        }


def _find_product(db: Session, product_name: str) -> tuple[ReleaseProduct | None, str | None]:
    """The one product published under this exact name, or a refusal reason."""
    rows = db.scalars(
        select(ReleaseProduct).where(
            (ReleaseProduct.display_name == product_name)
            | (ReleaseProduct.first_seen_name == product_name)
        )
    ).all()
    unique = {row.id: row for row in rows}
    if not unique:
        return None, f"no release_product is named {product_name!r}"
    if len(unique) > 1:
        return None, (
            f"{len(unique)} release_products are named {product_name!r} "
            f"({sorted(unique)}); a rendering must not be attached by guess"
        )
    return next(iter(unique.values())), None


def plan_renderings(
    db: Session, source_name: str = "snkrdunk", labels: list[str] | None = None
) -> RenderingReport:
    """Decide every declared rendering without writing anything."""
    declared: list[SourceRendering] = [
        r for r in UNCODED_SOURCE_RENDERINGS if r.source_name == source_name
    ]
    if labels:
        wanted = set(labels)
        unknown = sorted(wanted - {r.source_label for r in declared})
        if unknown:
            raise SourceRenderingError(
                f"Refusing: label(s) {unknown} are not declared in "
                "app.services.uncoded_source_renderings. A rendering must be declared "
                "with its observed card codes and evidence before it can be written."
            )
        declared = [r for r in declared if r.source_label in wanted]

    report = RenderingReport()
    for row in declared:
        plan = RenderingPlan(
            source_name=row.source_name,
            source_label=row.source_label,
            product_name=row.product_name,
            membership_relation=row.membership_relation,
            observed_card_codes=row.observed_card_codes,
        )
        product, refusal = _find_product(db, row.product_name)
        if product is None:
            plan.refusal = refusal
            report.plans.append(plan)
            continue
        plan.product_id = product.id
        plan.product_official_code = product.official_code
        exists = db.scalars(
            select(ReleaseProductAlias).where(
                ReleaseProductAlias.product_id == product.id,
                ReleaseProductAlias.alias_kind == SOURCE_RENDERING,
                ReleaseProductAlias.alias_name == row.source_label,
            )
        ).first()
        plan.action = "present" if exists is not None else "create"
        report.plans.append(plan)
    return report


def apply_renderings(
    db: Session,
    source_name: str = "snkrdunk",
    labels: list[str] | None = None,
    confirm: str | None = None,
    commit: bool = True,
) -> RenderingReport:
    """Plan, then insert the missing alias rows in one transaction."""
    if confirm != CONFIRM_PHRASE:
        raise SourceRenderingError(
            f'Refusing to apply without the confirmation phrase. Pass --confirm "{CONFIRM_PHRASE}".'
        )
    report = plan_renderings(db, source_name=source_name, labels=labels)
    if report.refused:
        raise SourceRenderingError(
            "Refusing: "
            + "; ".join(f"{p.source_label!r}: {p.refusal}" for p in report.refused)
            + ". Nothing was written."
        )
    try:
        for plan in report.to_create:
            db.add(
                ReleaseProductAlias(
                    product_id=plan.product_id,
                    alias_name=plan.source_label,
                    alias_kind=SOURCE_RENDERING,
                    source_url=None,
                )
            )
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    report.applied = True
    return report


def format_report(report: RenderingReport) -> str:
    lines = [
        "== declared source renderings: "
        + ("APPLIED" if report.applied else "PLAN (dry run - nothing written)")
        + " =="
    ]
    for plan in report.plans:
        lines.append("")
        lines.append(f"{plan.source_label!r}  [{plan.action}]")
        lines.append(f"  product        : {plan.product_name!r}")
        lines.append(
            f"  release_product: id={plan.product_id} official_code={plan.product_official_code}"
        )
        lines.append(
            f"  evidence       : {plan.membership_relation} membership, "
            f"{len(plan.observed_card_codes)} observed code(s)"
        )
        if plan.refusal:
            lines.append(f"  REFUSED: {plan.refusal}")
    lines.append("")
    lines.append(
        f"scoped={len(report.plans)} to_create={len(report.to_create)} "
        f"already_present={len(report.present)} refused={len(report.refused)} "
        f"writes={report.as_dict()['writes']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write declared storefront renderings for products that already exist. "
            "Plans by default. Only labels declared in "
            "app.services.uncoded_source_renderings can be written."
        )
    )
    parser.add_argument("--source", default="snkrdunk")
    parser.add_argument(
        "--labels",
        default=None,
        help="Comma-separated source labels to scope to. Default: every declared label.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default=None, help=f'Exactly: "{CONFIRM_PHRASE}"')
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    labels = [x for x in (args.labels or "").split(",") if x.strip()] or None

    db = SessionLocal()
    try:
        if args.apply:
            report = apply_renderings(
                db, source_name=args.source, labels=labels, confirm=args.confirm
            )
        else:
            report = plan_renderings(db, source_name=args.source, labels=labels)
    except SourceRenderingError as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        db.close()

    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
