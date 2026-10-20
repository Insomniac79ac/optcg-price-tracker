"""Raw refresh work for approved mappings that have none (ops-write runbook `plan-refresh-backfill`).

A collector prices only a mapping with a `refresh` row in freshness_work. Approval now plans it
(app.services.mapping_refresh.ensure_refresh_work, called by every approval path); this runbook
plans it once for mappings approved before that, starting with the 97 of F1 batch 1 (2026-10-19).

1. List every mapping in the shared operational-health population (active, current, approved,
   verified print, SNKRDUNK manually verified) with no refresh work, oldest mapping first, and
   pin the first ``count`` (default 500) by SHA-256 over the decision fields only.
2. Dry run (default): write nothing. The summary carries the list SHA-256, counts per source, a
   10-row reproducible sample and a storage estimate in MB/day (ESTIMATE: the measured planning
   rate per existing refresh row times the new rows).
3. Apply (``--apply --expected-sha256``) rebuilds the list in the write session and refuses unless
   its SHA-256 equals the dry run's, then plans each mapping through ensure_refresh_work (raw
   only, never PSA10; existing work untouched) in one transaction. A mapping it cannot plan is
   named in the summary and gets nothing. Requests to sources: none.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from ops import common

DEFAULT_COUNT = 500
MAX_COUNT = 1000
SAMPLE_SIZE = 10
LIST_KEYS = ("mapping_id", "source", "card_print_id", "listing_identity")
# The operational-health population (app.services.operational_health_sql.ELIGIBLE) with its
# listing identity and print. Read-only; no locks.
UNPLANNED_SQL = """
with e as ({eligible})
select e.mapping_id, e.source, m.card_print_id, m.canonical_source_listing_identity listing_identity,
  m.source_url, c.card_code, p.official_rarity rarity, p.official_asset_variant variant
from e join source_card_mappings m on m.id = e.mapping_id
join card_prints p on p.id = m.card_print_id join canonical_cards c on c.id = p.canonical_card_id
where e.work_id is null order by e.mapping_id
"""
PLANNED_SQL = "with e as ({eligible}) select count(*) from e where e.work_id is not null"


def check_count(count):
    count = DEFAULT_COUNT if count is None else count
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise common.Refused(f"count must be 1..{MAX_COUNT}")
    return count


def pinned_list(rows, count):
    """(bytes, sha256, doc) of the first ``count`` rows, in mapping order."""
    chosen = [{k: r[k] for k in LIST_KEYS} for r in rows[:count]]
    if not chosen:
        raise common.Refused("no approved mapping without refresh work")
    doc = {"runbook": "plan-refresh-backfill", "categories": "raw", "expected_count": len(chosen), "entries": chosen}
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    return data, hashlib.sha256(data).hexdigest(), doc


def sample(rows, sha, size=SAMPLE_SIZE):
    rng = random.Random(int(sha[:16], 16))
    picked = rng.sample(range(len(rows)), min(size, len(rows)))
    return [rows[i] for i in sorted(picked)]


def check_apply(apply, expected_sha256, sha):
    if not apply:
        return
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the list SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the rebuilt list differs from the dry run's (expected_sha256); dry run again")


def unplanned(session):
    """(rows without refresh work, planned row count). Read-only."""
    from app.services.operational_health_sql import ELIGIBLE
    from sqlalchemy import text

    rows = [dict(r._mapping) for r in session.execute(text(UNPLANNED_SQL.format(eligible=ELIGIBLE)))]
    planned = session.execute(text(PLANNED_SQL.format(eligible=ELIGIBLE))).scalar_one()
    return rows, planned


def storage_estimate(new_rows, planned_rows, rates):
    """MB/day the new rows would add at the measured planning rate per existing refresh row."""
    planning = rates["variants"]["ex_steps"]["planning_mb_day_s9"]
    per_row = planning / planned_rows if planned_rows else None
    added = round(per_row * new_rows, 2) if per_row is not None else None
    room = rates["room_to_reserve_mb_s9"]
    return {"label": "ESTIMATE", "planning_mb_day_s9_now": planning, "planned_refresh_rows_now": planned_rows,
            "mb_day_per_refresh_row": round(per_row, 4) if per_row is not None else None,
            "added_mb_day": added, "room_to_reserve_mb_s9": room,
            "days_to_reserve_now": round(room / planning, 1) if planning else None,
            "days_to_reserve_after": round(room / (planning + added), 1) if planning and added is not None else None}


def plan(session, entries):
    """Plan each listed mapping; (planned work rows, mappings that could not be planned)."""
    from app.models import SourceCardMapping
    from app.services.mapping_refresh import ensure_refresh_work

    planned, skipped = [], []
    for entry in entries:
        mapping = session.get(SourceCardMapping, entry["mapping_id"])
        work = ensure_refresh_work(session, mapping) if mapping is not None else None
        if work is None:
            skipped.append(entry["mapping_id"])
        else:
            planned.append({"mapping_id": entry["mapping_id"], "work_id": work.id})
    return planned, skipped


def run(out_dir, *, apply=False, count=None, expected_sha256=""):
    import yuyu_identity_capture_enqueue as tool
    from sqlalchemy.orm import Session

    from ops import db as ops_db
    from ops import storage_rates

    count = check_count(count)
    out = Path(out_dir)
    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        rows, planned_rows = unplanned(session)
    data, sha, doc = pinned_list(rows, count)
    (out / "backfill-list.json").write_bytes(data)
    chosen = rows[:len(doc["entries"])]
    common.write_json(out / "backfill-detail.json", chosen)
    check_apply(apply, expected_sha256, sha)

    events = storage_rates.load_events()
    rates = storage_rates.compute(storage_rates.fetch_series(events["window_start"]), events)
    summary = {"mode": "apply" if apply else "dry-run", "status": "DRY_RUN_OK", "approved_list_sha256": sha,
               "batch_size": len(chosen), "unplanned_total": len(rows),
               "by_source": dict(Counter(r["source"] for r in chosen)),
               "mapping_ids": [r["mapping_id"] for r in chosen],
               "sample": sample(chosen, sha),
               "storage": storage_estimate(len(chosen), planned_rows, rates),
               "categories": {"yuyutei": "raw/sell", "snkrdunk": "raw/floor"},
               "source_requests": 0, "written": 0}
    if not apply:
        return summary

    ops_db.resolve()[1].clear()
    with tool.staging_session(writable=True) as session:
        live, _ = unplanned(session)
        live_sha = pinned_list(live, count)[1] if live else ""
        check_apply(True, expected_sha256, live_sha)
        try:
            planned, skipped = plan(session, pinned_list(live, count)[2]["entries"])
            session.commit()
        except Exception:
            session.rollback()
            raise
    common.write_json(out / "backfill-receipt.json", {"planned": planned, "skipped_mapping_ids": skipped})
    summary.update(status="APPLIED" if not skipped else "APPLIED_WITH_SKIPS", written=len(planned),
                   planned_work_ids=[p["work_id"] for p in planned], skipped_mapping_ids=skipped)
    if skipped:
        summary["ok"] = False
    return summary
