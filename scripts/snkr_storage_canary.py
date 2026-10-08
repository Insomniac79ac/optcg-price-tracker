#!/usr/bin/env python3
"""Fresh bounded SNKR RAW dictionary canary; never dispatches source work.

Re-pinned from docs/agent/handoff/2026-10-08/capacity75-resumed/
snkr_storage_canary-dcaa478b305e.py (pinned to 4995007). Every original check is
kept. Changes: the verified collector upload is 1b1b64d while staging head may
be a later tooling/docs merge, so the helper additionally requires the
services/ and packages/ trees to be byte-identical between head and the upload;
and writer changes go only through collector_variables.change (skip-deploys +
redeploy of the verified upload), never a plain Railway variable change.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import collector_variables
import generate_staging_state as state

sys.path[:0] = [str(state.ROOT / "services/api"), str(state.ROOT / "packages/opcg_source_identity/src")]

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

COMPONENT = "1b1b64d23555b5abc315f1aaa79f547784136f59"
SID = "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a"
NAME = "snkrdunk-collector"
LEDGER_BEFORE = 16
FLAG_KEYS = ["RAW_DICTIONARY_STORAGE_ENABLED", "RAW_DICTIONARY_STORAGE_MODE", "APP_ENV", "SCRAPING_MODE",
             "LEGACY_PRICE_REFRESH_ENABLED", "MARKET_WORKFLOW_ENABLED", "DATA_RETENTION_ENABLED", "MOCK_MODE",
             "RAW_RETENTION_ENABLED", "PSA10_ENABLED", "SNKRDUNK_PSA10_ENABLED", "YUYUTEI_ENABLED",
             "SNKRDUNK_ENABLED", "YUYUTEI_DISCOVERY_ENABLED", "COLLECTORS_ENABLED"]


def flags(edge):
    n = edge["node"]
    v = state.command_json(["railway", "variable", "list", "-p", state.PROJECT, "-e", state.ENVIRONMENT,
                            "-s", n["serviceId"], "--json"])
    try:
        assert v["RAILWAY_PROJECT_ID"] == state.PROJECT and v["RAILWAY_ENVIRONMENT_ID"] == state.ENVIRONMENT
        return {"name": n["serviceName"], "service_id": n["serviceId"], "flags": {k: v.get(k) for k in FLAG_KEYS},
                "schedule": n.get("cronSchedule"), "start_command": n.get("startCommand"),
                "deployment_id": (n.get("latestDeployment") or {}).get("id")}
    finally:
        v.clear()


def connection():
    proxy = state.railway(f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") '
                          f'{{ domain proxyPort applicationPort }} }}')["tcpProxies"]
    assert len(proxy) == 1 and proxy[0]["applicationPort"] == 5432
    v = state.command_json(["railway", "variable", "list", "-p", state.PROJECT, "-e", state.ENVIRONMENT,
                            "-s", state.POSTGRES, "--json"])
    try:
        return psycopg.connect(host=proxy[0]["domain"], port=proxy[0]["proxyPort"], user=v["PGUSER"],
                               password=v["PGPASSWORD"], dbname=v["PGDATABASE"], connect_timeout=15,
                               options="-c default_transaction_read_only=on -c statement_timeout=30000")
    finally:
        v.clear()


def set_writer(enabled, out):
    receipt = collector_variables.change(NAME, {
        "RAW_DICTIONARY_STORAGE_ENABLED": "true" if enabled else "false",
        "RAW_DICTIONARY_STORAGE_MODE": "canary", "APP_ENV": "staging"}, COMPONENT)
    stamp = state.timestamp().replace(":", "").replace("-", "")[:15]
    state.atomic_write(out / f"snkr-writer-{'on' if enabled else 'off'}-{stamp}.json",
                       json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--activate", action="store_true")
    p.add_argument("--off", action="store_true")
    p.add_argument("--delivery", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    assert not (a.activate and a.off)
    a.out.mkdir(parents=True, exist_ok=True)
    activation = a.out / f"snkr-storage-canary-activation-{COMPONENT[:7]}.json"
    env = state.staging_environment()
    edges = [r for r in env["serviceInstances"]["edges"]
             if r["node"]["serviceName"].startswith("yuyutei-collector-shard-")
             or r["node"]["serviceName"] in {NAME, "optcg-price-tracker", "worker", "beat"}]
    before = [flags(r) for r in edges]
    target = next(r for r in before if r["service_id"] == SID)
    assert target["name"] == NAME and target["schedule"] == "27,57 * * * *" \
        and target["start_command"] == "python -m snkrdunk_collector.collect --due-work"
    if a.off:
        receipt = set_writer(False, a.out)
        print(json.dumps({"off": receipt["observed"], "deployment": receipt["deployment"]}))
        return
    assert len(before) == 13
    assert all(r["flags"]["RAW_DICTIONARY_STORAGE_ENABLED"] in (None, "false") for r in before)
    assert not activation.exists()
    assert a.delivery and a.delivery.exists()
    live = state.collect_live()
    head = live["repository"]["sha"]
    # New: the running upload's code must be byte-identical to staging head.
    assert subprocess.run(["git", "diff", "--quiet", COMPONENT, head, "--", "services", "packages"],
                          cwd=state.ROOT).returncode == 0
    delivery = json.loads(a.delivery.read_text())
    assert delivery["expected_commit"] == head and delivery["migration_revision"] == "f9e5b4a8c012" \
        and delivery["production_accessed"] is False
    assert delivery["sale_invariant"]["sale_index_inputs"] == delivery["sale_invariant"]["gap_receipts"] == 0
    import verify_yuyu_raw_reader_component as y
    import verify_snkr_published_discovery_component as s
    adoption = {"yuyu": y.verify(live, head, COMPONENT), "snkr": s.verify(live, head, COMPONENT, COMPONENT)}
    snapshot = state.write_snapshot(live, a.out / "CURRENT_STATE-canary-preflight.yaml")
    with connection() as db:
        assert all(c.ok for c in state.guard.evaluate(state.guard.collect_facts(db),
                                                      state.guard.expected_revisions_from_repo(str(state.ROOT))))
        db.row_factory = dict_row
        ledger = db.execute("select count(*) used,max(id) last_id from raw_snapshot_dictionaries").fetchone()
        assert ledger["used"] == LEDGER_BEFORE
        assert db.execute("select count(*) n from pg_indexes where schemaname=current_schema() and indexname in "
                          "('ix_raw_dictionary_created','ix_raw_snapshot_dictionary_scope')").fetchone()["n"] == 2
        from app.services.operational_health_sql import BUDGET_SQL
        budget = next(r for r in db.execute(BUDGET_SQL).fetchall() if r["name"] == "snkrdunk")
        assert not budget["reservation_mismatch"]
        raw_budget = db.execute("select b.* from source_dispatch_budgets b join sources s on s.id=b.source_id "
                                "where s.name='snkrdunk'").fetchone()
        assert raw_budget["enabled"] and raw_budget["pause_reason"] is None and raw_budget["paused_until"] is None
        assert raw_budget["request_limit"] == 3100 and raw_budget["window_seconds"] == 1800 \
            and raw_budget["used_requests"] + raw_budget["reserved_requests"] <= 3100
        assert db.execute("select count(*) n from freshness_attempts where claimed_by like 'snkrdunk-due:%' "
                          "and outcome is null").fetchone()["n"] == 0
        assert db.execute("select count(*) n from freshness_work w join freshness_price_states ps on "
                          "ps.work_id=w.id and ps.price_category='raw' where w.state in ('pending','claimed') and "
                          "(ps.last_successfully_checked_at is null or "
                          "ps.last_successfully_checked_at<now()-interval '24 hours')").fetchone()["n"] == 0
        assert db.execute("select count(*) n from freshness_price_states where price_category='psa10'").fetchone()["n"] == 0
        assert db.execute("select count(*) n from freshness_work where id in (3676,3677) and last_outcome='completed' "
                          "and next_due_at>now()+interval '365 days'").fetchone()["n"] == 2
        next_due = db.execute("select min(next_due_at) next_due from freshness_work w join sources s on "
                              "s.id=w.source_id where s.name='snkrdunk' and kind='refresh' and state='pending'").fetchone()
        db.rollback()
    metrics = state.command_json(["railway", "metrics", "-p", state.PROJECT, "-e", state.ENVIRONMENT, "-s",
                                  state.POSTGRES, "--since", "1d", "--volume", "--json"])
    assert metrics["environment"] == "staging" and metrics["service"] == "Postgres"
    volume = next(v for v in metrics["volumes"] if v["name"] == "postgres-volume")
    free = (volume["limit_mb"] - max(volume["current_mb"], volume["max_mb"])) * 1000000
    assert volume["limit_mb"] == 10000 and free > 3 * 1024**3 + (200 - ledger["used"]) * 8 * 1024**2
    receipt = {
        "target": "staging", "classification": "AMBER", "observed_at": state.timestamp(), "staging_head": head,
        "component_sha": COMPONENT, "schema": "f9e5b4a8c012", "before": before, "service_id": SID, "mode": "canary",
        "global_all_time_limit": 200, "global_already_charged": ledger["used"],
        "remaining_global_rows": 200 - ledger["used"],
        "worst_recovery_plaintext_bytes": (200 - ledger["used"]) * 8 * 1024**2, "reserve_bytes": 3 * 1024**3,
        "volume": volume, "free_bytes": free, "adoption": adoption, "next_regular_due": next_due,
        "source_jobs_triggered": 0, "source_requests_added": 0, "production_accessed": False,
        "mapping_writes": 0, "writer_changes": 1,
        "exact_variables": sorted(collector_variables.ALLOWED),
        "change_path": "collector_variables.change: --skip-deploys then deploymentRedeploy of verified upload",
        "source_requests": "Only existing ordinary scheduled due work; no intent creation, due advancement, "
                           "cron/budget/pacing change or replay.",
        "rollback": "Run this helper --off (same safe path). Disables only SNKR; keeps canary mode, staging APP_ENV, "
                    "readers, dependencies and protected old rows. Config containment, not RAW expansion.",
        "recovery": "Retain new encoded and base values before independent hash/length decode. Any expansion selects "
                    "only new writer-owned IDs under OFF expand_snapshot with rechecked space. 35175 never replayed.",
        "failure_triggers": ["hash or source/parser/fullURL/older-base/price lineage mismatch",
                             "source403/429/challenge or duplicate/uncontrolled requests",
                             "lease/reservation/singleton failure", "new actionable >24h backlog",
                             "RAW run runtime greater than previous293.052s plus10s; investigate",
                             "physical volume reserve threatened"],
        "observation": "Observe ONE positive scheduled RAW turn, then OFF promptly. Empty turns are not writer proof. "
                       "Global200 safeguard remains if monitoring delayed. Daily mode remains OFF.",
        "delivery_sha256": hashlib.sha256(a.delivery.read_bytes()).hexdigest(),
        "current_state": snapshot["evidence"]}
    stamp = state.timestamp().replace(":", "").replace("-", "")[:15]
    state.atomic_write(a.out / f"snkr-storage-canary-preflight-{stamp}.json",
                       json.dumps(receipt, default=state.json_default, indent=2) + "\n")
    if a.activate:
        receipt["writer_change"] = set_writer(True, a.out)
        receipt["activated_at"] = state.timestamp()
        state.atomic_write(activation, json.dumps(receipt, default=state.json_default, indent=2) + "\n")
    print(json.dumps({"activated": a.activate, "remaining_global_rows": 200 - ledger["used"],
                      "next_regular_due": next_due, "free_bytes": free}, default=state.json_default))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        print([(f.filename, f.lineno, f.name) for f in traceback.extract_tb(exc.__traceback__)])
        raise SystemExit("SNKR storage safeguard refused: " + type(exc).__name__) from None
