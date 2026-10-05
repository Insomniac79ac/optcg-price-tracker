#!/usr/bin/env python3
"""Generate a staging observation, never authorization or desired infrastructure state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal

import staging_db_read_check as guard

# Pure shared classifier/query definitions; no application settings/provider imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from app.services import operational_health as health
from app.services.operational_health_sql import DUE_SQL, EVENT_SQL

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Insomniac79ac/optcg-price-tracker"
PROJECT = "c613898d-bf03-43a6-8813-761f72e1c00a"
ENVIRONMENT = "05d1eac2-510d-4bd3-999e-fea9ead766b7"
POSTGRES = "08c557d4-9d74-43fa-a0ac-5a909e731f4e"
VERCEL = "prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr"
CANONICAL_OUTPUT = ROOT / "docs/agent/CURRENT_STATE.yaml"
SQL_PATH = ROOT / "docs/agent/evidence/staging-state-read.sql"
UNKNOWN = "unknown"


class VerificationError(Exception):
    """Safe diagnostic text only; never attach command output or a DSN."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def command_json(args):
    if args[0] == "vercel" and os.environ.get("STAGING_VERCEL_READ_TOKEN"):
        args = [*args, "--token", os.environ["STAGING_VERCEL_READ_TOKEN"]]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise VerificationError(f"{args[0]} read failed; no snapshot replaced")
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        raise VerificationError(
            f"{args[0]} read unavailable; no snapshot replaced"
        ) from None


def railway(query):
    response = command_json(["railway", "api", query])
    if response.get("errors") or not response.get("data"):
        raise VerificationError("Railway query failed")
    return response["data"]


def load_queries():
    queries = dict(
        re.findall(r"^-- (\w+)\n(.*?);\s*$", SQL_PATH.read_text(), re.M | re.S)
    )
    # Fixed, reviewed SQL only. Read-only PostgreSQL transactions remain the enforcement.
    if not queries or any(
        not q.lstrip().lower().startswith(("select ", "with "))
        for q in queries.values()
    ):
        raise VerificationError("Invalid aggregate query file")
    return queries


def database_snapshot():
    import psycopg
    from psycopg.rows import dict_row

    proxies = railway(
        f'query {{ tcpProxies(environmentId:"{ENVIRONMENT}", serviceId:"{POSTGRES}") {{ domain proxyPort applicationPort }} }}'
    )["tcpProxies"]
    if len(proxies) != 1 or proxies[0]["applicationPort"] != 5432:
        raise VerificationError("Staging database endpoint is ambiguous")
    # Fetch freshly scoped credentials into memory; never log or save this response.
    variables = command_json(
        [
            "railway",
            "variable",
            "list",
            "-p",
            PROJECT,
            "-e",
            ENVIRONMENT,
            "-s",
            POSTGRES,
            "--json",
        ]
    )
    try:
        with psycopg.connect(
            host=proxies[0]["domain"],
            port=proxies[0]["proxyPort"],
            user=variables["PGUSER"],
            password=variables["PGPASSWORD"],
            dbname=variables["PGDATABASE"],
            connect_timeout=15,
            options="-c default_transaction_read_only=on -c statement_timeout=30000 -c search_path=public",
        ) as connection:
            connection.read_only = True
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            # Fingerprints and all aggregates share a single consistent read-only transaction.
            facts = guard.collect_facts(connection)
            checks = guard.evaluate(
                facts, guard.expected_revisions_from_repo(str(ROOT))
            )
            if not all(check.ok for check in checks):
                raise VerificationError(
                    "Staging database fingerprint failed: "
                    + ", ".join(c.name for c in checks if not c.ok)
                )
            connection.row_factory = dict_row
            result = {
                name: connection.execute(sql).fetchall()
                for name, sql in load_queries().items()
            }
            result["operational_due"] = connection.execute(DUE_SQL).fetchall()
            result["operational_runs"] = [
                row["context_json"] for row in connection.execute(EVENT_SQL).fetchall()
            ]
            connection.rollback()
            result["fingerprint"] = [{"name": c.name, "ok": c.ok} for c in checks]
            return result
    except VerificationError:
        raise
    except Exception:
        # Driver diagnostics can contain host, username and other connection details.
        raise VerificationError(
            "Staging database read failed; no snapshot replaced"
        ) from None
    finally:
        variables.clear()


