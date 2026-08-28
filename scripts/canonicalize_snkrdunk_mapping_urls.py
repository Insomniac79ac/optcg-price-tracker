#!/usr/bin/env python3
"""Repoint approved SNKRDUNK mappings at the page their print's language needs.

WHY THIS EXISTS. Discovery walks SNKRDUNK's English sitemap, so candidates
carry `/en/trading-cards/{id}`. Until 4F-9 approval copied that URL onto the
mapping verbatim, but the collector validates the fetched page's `<html lang>`
against the print's own language, so a jp-language print approved against the
English mirror can never be priced - it fails identity with
`language_mismatch` every run, forever, while looking perfectly approved.
Staging mappings 75 and 76 are exactly that.

4F-9 fixed approval going forward. This script fixes the rows already written.

WHAT IT CHANGES, AND WHAT IT REFUSES TO. Only `source_url`, and only when the
new value is derived from the listing id already in the old one. It never
invents a listing, never touches identity (`card_print_id`, `card_id`,
`source_card_id`), never changes review state, and never touches a candidate.
A mapping whose URL carries no recognisable listing id is REPORTED and left
alone, because guessing which listing it meant is the failure this whole
tranche exists to prevent.

Idempotent: a mapping already on the right path is a no-op. Dry-run by
default; `--apply` is required to write.
"""

from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "services", "api"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models import CardPrint, Source, SourceCardMapping  # noqa: E402
from app.services.exact_print_approval import ExactPrintApprovalError  # noqa: E402
from app.services.snkrdunk_urls import canonical_listing_url  # noqa: E402


def plan(db: Session) -> list[dict]:
    """What would change, without changing anything."""
    source = db.scalars(select(Source).where(Source.name == "snkrdunk")).one_or_none()
    if source is None:
        raise SystemExit("FAIL: no 'snkrdunk' row in sources.")

    rows = db.scalars(
        select(SourceCardMapping)
        .where(
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.card_print_id.is_not(None),
        )
        .order_by(SourceCardMapping.id)
    ).all()

    actions: list[dict] = []
    for mapping in rows:
        card_print = db.get(CardPrint, mapping.card_print_id)
        language = card_print.language if card_print is not None else None
        entry = {
            "mapping_id": mapping.id,
            "card_print_id": mapping.card_print_id,
            "print_language": language,
            "review_status": mapping.review_status,
            "is_active": mapping.is_active,
            "old_url": mapping.source_url,
            "new_url": None,
            "action": None,
            "detail": None,
        }
        try:
            canonical = canonical_listing_url(mapping.source_url, card_print_language=language)
        except ExactPrintApprovalError as exc:
            entry["action"] = "SKIP_UNRECOGNISED"
            entry["detail"] = exc.detail
        else:
            entry["new_url"] = canonical
            entry["action"] = "OK_ALREADY" if canonical == mapping.source_url else "REPOINT"
        actions.append(entry)
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run).")
    parser.add_argument("--mapping-ids", default=None,
                        help="Comma-separated mapping ids to restrict the change to.")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("FAIL: set DATABASE_URL or pass --database-url.")

    only = None
    if args.mapping_ids:
        only = {int(x) for x in args.mapping_ids.split(",") if x.strip()}

    engine = create_engine(args.database_url, future=True)
    with Session(engine) as db:
        actions = plan(db)
        changed = 0
        for entry in actions:
            if only is not None and entry["mapping_id"] not in only:
                continue
            print(
                f"  mapping {entry['mapping_id']:>4} print={entry['card_print_id']} "
                f"lang={entry['print_language']!r} {entry['review_status']}/"
                f"{'active' if entry['is_active'] else 'inactive'} "
                f"{entry['action']}"
            )
            print(f"      old: {entry['old_url']}")
            if entry["new_url"] and entry["action"] == "REPOINT":
                print(f"      new: {entry['new_url']}")
            if entry["detail"]:
                print(f"      why: {entry['detail']}")
            if entry["action"] != "REPOINT":
                continue
            changed += 1
            if args.apply:
                mapping = db.get(SourceCardMapping, entry["mapping_id"])
                mapping.source_url = entry["new_url"]
        if args.apply and changed:
            db.commit()
        print()
        print(f"{'APPLIED' if args.apply else 'DRY RUN'}: {changed} mapping(s) would be repointed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
