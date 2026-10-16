#!/usr/bin/env python3
"""Run one allowlisted staging runbook (GitHub Actions ops-readonly / ops-write only).

    python scripts/ops/run.py <runbook> --out ops-out [options]
    python scripts/ops/run.py <runbook> --preflight [options]   # inputs and quiet windows only

Every runbook is in RUNBOOKS with its kind (read or write) and whether it affects collectors.
Before it starts: the quiet windows (no collector-affecting runbook 02:00-06:00 UTC, no write
runbook 19:30-20:30 UTC), and for a write runbook no staging delivery in progress. After it
finishes: no known secret value in any output file. The summary is printed as JSON, written to
summary.json and the job summary, and emitted as `ops-summary` notice annotations, which an
agent can read over the REST API (docs/agent/OPS_RUNBOOKS.md). Exit 0 ok, 1 runbook reported a
problem, 2 refused.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import common  # noqa: E402

REPOSITORY = "Insomniac79ac/optcg-price-tracker"
# Workflows and CI jobs that deliver to staging (docs/agent/STAGING_DELIVERY.md).
# staging-delivery.yml is workflow_call only: it runs inside its caller's run and has no runs
# endpoint of its own (404, which would refuse every write); a caller's job belongs here instead.
DELIVERY_WORKFLOWS = {"ci.yml": {"staging-credential-presence", "staging-automerge"},
                      "staging-verify.yml": None}


def _staging_state(args, out):
    from ops import staging_state
    return staging_state.run(out)


def _lossless(args, out):
    from ops import lossless
    if args.ledger_floor is None:
        raise common.Refused("verify-lossless needs --ledger-floor (exclusive ledger id)")
    return lossless.run(out, args.ledger_floor)


def _storage(args, out):
    from ops import storage_rates
    names = [n for n in (args.transients or "").split(",") if n] or None
    return storage_rates.run(out, names)


def _fleet(args, out):
    from ops import fleet
    return fleet.run(out, args.receipt)


def _official(args, out):
    from ops import official_images
    return official_images.run(out)


def _diagnostic(args, out):
    from ops import diagnostic
    return diagnostic.run(out, args.diagnostic)


def _web_smoke(args, out):
    receipt = Path(out) / "web-smoke.json"
    status = subprocess.run([sys.executable, str(common.ROOT / "scripts/staging_web_smoke.py"), "--output", str(receipt)],
                            capture_output=True, text=True, timeout=900).returncode
    result = json.loads(receipt.read_text())
    return {"ok": result.get("ok") and status == 0, "problems": result.get("problems", [])[:20]}


def _enqueue(args, out):
    from ops import enqueue_remaining
    return enqueue_remaining.run(out, apply=args.apply, count=args.count, expected_sha256=args.expected_sha256)


# name: (kind, collector_affecting, handler). A write runbook runs only in ops-write.
RUNBOOKS = {
    "staging-state": ("read", False, _staging_state),
    "verify-lossless": ("read", False, _lossless),
    "storage-rates": ("read", False, _storage),
    "fleet-vs-receipt": ("read", False, _fleet),
    "official-images-status": ("read", False, _official),
    "db-diagnostic": ("read", False, _diagnostic),
    "web-smoke": ("read", False, _web_smoke),
    "enqueue-remaining-50": ("write", True, _enqueue),
}


def kind_of(name, apply):
    """(writes, collector_affecting) for this invocation. A write runbook's dry run writes nothing."""
    kind, collector, _ = RUNBOOKS[name]
    writes = kind == "write" and bool(apply)
    return writes, collector and writes