def collect_live():
    data = railway(
        f"""query {{ project(id:"{PROJECT}") {{ id }} environment(id:"{ENVIRONMENT}") {{ id name projectId serviceInstances {{ edges {{ node {{ serviceName serviceId startCommand cronSchedule latestDeployment {{ id status meta }} }} }} }} }} }}"""
    )
    environment = data["environment"]
    if (
        data["project"]["id"],
        environment["id"],
        environment["name"],
        environment["projectId"],
    ) != (PROJECT, ENVIRONMENT, "staging", PROJECT):
        raise VerificationError(
            "Refused: target does not match pinned staging identity"
        )
    services = []
    for edge in environment["serviceInstances"]["edges"]:
        service = edge["node"]
        name = service["serviceName"]
        if name not in {
            "optcg-price-tracker",
            "snkrdunk-collector",
            "market-index-snapshot",
        } and not name.startswith("yuyutei-collector-shard-"):
            continue
        deployment = service.get("latestDeployment") or {}
        meta = deployment.get("meta") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        reported = re.search(
            r"exact commit ([0-9a-f]{40})", (meta.get("cliMessage") or "")
        )
        # No arbitrary commands, CLI messages, env vars, URLs or personal metadata in evidence.
        services.append(
            {
                "name": name,
                "service_id": service["serviceId"],
                "due_work_configured": "--due-work"
                in (service.get("startCommand") or ""),
                "schedule_utc": service.get("cronSchedule"),
                "deployment_id": deployment.get("id", UNKNOWN),
                "status": deployment.get("status", UNKNOWN),
                "git_sha": (meta.get("commitHash") or UNKNOWN),
                "reported_sha": reported.group(1) if reported else UNKNOWN,
            }
        )
    branch = command_json(["gh", "api", f"repos/{REPOSITORY}/branches/staging"])
    if branch.get("name") != "staging" or not re.fullmatch(
        r"[0-9a-f]{40}", branch["commit"]["sha"]
    ):
        raise VerificationError("Refused: Git branch identity did not match staging")
    evidence = {
        "environment": "staging",
        "mode": "live",
        "collected_at": timestamp(),
        "repository": {
            "name": REPOSITORY,
            "branch": "staging",
            "sha": branch["commit"]["sha"],
        },
        "railway": {
            "project_id": PROJECT,
            "environment_id": ENVIRONMENT,
            "services": sorted(services, key=lambda s: s["name"]),
        },
        "errors": [],
    }
    evidence["database"] = database_snapshot()
    try:
        project = command_json(["vercel", "api", f"/v9/projects/{VERCEL}", "--raw"])
    except VerificationError:
        evidence["frontend"] = UNKNOWN
        evidence["errors"].append("frontend_metadata_unavailable")
    else:
        if (
            project.get("id") != VERCEL
            or project.get("name") != "optcg-price-tracker-staging"
        ):
            raise VerificationError("Refused: frontend project is not staging")
        active = project.get("targets", {}).get("production") or {}
        meta = active.get("meta") or {}
        evidence["frontend"] = {
            "project_id": VERCEL,
            "deployment_id": active.get("id", UNKNOWN),
            "status": active.get("readyState", UNKNOWN),
            "sha": meta.get("githubCommitSha") or meta.get("gitCommitSha") or UNKNOWN,
        }
    return evidence


