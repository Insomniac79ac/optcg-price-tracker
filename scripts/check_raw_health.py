#!/usr/bin/env python3
"""Machine-readable mission admission: 0 healthy, 1 fix-forward, 2 affected path blocked.

Read only. Never dispatch a collector, alter mappings or send notifications.
"""

import argparse
import json
from pathlib import Path
import generate_staging_state as state


def decision(evidence):
    clean = state.sanitize(evidence)
    snapshot = state.build_state(clean)
    health = snapshot["operational_health"]
    actions = []
    for source in ("yuyu", "snkrdunk"):
        result = health[source]
        if result["status"] != "HEALTHY":
            actions.append(
                {
                    "source": source,
                    "status": result["status"],
                    "action": result["action"],
                    "reasons": result["reasons"],
                    "requires_intermediate_approval": False,
                    "policy": "GREEN/AMBER fix-forward; RED and integrity stops remain binding",
                }
            )
    return {
        "schema_version": 1,
        "target": "staging",
        "observed_at": snapshot["verified_at"],
        "operational_health": health,
        "mission_actions": actions,
        "human_report": bool(actions),
        "production_accessed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = (
        state.collect_live() if args.live else json.loads(args.fixture.read_text())
    )
    if args.fixture:
        evidence["mode"] = "fixture"
    result = decision(evidence)
    result["collection_mode"] = evidence["mode"]
    state.atomic_write(args.output, json.dumps(result, indent=2) + "\n")
    statuses = [result["operational_health"][s]["status"] for s in ("yuyu", "snkrdunk")]
    # Healthy polling has no stdout chatter; consumers read the artifact.
    return 2 if "BLOCKED" in statuses else 1 if "DEGRADED" in statuses else 0


if __name__ == "__main__":
    raise SystemExit(main())