def gh_json(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise common.Refused("GitHub read failed: " + path.split("?")[0])
    return json.loads(out.stdout)


def deliveries_in_progress(read=gh_json, repo=REPOSITORY):
    """Names of staging delivery runs/jobs that are queued or running (fail closed on read errors)."""
    busy = []
    for workflow, jobs in DELIVERY_WORKFLOWS.items():
        for status in ("in_progress", "queued", "waiting"):
            runs = read(f"repos/{repo}/actions/workflows/{workflow}/runs?status={status}&per_page=20")["workflow_runs"]
            for run in runs:
                if jobs is None:
                    busy.append(f"{workflow} run {run['id']}")
                    continue
                for job in read(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]:
                    if job["name"] in jobs and job["status"] in ("in_progress", "queued", "waiting", "pending"):
                        busy.append(f"{workflow} {job['name']} run {run['id']}")
    return sorted(set(busy))


def preflight(args, now=None, read=gh_json):
    if args.runbook not in RUNBOOKS:
        raise common.Refused(f"unknown runbook {args.runbook!r}; allowed: {', '.join(RUNBOOKS)}")
    kind = RUNBOOKS[args.runbook][0]
    if kind == "write" and args.workflow != "ops-write":
        raise common.Refused("write runbooks run only in the owner-gated ops-write workflow")
    if kind == "read" and args.apply:
        raise common.Refused("--apply is only for write runbooks")
    writes, collector = kind_of(args.runbook, args.apply)
    reason = common.quiet_window_refusal(now or common.now_utc(), collector_affecting=collector, write=writes)
    if reason:
        raise common.Refused(reason)
    if kind == "write":
        busy = deliveries_in_progress(read)
        if busy:
            raise common.Refused("a staging delivery is in progress: " + "; ".join(busy))


def annotations(summary, title="ops-summary", chunk=3000, limit=9):
    """Workflow-command lines carrying the compact JSON summary (readable over REST)."""
    text = json.dumps(summary, separators=(",", ":"), default=common.json_default)
    escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    parts = [escaped[i:i + chunk] for i in range(0, len(escaped), chunk)] or [""]
    if len(parts) > limit:
        parts = parts[:limit - 1] + ["(truncated; see summary.json in the artifact)"]
    return [f"::notice title={title} {i + 1}/{len(parts)}::{p}" for i, p in enumerate(parts)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runbook")
    parser.add_argument("--out", type=Path, default=Path("ops-out"))
    parser.add_argument("--preflight", action="store_true", help="validate inputs and windows only")
    parser.add_argument("--workflow", choices=["ops-readonly", "ops-write"], default="ops-readonly")
    parser.add_argument("--ledger-floor", type=int)
    parser.add_argument("--diagnostic")
    parser.add_argument("--transients")
    parser.add_argument("--receipt")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args(argv)
    summary = {"runbook": args.runbook, "workflow": args.workflow, "apply": args.apply,
               "started_at": common.now_utc().isoformat()}
    code = 0
    try:
        preflight(args)
        if args.preflight:
            summary["status"] = "preflight-ok"
        else:
            args.out.mkdir(parents=True, exist_ok=True)
            result = RUNBOOKS[args.runbook][2](args, args.out)
            summary.update(status="ok", result=result)
            if isinstance(result, dict) and (result.get("ok") is False or result.get("all_match") is False
                                             or result.get("all_lossless") is False or result.get("healthy") is False
                                             or result.get("status") == "REFUSED"):
                summary["status"] = "problem"
                code = 1
    except common.Refused as error:
        summary.update(status="refused", reason=str(error))
        code = 2
    except Exception as error:  # noqa: BLE001 - provider/driver text may carry hosts or users
        # Where it failed (file:line), never the message: driver text can carry hosts and users.
        frames = [f"{Path(f.filename).name}:{f.lineno}" for f in traceback.extract_tb(error.__traceback__)][-6:]
        # VerificationError text is written to be safe (generate_staging_state); nothing else is.
        detail = f": {error}" if type(error).__name__ == "VerificationError" else ""
        summary.update(status="error", reason=f"{type(error).__name__}{detail} at {' < '.join(reversed(frames))}")
        code = 1
    summary["finished_at"] = common.now_utc().isoformat()
    if not args.preflight:
        common.write_json(args.out / "summary.json", summary)
        try:
            common.assert_clean(args.out)
        except common.Refused as error:
            summary = {"runbook": args.runbook, "status": "refused", "reason": str(error)}
            code = 2
    print(json.dumps(summary, indent=1, default=common.json_default))
    for line in annotations(summary):
        print(line)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {args.runbook}: {summary['status']}\n\n```json\n"
                     + json.dumps(summary, indent=1, default=common.json_default) + "\n```\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