def sanitize(evidence):
    """Allowlist the persisted evidence; old/untrusted fixture extras cannot leak secrets."""
    if evidence.get("environment") != "staging":
        raise VerificationError("Refused: evidence is not staging")
    db = evidence["database"]
    if not db.get("fingerprint") or not all(
        c.get("ok") is True for c in db["fingerprint"]
    ):
        raise VerificationError("Refused: database fingerprint not verified")
    if db["as_of"][0].get("read_only") != "on":
        raise VerificationError("Refused: database observation was not read-only")
    allowed = {
        "as_of": ["at", "read_only"],
        "revision": ["version_num"],
        "coverage": [
            "canonical_variants",
            "one_or_more_sources",
            "one_or_more_sources_pct",
            "both_sources",
            "zero_sources",
        ],
        "eligible": ["name", "count"],
        "budgets": [
            "name",
            "enabled",
            "request_limit",
            "window_seconds",
            "used_requests",
            "reserved_requests",
            "paused_until",
        ],
        "work": ["name", "kind", "state", "policy_version", "count"],
        "freshness": [
            "name",
            "total",
            "never_successfully_checked",
            "check_older_than_24h",
            "price_older_than_24h",
            "no_listing",
        ],
        "attempts_24h": ["name", "kind", "outcome", "attempts", "latest"],
        "market_value": ["scope_kind", "latest_published_date", "intentional_gap_rows"],
        "receipts": [
            "snapshot_date",
            "receipt_kind",
            "expected_print_count",
            "snapshot_row_count",
        ],
        "categories": ["price_category", "price_type", "count"],
        "psa10": ["count", "latest"],
    }
    clean_db = {
        key: [{field: row.get(field) for field in fields} for row in db.get(key, [])]
        for key, fields in allowed.items()
    }
    due_fields = (
        "source",
        "shard",
        "eligible",
        "due",
        "overdue",
        "claimed",
        "backoff",
        "quarantined",
        "never_checked",
        "within_23h",
        "between_23_24h",
        "over_24h",
        "expired_claims",
        "retries",
        "unplanned",
        "oldest_actionable_due_at",
        "successful_check_age_p50",
        "successful_check_age_p95",
        "successful_check_age_max",
        "maximum_successful_revisit_gap_seconds",
    )
    clean_db["operational_due"] = [
        {k: row.get(k) for k in due_fields} for row in db.get("operational_due", [])
    ]
    clean_db["operational_runs"] = [
        health.sanitize(row) for row in db.get("operational_runs", [])
    ]
    clean_db["fingerprint"] = [
        {"name": c["name"], "ok": c["ok"]} for c in db["fingerprint"]
    ]
    clean_db["duplicate_active_exact_print_source_groups"] = db.get(
        "duplicate_active_exact_print_source_groups",
        sum(row["card_print_id"] is not None for row in db.get("duplicate_detail", [])),
    )
    clean_db["quarantined_identity"] = db.get(
        "quarantined_identity",
        sum(
            row["count"]
            for row in db.get("blocked_reasons", [])
            if row["name"] == "snkrdunk"
            and "identity" in (row.get("last_failure") or "").lower()
        ),
    )
    repo = evidence["repository"]
    front = evidence.get("frontend", UNKNOWN)
    rail = evidence["railway"]
    result = {
        "environment": "staging",
        "mode": evidence["mode"],
        "collected_at": evidence["collected_at"],
        "repository": {k: repo[k] for k in ["name", "branch", "sha"]},
        "railway": {
            "project_id": rail["project_id"],
            "environment_id": rail["environment_id"],
            "services": [
                {
                    k: s.get(k, UNKNOWN)
                    for k in [
                        "name",
                        "service_id",
                        "due_work_configured",
                        "schedule_utc",
                        "deployment_id",
                        "status",
                        "git_sha",
                        "reported_sha",
                    ]
                }
                for s in rail["services"]
            ],
        },
        "frontend": (
            {
                k: front.get(k, UNKNOWN)
                for k in ["project_id", "deployment_id", "status", "sha"]
            }
            if isinstance(front, dict)
            else UNKNOWN
        ),
        "database": clean_db,
        "errors": [
            e
            for e in evidence.get("errors", [])
            if e == "frontend_metadata_unavailable"
        ],
    }
    return json.loads(json.dumps(result, default=json_default))


