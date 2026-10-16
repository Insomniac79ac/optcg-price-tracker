"""Staging state runbook: one live read feeds both generate_staging_state and check_raw_health.

Writes CURRENT_STATE.yaml and its staging-state-*.json evidence into the output directory
(never the committed docs/agent/CURRENT_STATE.yaml) and raw-health.json. Read-only: pinned
Railway/Vercel/GitHub reads and one fingerprinted read-only database transaction.
"""
from __future__ import annotations

from pathlib import Path

from ops import common


def run(out_dir):
    import check_raw_health
    import generate_staging_state as state

    # Mask the database password before the generator reads it again for its snapshot.
    from ops import db as ops_db
    ops_db.resolve()[1].clear()
    evidence = state.collect_live()
    output = Path(out_dir) / "CURRENT_STATE.yaml"
    if output.resolve() == state.CANONICAL_OUTPUT.resolve():
        raise common.Refused("ops runbooks never overwrite the committed CURRENT_STATE.yaml")
    snapshot = state.write_snapshot(evidence, output)
    health = check_raw_health.decision(evidence)
    common.write_json(Path(out_dir) / "raw-health.json", health)
    return {"verified_at": snapshot["verified_at"], "staging_head": evidence["repository"]["sha"],
            "blockers": [b["id"] for b in snapshot["blockers"]],
            "operational_health": {k: snapshot["operational_health"][k]["status"]
                                   for k in ("yuyu", "snkrdunk") if k in snapshot["operational_health"]},
            "raw_health_actions": len(health["mission_actions"]),
            "evidence_sha256": snapshot["evidence"]["sha256"]}
