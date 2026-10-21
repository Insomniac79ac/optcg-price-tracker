#!/usr/bin/env python3
"""Enqueue explicitly approved Yuyu identity-evidence capture intents (NEW100 batches).

Dry run by default. With --apply it writes one pending discovery intent per approved
candidate through the canonical writer (`freshness_queue.plan_discovery_scope`), the
same shape the collector's `identity_evidence.load_intent` accepts at claim time.

It never approves, reviews or maps anything: it does not write proposal groups,
alternatives or source mappings. It never fetches a source and never triggers a job;
the intents are claimed by ordinary scheduled Yuyu turns under the source budget.

Fail closed, all or nothing. Every entry of the approved list (pinned by SHA-256) is
re-resolved live with the canonical resolver and must still be:
- an ambiguous family whose live digest, release and complete sibling set (2..12)
  equal the approved values; prints exist, share the plan's canonical card and the
  plan's authoritative release_product_id (never a card-code prefix);
- a candidate whose listing identity matches its stored set/product;
- free of any active Yuyu mapping on its prints or listing, of any reviewed decision,
  and of any capture scope other than this exact intent;
- disjoint from every other entry's prints.
One failure refuses the whole batch with no write. Idempotent: an identical existing
intent is a no-op; any other existing scope for the candidate is a refusal. Not
imported by any collector (scripts/ is outside every collector image and watch path).

usage:
  yuyu_identity_capture_enqueue.py --list approved.json --sha256 <hex> [--apply] [--out receipt.json]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for extra in ("services/api", "packages/opcg_source_identity/src"):
    if str(ROOT / extra) not in sys.path:
        sys.path.insert(0, str(ROOT / extra))

MAX_SIBLINGS = 12  # services/yuyutei_collector/yuyutei_collector/identity_evidence.py
SCOPE_VERSION = 2
ESTIMATED_REQUEST_COST = 100  # as the 2026-10-06 intents
INTENT_KEYS = ("candidate_id", "evidence_digest", "release_product_id", "considered_print_ids")


class Refused(Exception):
    pass


def load_list(path: Path, expected_sha256: str):
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise Refused(f"approved list SHA-256 {actual} != pinned {expected_sha256}")
    data = json.loads(raw)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        raise Refused("approved list must hold 1..100 entries")
    if data.get("expected_count") != len(entries):
        raise Refused("approved list expected_count does not match its entries")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != set(INTENT_KEYS):
            raise Refused("each entry must hold exactly candidate_id, evidence_digest, release_product_id, considered_print_ids")
        if type(entry["candidate_id"]) is not int or type(entry["release_product_id"]) is not int:
            raise Refused("integer candidate and release required")
        ids = entry["considered_print_ids"]
        if not isinstance(ids, list) or any(type(i) is not int for i in ids) or ids != sorted(set(ids)):
            raise Refused("sorted unique integer print ids required")
    if len({e["candidate_id"] for e in entries}) != len(entries):
        raise Refused("duplicate candidate in approved list")
    return data, actual


def intent_cursor(entry):
    return {
        "version": SCOPE_VERSION,
        "candidate_id": entry["candidate_id"],
        "explicit_identity_capture": True,
        "evidence_digest": entry["evidence_digest"],
        "release_product_id": entry["release_product_id"],
        "considered_print_ids": list(entry["considered_print_ids"]),
    }


def check_entry(session, entry, source_id):
    """Return (scope_key, existing_identical) or raise Refused with the reason."""
    from sqlalchemy import select, text
    from opcg_source_identity import yuyutei_listing_identity
    from app.models import CardPrint, YuyuteiCandidate
    from app.services.identity_evidence_scope import identity_evidence_scope
    from app.services.source_mapping_proposals import resolve_current_candidate_proposal

    cid = entry["candidate_id"]
    candidate = session.get(YuyuteiCandidate, cid)
    if candidate is None or yuyutei_listing_identity(candidate.source_url) != (candidate.set_slug, candidate.product_id):
        raise Refused(f"{cid}: candidate listing identity does not match its stored set/product")
    plan = resolve_current_candidate_proposal(session, source_name="yuyutei", candidate_id=cid)
    if plan is None or plan.resolution_status != "ambiguous":
        raise Refused(f"{cid}: live plan is not an ambiguous family")
    ids = sorted(a.card_print_id for a in plan.alternatives)
    if plan.evidence_digest != entry["evidence_digest"]:
        raise Refused(f"{cid}: live evidence digest changed (re-plan required)")
    if plan.release_product_id is None or plan.release_product_id != entry["release_product_id"]:
        raise Refused(f"{cid}: live release_product_id differs from the approved one")
    if plan.source_id != source_id:
        raise Refused(f"{cid}: plan is not a Yuyu-Tei plan")
    if ids != entry["considered_print_ids"] or not 2 <= len(ids) <= MAX_SIBLINGS:
        raise Refused(f"{cid}: live sibling set differs or is not 2..{MAX_SIBLINGS}")
    prints = session.scalars(select(CardPrint).where(CardPrint.id.in_(ids))).all()
    if len(prints) != len(ids):
        raise Refused(f"{cid}: an official sibling print is missing")
    if any(p.release_product_id != plan.release_product_id for p in prints):
        raise Refused(f"{cid}: a sibling's authoritative release differs from the plan")
    if any(p.canonical_card_id != plan.canonical_card_id for p in prints):
        raise Refused(f"{cid}: siblings do not share the plan's canonical card")
    active = session.execute(
        text(
            """select count(*) from source_card_mappings where source_id = :sid and is_active
               and superseded_at is null and (card_print_id = any(:ids) or source_url = :url)"""
        ),
        {"sid": source_id, "ids": ids, "url": plan.source_url},
    ).scalar()
    if active:
        raise Refused(f"{cid}: an active Yuyu mapping exists for a sibling or this listing")
    reviewed = session.execute(
        text(
            """select count(*) from source_mapping_proposal_groups where source_id = :sid
               and source_candidate_id = :cid and reviewed_at is not null"""
        ),
        {"sid": source_id, "cid": cid},
    ).scalar()
    if reviewed:
        raise Refused(f"{cid}: a reviewed proposal decision exists")
    scope = identity_evidence_scope(cid, entry["evidence_digest"], SCOPE_VERSION)
    existing = session.execute(
        text(
            """select scope_key, kind, state, attempt_count, resume_cursor from freshness_work
               where source_id = :sid and (scope_key = :legacy or scope_key like :pattern)"""
        ),
        {"sid": source_id, "legacy": f"yuyu-identity:{cid}", "pattern": f"yuyu-identity:{cid}:%"},
    ).mappings().all()
    if not existing:
        return scope, False
    if (
        len(existing) == 1
        and existing[0]["scope_key"] == scope
        and existing[0]["kind"] == "discovery"
        and {k: (existing[0]["resume_cursor"] or {}).get(k) for k in intent_cursor(entry)} == intent_cursor(entry)
    ):
        return scope, True  # this exact intent is already queued (or done): never touched again
    raise Refused(f"{cid}: another capture scope already exists for this candidate")


def enqueue(session, approved, *, apply, now=None):
    """Check every entry, then (apply only) write all intents. Caller owns the transaction."""
    from sqlalchemy import select
    from app.models import FreshnessWork, Source
    from app.services.freshness_queue import plan_discovery_scope

    now = now or datetime.now(timezone.utc)
    source = session.scalars(select(Source).where(Source.name == "yuyutei")).one_or_none()
    if source is None:
        raise Refused("yuyutei source missing")
    entries = approved["entries"]
    shared = Counter(i for e in entries for i in e["considered_print_ids"])
    if any(n > 1 for n in shared.values()):
        raise Refused("a print is shared between approved candidates")
    checked = [(entry, *check_entry(session, entry, source.id)) for entry in entries]
    report = {"apply": apply, "checked": len(checked), "already_enqueued": [], "to_enqueue": [], "written": []}
    for entry, scope, identical in checked:
        (report["already_enqueued"] if identical else report["to_enqueue"]).append(scope)
    if not apply:
        return report
    for entry, scope, identical in checked:
        if identical:
            continue
        work = plan_discovery_scope(
            session, source.id, scope, due_at=now, estimated_request_cost=ESTIMATED_REQUEST_COST
        )
        if work.state != "pending" or work.attempt_count != 0 or work.resume_cursor:
            raise Refused(f"{scope}: writer returned an existing or progressed work row")
        work.resume_cursor = intent_cursor(entry)
        session.flush()
        report["written"].append({"work_id": work.id, "scope_key": scope})
    stored = session.scalars(
        select(FreshnessWork).where(FreshnessWork.id.in_([w["work_id"] for w in report["written"]]))
    ).all()
    if len(stored) != len(report["written"]) or any(
        w.kind != "discovery" or w.state != "pending" or w.attempt_count != 0
        or w.resume_cursor.get("explicit_identity_capture") is not True
        for w in stored
    ):
        raise Refused("post-write verification failed")
    return report


def staging_session(*, writable):
    """Pinned staging Postgres through the Railway TCP proxy; read only unless --apply."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_staging_state as state
    import psycopg
    import sqlalchemy
    from sqlalchemy.orm import Session

    state.staging_environment()  # refuses anything but the pinned staging identity
    proxy = state.railway(
        f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") '
        "{ domain proxyPort applicationPort } }"
    )["tcpProxies"]
    if len(proxy) != 1 or proxy[0]["applicationPort"] != 5432:
        raise Refused("staging Postgres proxy not uniquely identified")
    variables = state.service_variables(state.POSTGRES)
    options = "-c statement_timeout=60000 -c lock_timeout=10000"
    if not writable:
        options += " -c default_transaction_read_only=on"
    creds = dict(
        host=proxy[0]["domain"], port=proxy[0]["proxyPort"], user=variables["PGUSER"],
        password=variables["PGPASSWORD"], dbname=variables["PGDATABASE"], connect_timeout=15, options=options,
    )
    variables.clear()
    engine = sqlalchemy.create_engine(
        "postgresql+psycopg://", creator=lambda: psycopg.connect(**creds), poolclass=sqlalchemy.pool.NullPool
    )
    return Session(engine, autoflush=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--apply", action="store_true", help="write the intents (default: dry run)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    receipt = {"tool": "yuyu_identity_capture_enqueue", "target": "staging", "mode": "apply" if args.apply else "dry-run",
               "source_requests": 0, "proposal_or_mapping_writes": 0}
    try:
        approved, digest = load_list(args.list, args.sha256)
        receipt["list"] = {"path": str(args.list), "sha256": digest, "batch": approved.get("batch"), "entries": len(approved["entries"])}
        with staging_session(writable=args.apply) as session:
            from sqlalchemy import text

            receipt["started_at"] = session.execute(text("select now()")).scalar().isoformat()
            report = enqueue(session, approved, apply=args.apply)
            if args.apply:
                session.commit()
            else:
                session.rollback()
            receipt.update(report, status="APPLIED" if args.apply else "DRY_RUN_OK")
    except Refused as error:
        receipt.update(status="REFUSED", reason=str(error), written=[])
    text_out = json.dumps(receipt, indent=1, default=str)
    if args.out:
        args.out.write_text(text_out + "\n")
    print(text_out)
    return 0 if receipt["status"] != "REFUSED" else 2


if __name__ == "__main__":
    sys.exit(main())