def build_state(evidence):
    db = evidence["database"]
    coverage = dict(db["coverage"][0])
    total, covered, both, zero = (
        int(coverage[k])
        for k in [
            "canonical_variants",
            "one_or_more_sources",
            "both_sources",
            "zero_sources",
        ]
    )
    if min(total, covered, both, zero) < 0 or covered + zero != total or both > covered:
        raise VerificationError("Coverage arithmetic failed; no snapshot replaced")
    coverage["one_or_more_sources_pct"] = (
        round(100 * covered / total, 4) if total else UNKNOWN
    )
    coverage["meaning"] = (
        "eligible exact-print mappings, including quarantined work; not operational health"
    )
    coverage["duplicate_active_exact_print_source_groups"] = db[
        "duplicate_active_exact_print_source_groups"
    ]
    eligible = {r["name"]: r["count"] for r in db["eligible"]}
    if eligible.get("yuyutei", 0) + eligible.get("snkrdunk", 0) - both != covered:
        raise VerificationError("Eligible mappings disagree with coverage")
    services = evidence["railway"]["services"]
    by_name = {s["name"]: s for s in services}
    shards = [
        s
        for s in services
        if s["name"].startswith("yuyutei-collector-shard-")
        and s["due_work_configured"] is True
    ]
    snkr = by_name.get("snkrdunk-collector", {})
    front = evidence["frontend"] if isinstance(evidence["frontend"], dict) else {}
    freshness = {
        r["name"]: {k: v for k, v in r.items() if k != "name"} for r in db["freshness"]
    }
    deficit = any(
        r["never_successfully_checked"] or r["check_older_than_24h"]
        for r in freshness.values()
    )
    compliance = (
        "not_met" if deficit else UNKNOWN
    )  # One instant never proves sustained deadline compliance.

    def attempts(source, kind):
        rows = [
            r for r in db["attempts_24h"] if r["name"] == source and r["kind"] == kind
        ]
        return {"attempts_24h": sum(r["attempts"] for r in rows), "outcomes": rows}

    def work(source, kind):
        counts = {}
        for row in db["work"]:
            if row["name"] == source and row["kind"] == kind:
                counts[row["state"]] = counts.get(row["state"], 0) + row["count"]
        return counts

    overall = next((r for r in db["market_value"] if r["scope_kind"] == "overall"), {})
    blockers = []
    if deficit:
        blockers.append(
            {"id": "freshness-deadline-deficit", "scope": "operational freshness claim"}
        )
    if db["quarantined_identity"]:
        blockers.append(
            {"id": "snkrdunk-identity-quarantine", "count": db["quarantined_identity"]}
        )
    if db["duplicate_active_exact_print_source_groups"]:
        blockers.append(
            {"id": "duplicate-active-exact-mapping", "scope": "identity integrity"}
        )
    if any(r["intentional_gap_rows"] for r in db["market_value"]):
        blockers.append(
            {
                "id": "intentional-history-gap-populated",
                "scope": "published history integrity",
            }
        )
    repo_sha = evidence["repository"]["sha"]
    if front.get("sha", UNKNOWN) not in (UNKNOWN, repo_sha) or any(
        s[key] not in (UNKNOWN, repo_sha)
        for s in services
        for key in ("reported_sha", "git_sha")
    ):
        blockers.append(
            {
                "id": "deployment-provenance-divergence",
                "scope": "verify intended source before redeploying",
            }
        )
    blockers.extend(
        {"id": err, "scope": "snapshot completeness"} for err in evidence["errors"]
    )
    return {
        "schema_version": 2,
        "verified_at": db["as_of"][0]["at"],
        "target": "staging",
        "collection_mode": evidence["mode"],
        "snapshot_semantics": "observation only; not authorization, desired state or a capacity guarantee",
        "repository": evidence["repository"],
        "staging": {
            "frontend_url": "https://optcg-price-tracker-staging.vercel.app",
            "api_url": "https://optcg-price-tracker-staging.up.railway.app",
            "database_revision": db["revision"][0]["version_num"],
            "frontend": front or UNKNOWN,
            "services": services,
            "collector_runtime_sha": UNKNOWN,
        },
        "operational_health": health.aggregate(
            db.get("operational_due", []),
            db.get("operational_runs", []),
            db["budgets"],
            db["as_of"][0]["at"],
        ),
        "coverage": coverage,
        "yuyu": {
            "eligible_mappings": eligible.get("yuyutei", 0),
            "shards": len(shards),
            "schedules_utc": {s["name"]: s["schedule_utc"] for s in shards},
            "admission_versions": UNKNOWN,
            "promotion_semantics": {
                "required_policy": "sale provenance is internal only; never public/history/index/Market Value; never substitute struck prices",
                "live_end_to_end_revalidation": UNKNOWN,
            },
            "due_work": work("yuyutei", "refresh") | attempts("yuyutei", "refresh"),
            "discovery": work("yuyutei", "discovery")
            | attempts("yuyutei", "discovery")
            | {"continuous_consumer_health": UNKNOWN},
        },
        "snkrdunk": {
            "eligible_mappings": eligible.get("snkrdunk", 0),
            "batch_max": UNKNOWN,
            "schedule": snkr.get("schedule_utc", UNKNOWN),
            "schedule_timezone": "UTC",
            "quarantined_identity": db["quarantined_identity"],
            "due_work": work("snkrdunk", "refresh") | attempts("snkrdunk", "refresh"),
        },
        "freshness": {
            "standard_target_hours": 24,
            "dispatch_due_hours": 23,
            "deadline_compliance_status": compliance,
            "by_source": freshness,
            "sustained_natural_cycle_compliance": UNKNOWN,
        },
        "source_budgets": {
            r["name"]: {k: v for k, v in r.items() if k != "name"}
            for r in db["budgets"]
        },
        "market_value": {
            "latest_published_date": overall.get("latest_published_date") or UNKNOWN,
            "historical_gaps": ["2026-09-27", "2026-09-28"],
            "historical_gap_rows": sum(
                r["intentional_gap_rows"] for r in db["market_value"]
            ),
            "latest_atomic_receipt": db["receipts"][0] if db["receipts"] else UNKNOWN,
            "receipt_gate": "required; observation is not a receipt-content audit",
        },
        "features": {
            "raw_due_work": {
                "configured_sources": sorted(
                    {s["name"] for s in services if s["due_work_configured"] is True}
                ),
                "full_freshness_compliance": compliance,
            },
            "discovery": {
                "yuyu": work("yuyutei", "discovery"),
                "snkrdunk": work("snkrdunk", "discovery") or UNKNOWN,
                "continuous_consumer_health": UNKNOWN,
            },
            "psa10": {
                "live_observations": db["psa10"][0]["count"],
                "freshness_categories": sorted(
                    {r["price_category"] for r in db["categories"]}
                ),
                "live_activation": UNKNOWN,
                "public_exposure": UNKNOWN,
            },
        },
        "blockers": blockers,
        "hard_invariants": {
            "production_change_authorized": False,
            "ambiguous_auto_approval": False,
            "yuyu_sale_public": False,
            "yuyu_sale_index_eligible": False,
            "yuyu_sale_market_value_input": False,
        },
        "hard_invariants_meaning": "binding policy, not a live audit verdict",
        "unknown_reasons": {
            "admission_versions": "no version-bearing runtime receipt collected",
            "batch_max": "no effective runtime limit receipt collected",
            "collector_runtime_sha": "platform Git metadata and CLI-reported provenance do not independently verify runtime bytes",
            "feature_health": "queue/configuration and recent attempts do not prove sustained health or public activation",
        },
    }


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".agent-state-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_snapshot(evidence, output):
    import yaml

    clean = sanitize(evidence)
    state = build_state(clean)
    if clean["mode"] != "live" and output.resolve() == CANONICAL_OUTPUT.resolve():
        raise VerificationError("Fixture replay cannot replace CURRENT_STATE.yaml")
    content = json.dumps(clean, indent=2, sort_keys=True) + "\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    artifact = output.parent / "evidence" / f"staging-state-{digest[:16]}.json"
    state["evidence"] = {
        "artifact": os.path.relpath(artifact, output.parent),
        "sha256": digest,
        "collected_at": clean["collected_at"],
        "database_read_only": True,
        "database_fingerprint": "passed",
    }
    for section in ("yuyu", "snkrdunk"):
        state["operational_health"][section]["evidence"] = {
            "artifact": state["evidence"]["artifact"],
            "sha256": digest,
            "sections": ["database.operational_due", "database.operational_runs"],
        }
    # Publish evidence first and the referencing snapshot last. A failed write leaves the old snapshot.
    serialized = yaml.safe_dump(state, sort_keys=False, allow_unicode=True, width=100)
    atomic_write(artifact, content)
    atomic_write(
        output,
        "# Generated staging observation; reverify before operational decisions.\n"
        + serialized,
    )
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--live",
        action="store_true",
        help="Read the pinned staging projects and database; never scrape sources",
    )
    mode.add_argument(
        "--fixture",
        type=Path,
        help="Replay evidence offline; cannot overwrite canonical CURRENT_STATE.yaml",
    )
    parser.add_argument("--environment", choices=["staging"], default="staging")
    parser.add_argument("--output", type=Path, default=CANONICAL_OUTPUT)
    args = parser.parse_args(argv)
    try:
        if args.fixture:
            evidence = json.loads(args.fixture.read_text())
            evidence["mode"] = "fixture"
        else:
            evidence = collect_live()
        state = write_snapshot(evidence, args.output)
    except (
        VerificationError,
        KeyError,
        ValueError,
        TypeError,
        OSError,
        ImportError,
    ) as error:
        message = (
            str(error)
            if isinstance(error, VerificationError)
            else "Required input, dependency or output unavailable; no snapshot replaced"
        )
        print(message, file=sys.stderr)
        return 1
    print(
        f"Wrote {args.output}; mode={state['collection_mode']}; verified_at={state['verified_at']}; blockers={len(state['blockers'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
