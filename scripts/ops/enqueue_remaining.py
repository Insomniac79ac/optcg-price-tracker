"""Remaining-50 Yuyu identity-capture enqueue (ops-write runbook), through the PR #116 tool.

1. Re-plan every candidate of the NEW100 plan against live digests (ops.replan, read-only).
2. Build the approved list: the first ``count`` eligible candidates, pinned by SHA-256.
3. Storage fit of that batch at the current rates, as information for the owner (NEW50's
   measured per-unit costs; owner rule: fit at planning AND stress).
4. Run scripts/yuyu_identity_capture_enqueue.py's checks on that list. Dry run (read-only
   session, rolled back) unless ``apply``; ``apply`` also requires ``expected_sha256`` to equal
   the list this run built, so only a list the owner saw in a dry run can be written.
The tool re-verifies every guard itself and writes all intents or none. It never approves,
reviews or maps, never fetches a source and never triggers a job.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from ops import common

# NEW50 measured costs (session 13 remaining50-fit.json): stored bytes per unit, and the
# volume (s9) MB per stored MB.
FIT_EVIDENCE = "docs/agent/handoff/2026-10-15/capacity75-session13/evidence/remaining50-fit.json"
RECURRING_MB_DAY = 0.45
HORIZON_DAYS = 90


def one_off_mb(doc, evidence):
    unit = evidence["unit_stored_bytes"]
    entries = doc["entries"]
    stored = (unit["product_html"] * len(entries) + unit["yuyu_image"] * len(entries)
              + unit["official_image"] * sum(len(e["considered_print_ids"]) for e in entries))
    return round(stored / 1_000_000 * evidence["physical_per_stored_ratio"], 1)


def storage_fit(doc, rates_result):
    from ops import storage_rates

    evidence = json.loads((common.ROOT / FIT_EVIDENCE).read_text())
    v = rates_result["variants"]
    rates = {"planning": v["ex_steps"]["planning_mb_day_s9"],
             "stress_A_as_observed": v["ex_steps"]["stress_worst_rolling_24h"]["mb_day_s9"],
             "stress_B_ex_transients": v["ex_steps_ex_transients"]["stress_worst_rolling_24h"]["mb_day_s9"]}
    one_off = one_off_mb(doc, evidence)
    fit = storage_rates.fit(rates, one_off, rates_result["room_to_reserve_mb_s9"], HORIZON_DAYS, RECURRING_MB_DAY)
    return {"one_off_mb_s9": one_off, "room_to_reserve_mb_s9": rates_result["room_to_reserve_mb_s9"],
            "horizon_days": HORIZON_DAYS, "recurring_mb_day_allowance": RECURRING_MB_DAY, "rates": fit,
            "fits_planning_and_stress_A": fit["planning"]["fits"] and fit["stress_A_as_observed"]["fits"],
            "fits_planning_and_stress_B": fit["planning"]["fits"] and fit["stress_B_ex_transients"]["fits"]}


def check_apply(apply, expected_sha256, sha):
    if not apply:
        return
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        raise common.Refused("apply needs expected_sha256: the approved-list SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the re-planned list differs from the dry run's (expected_sha256); dry run again")


def run(out_dir, *, apply=False, count=50, expected_sha256=""):
    from sqlalchemy.orm import Session
    from ops import db as ops_db, replan, storage_rates
    import yuyu_identity_capture_enqueue as tool

    out = Path(out_dir)
    plan = replan.load_plan()
    with Session(ops_db.engine()) as session:
        replanned = replan.replan(session, plan)
    common.write_json(out / "replan.json", replanned)
    data, sha, doc = replan.approved_list(replanned, count)
    list_path = out / "approved-list.json"
    list_path.write_bytes(data)
    check_apply(apply, expected_sha256, sha)

    events = storage_rates.load_events()
    rates_result = storage_rates.compute(storage_rates.fetch_series(events["window_start"]), events)
    fit = storage_fit(doc, rates_result)
    common.write_json(out / "storage-fit.json", fit)

    # Mask the database password in the log before the tool opens its own session.
    ops_db.resolve()[1].clear()
    receipt = {"tool": "yuyu_identity_capture_enqueue", "target": "staging", "mode": "apply" if apply else "dry-run",
               "source_requests": 0, "proposal_or_mapping_writes": 0, "list": {"sha256": sha, "entries": count}}
    try:
        approved, _ = tool.load_list(list_path, sha)
        with tool.staging_session(writable=apply) as session:
            report = tool.enqueue(session, approved, apply=apply)
            if apply:
                session.commit()
            else:
                session.rollback()
        receipt.update(report, status="APPLIED" if apply else "DRY_RUN_OK")
    except tool.Refused as error:
        receipt.update(status="REFUSED", reason=str(error), written=[])
    common.write_json(out / "enqueue-receipt.json", receipt)
    return {"mode": receipt["mode"], "status": receipt["status"], "reason": receipt.get("reason"),
            "approved_list_sha256": sha, "eligible": replanned["summary"]["eligible"],
            "guard_failures": replanned["summary"]["guard_failures"],
            "to_enqueue": len(receipt.get("to_enqueue", [])), "already_enqueued": len(receipt.get("already_enqueued", [])),
            "written": len(receipt.get("written", [])),
            "written_work_ids": [w["work_id"] for w in receipt.get("written", [])], "storage_fit": {
                "one_off_mb_s9": fit["one_off_mb_s9"], "fits_planning_and_stress_A": fit["fits_planning_and_stress_A"],
                "fits_planning_and_stress_B": fit["fits_planning_and_stress_B"]}}
