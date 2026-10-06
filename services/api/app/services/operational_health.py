"""Versioned RAW operational evidence and deterministic, side-effect-free decisions.

Counts describe retained facts, never absence inferred from missing telemetry.
This module has no provider, database, scheduler or notification dependencies.
"""

from copy import deepcopy
from datetime import datetime

VERSION = 1
SECTIONS = {
    "identity": (
        "source",
        "service",
        "shard",
        "execution_id",
        "deployment_id",
        "revision",
        "image",
        "scheduled_at",
        "started_at",
        "finished_at",
        "runtime_seconds",
        "trigger",
    ),
    "work": (
        "eligible",
        "due",
        "selected",
        "claimed",
        "attempted",
        "listed",
        "no_listing",
        "completed",
        "discovery_progress",
        "promotional_hidden",
        "accepted_observations",
        "raw_snapshots",
        "max_work",
        "runtime_limit_seconds",
    ),
    "failure": (
        "transient",
        "parsing",
        "identity",
        "optional_resource",
        "http_403",
        "http_429",
        "challenge",
        "unexpected_skip",
    ),
    "freshness": (
        "successful_checks",
        "deadline_misses",
        "successful_check_age_p50",
        "successful_check_age_p95",
        "successful_check_age_max",
        "never_checked",
        "retries",
        "backoff",
        "maximum_successful_revisit_gap_seconds",
    ),
    "safety": (
        "claims_remaining",
        "expired_claims",
        "reservations_remaining",
        "reservation_overruns",
        "singleton",
        "duplicate_requests",
        "wrong_shard",
        "identity_integrity",
        "promotion_policy",
        "production_impact",
    ),
    "exit": ("terminal_state", "exit_code", "stopped_reason"),
}


def empty_summary():
    return {
        "schema_version": VERSION,
        **{section: dict.fromkeys(fields) for section, fields in SECTIONS.items()},
    }


def validate(summary):
    if summary.get("schema_version") != VERSION or set(summary) != {
        "schema_version",
        *SECTIONS,
    }:
        raise ValueError("Unsupported operational summary schema")
    for section, fields in SECTIONS.items():
        if set(summary[section]) != set(fields):
            raise ValueError("Unexpected operational summary fields")
    identity = summary["identity"]
    if identity["source"] not in {"yuyutei", "snkrdunk"} or identity["trigger"] not in {
        "natural",
        "manual",
        "unknown",
    }:
        raise ValueError("Invalid execution identity/provenance")
    if identity["shard"] is not None and (
        type(identity["shard"]) is not int or not 0 <= identity["shard"] < 9
    ):
        raise ValueError("Invalid shard")
    for field in ("scheduled_at", "started_at", "finished_at"):
        if identity[field] is not None:
            t = datetime.fromisoformat(identity[field])
            if t.utcoffset() is None or t.utcoffset().total_seconds() != 0:
                raise ValueError("UTC execution timestamps required")
    if (
        identity["finished_at"]
        and identity["started_at"]
        and datetime.fromisoformat(identity["finished_at"])
        < datetime.fromisoformat(identity["started_at"])
    ):
        raise ValueError("Execution finish precedes start")
    if identity["runtime_seconds"] is not None and (
        type(identity["runtime_seconds"]) not in {int, float}
        or identity["runtime_seconds"] < 0
    ):
        raise ValueError("Nonnegative runtime or null required")
    for field in (
        "claims_remaining",
        "expired_claims",
        "reservations_remaining",
        "reservation_overruns",
        "duplicate_requests",
        "wrong_shard",
    ):
        value = summary["safety"][field]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Nonnegative safety counters or null required")
    for section in ("work", "failure", "freshness"):
        for value in summary[section].values():
            if value is not None and (type(value) not in {int, float} or value < 0):
                raise ValueError("Nonnegative metrics or null required")
    return summary


def sanitize(summary):
    # Allowlist rather than accepting arbitrary context/log strings in state artifacts.
    clean = empty_summary()
    for section, fields in SECTIONS.items():
        for field in fields:
            value = summary.get(section, {}).get(field)
            if value is None or type(value) in {str, int, float, bool}:
                clean[section][field] = value
    clean["schema_version"] = summary.get("schema_version")
    return validate(clean)


def classify(summary):
    validate(summary)
    failure, safety, freshness, work = (
        summary[k] for k in ("failure", "safety", "freshness", "work")
    )
    blocked = []
    for key in (
        "duplicate_requests",
        "reservation_overruns",
        "wrong_shard",
        "production_impact",
    ):
        if safety[key]:
            blocked.append(key)
    for key in ("identity_integrity", "promotion_policy"):
        if safety[key] == "violated":
            blocked.append(key)
    if safety["claims_remaining"] and safety["expired_claims"]:
        blocked.append("stuck_expired_claims")
    if summary["exit"]["terminal_state"] == "completed" and (
        safety["claims_remaining"] or safety["reservations_remaining"]
    ):
        blocked.append("unsettled_terminal_execution")
    if safety["singleton"] == "lost":
        blocked.append("singleton_lost")
    # Each denial stops the source path at its existing admission guard; never
    # keep probing until a percentage threshold makes widespread denial visible.
    for key in ("http_403", "http_429", "challenge"):
        if failure[key]:
            blocked.append(key)
    if summary["exit"]["stopped_reason"] in {
        "source_denial",
        "integrity",
        "security",
        "production",
        "RED",
    }:
        blocked.append(summary["exit"]["stopped_reason"])
    if blocked:
        return {
            "status": "BLOCKED",
            "reasons": sorted(set(blocked)),
            "action": "stop_affected_path",
            "human_report": True,
        }
    degraded = []
    for key in (
        "transient",
        "parsing",
        "identity",
        "optional_resource",
        "unexpected_skip",
    ):
        if failure[key]:
            degraded.append(key)
    for key in ("deadline_misses", "never_checked", "backoff"):
        if freshness[key]:
            degraded.append(key)
    if safety["expired_claims"]:
        degraded.append("expired_claims")
    if safety["claims_remaining"] or safety["reservations_remaining"]:
        degraded.append("unsettled_execution")
    if summary["exit"]["stopped_reason"] == "admission_unconfigured":
        degraded.append("admission_unconfigured")
    if summary["exit"]["terminal_state"] != "completed":
        degraded.append("execution_incomplete")
    if work["max_work"] is not None and (work["claimed"] or 0) > work["max_work"]:
        return {
            "status": "BLOCKED",
            "reasons": ["execution_work_bound_exceeded"],
            "action": "stop_affected_path",
            "human_report": True,
        }
    # No green verdict from an empty/partial receipt, a lock skip or missing
    # proof that the actual claims and charged reservations settled.
    required = [
        work[k]
        for k in ("claimed", "attempted", "listed", "no_listing", "raw_snapshots")
    ]
    required += [
        failure[k]
        for k in (
            "transient",
            "parsing",
            "identity",
            "http_403",
            "http_429",
            "challenge",
            "unexpected_skip",
        )
    ]
    required += [
        safety[k]
        for k in (
            "claims_remaining",
            "expired_claims",
            "reservations_remaining",
            "reservation_overruns",
            "duplicate_requests",
            "wrong_shard",
        )
    ]
    required += [freshness[k] for k in ("deadline_misses", "never_checked")]
    if (
        work["attempted"] is not None
        and all(work[k] is not None for k in ("listed", "no_listing"))
        and all(failure[k] is not None for k in ("transient", "identity"))
    ):
        if (
            work["attempted"]
            > work["listed"]
            + work["no_listing"]
            + failure["transient"]
            + failure["identity"]
            + (work.get("completed") or 0)
            + (work.get("discovery_progress") or 0)
        ):
            degraded.append("unaccounted_attempts")
    if any(v is None for v in required) or safety["singleton"] in {
        None,
        "unknown",
        "contended",
    }:
        degraded.append("incomplete_evidence")
    if safety["identity_integrity"] != "guarded" or safety["promotion_policy"] not in {
        "guarded",
        "not_applicable",
    }:
        degraded.append("invariant_evidence_unknown")
    if degraded:
        return {
            "status": "DEGRADED",
            "reasons": sorted(set(degraded)),
            "action": "autonomous_fix_forward",
            "human_report": True,
        }
    return {
        "status": "HEALTHY",
        "reasons": [],
        "action": "silent_state_update",
        "human_report": False,
    }


def aggregate(due_rows, runs, budgets, now):
    """Current source/shard envelope plus latest retained executions.

    Guarded identity refusal isolates the item (DEGRADED aggregate), whereas a
    wrong identity accepted is BLOCKED. Unknown Railway provenance stays unknown.
    """
    result = {
        "schema_version": VERSION,
        "observed_at": now,
        "target_hours": 24,
        "dispatch_due_hours": 23,
    }
    totals = {
        k: 0
        for k in (
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
        )
    }
    ranks = {"HEALTHY": 0, "DEGRADED": 1, "BLOCKED": 2}
    for source, alias in (("yuyutei", "yuyu"), ("snkrdunk", "snkrdunk")):
        rows = [r for r in due_rows if r["source"] == source]
        counts = {k: sum(r.get(k) or 0 for r in rows) for k in totals}
        for k, v in counts.items():
            totals[k] += v
        retained = [
            sanitize(r) for r in runs if r.get("identity", {}).get("source") == source
        ]
        retained.sort(key=lambda r: r["identity"]["started_at"] or "", reverse=True)
        unfinished = [
            r
            for r in retained
            if r["identity"]["finished_at"] is None
            and not any(
                x["identity"]["execution_id"] == r["identity"]["execution_id"]
                and x["identity"]["finished_at"] is not None
                for x in retained
            )
        ]
        active = [
            r
            for r in unfinished
            if r["work"].get("runtime_limit_seconds") is not None
            and r["identity"]["started_at"] is not None
            and (
                datetime.fromisoformat(now)
                - datetime.fromisoformat(r["identity"]["started_at"])
            ).total_seconds()
            <= r["work"]["runtime_limit_seconds"] + 60
        ]
        considered = [
            r
            for r in retained
            if r not in active
            and (r["identity"]["finished_at"] is not None or r in unfinished)
        ]
        latest = considered[0] if considered else None
        # Retain every service's latest verdict so a healthy shard cannot hide
        # another shard's failure. A new execution supersedes only its own shard.
        services = {}
        for run in considered:
            services.setdefault(run["identity"]["service"], run)
        decisions = {service: classify(run) for service, run in services.items()}
        status = max(
            (d["status"] for d in decisions.values()), key=ranks.get, default="DEGRADED"
        )
        reasons = {reason for d in decisions.values() for reason in d["reasons"]}
        if not rows or not latest:
            reasons.add("incomplete_evidence")
            status = max((status, "DEGRADED"), key=ranks.get)
        expected_shards = {r["shard"] for r in rows if r["shard"] is not None}
        observed_shards = {r["identity"]["shard"] for r in services.values()}
        if expected_shards - observed_shards:
            status = max((status, "DEGRADED"), key=ranks.get)
            reasons.add("missing_shard_execution")
        if (
            latest
            and (
                datetime.fromisoformat(now)
                - datetime.fromisoformat(latest["identity"]["started_at"])
            ).total_seconds()
            > 7200
        ):
            status = max((status, "DEGRADED"), key=ranks.get)
            reasons.add("execution_evidence_stale")
        if counts["expired_claims"]:
            status = "BLOCKED"
            reasons.add("stuck_expired_claims")
        if (
            counts["overdue"]
            or counts["quarantined"]
            or counts["backoff"]
            or counts["expired_claims"]
        ):
            status = max((status, "DEGRADED"), key=ranks.get)
            reasons.add("due_work_deficit")
        budget = next((b for b in budgets if b.get("name") == source), {})
        if budget.get("reservation_mismatch") is True:
            status = "BLOCKED"
            reasons.add("orphaned_or_unaccounted_reservations")
        if budget.get("reservation_mismatch") is None:
            status = max((status, "DEGRADED"), key=ranks.get)
            reasons.add("budget_accounting_unverified")
        limit = budget.get("request_limit")
        used, reserved = budget.get("used_requests"), budget.get("reserved_requests")
        effective_used = used
        if (
            budget.get("window_started_at")
            and budget.get("window_seconds")
            and (
                datetime.fromisoformat(now)
                - datetime.fromisoformat(budget["window_started_at"])
            ).total_seconds()
            >= budget["window_seconds"]
        ):
            effective_used = (
                0  # same rollover semantics as source admission; reservations survive
            )
        headroom = (
            max(0, limit - effective_used - reserved)
            if all(type(v) in {int, float} for v in (limit, used, reserved))
            else None
        )
        if budget.get("permanent_pause") is True or (
            budget.get("paused_until") and budget["paused_until"] > now
        ):
            status = "BLOCKED"
            reasons.add("source_paused")
        if headroom == 0 or budget.get("enabled") is False:
            status = max((status, "DEGRADED"), key=ranks.get)
            reasons.add("capacity_pressure")
        result[alias] = {
            "status": status,
            "reasons": sorted(reasons),
            "action": (
                "stop_affected_path"
                if status == "BLOCKED"
                else (
                    "autonomous_fix_forward"
                    if status == "DEGRADED"
                    else "silent_state_update"
                )
            ),
            "latest_execution": latest["identity"] if latest else None,
            "active_executions": [r["identity"] for r in active],
            "latest_natural_run": next(
                (
                    r["identity"]
                    for r in retained
                    if r["identity"]["trigger"] == "natural"
                ),
                None,
            ),
            "trigger_provenance": (
                "unknown" if not latest else latest["identity"]["trigger"]
            ),
            "deadline_compliance": (
                "not_met"
                if counts["overdue"]
                else "unknown; instantaneous observation only"
            ),
            "blocked_shards": [
                service for service, d in decisions.items() if d["status"] == "BLOCKED"
            ],
            "identity_quarantine": counts["quarantined"],
            "due_work": counts,
            "budget": {
                "request_headroom": headroom,
                "utilization": used / limit if used is not None and limit else None,
                "reserved_requests": reserved,
                "open_reservations": budget.get("open_reservations"),
                "reservation_mismatch": budget.get("reservation_mismatch"),
                "window_seconds": budget.get("window_seconds"),
                "permanent_pause": budget.get("permanent_pause"),
            },
            "evidence": "state evidence: database.operational_due and database.operational_runs",
        }
    result["raw_due_work"] = {
        "status": max(
            (result[k]["status"] for k in ("yuyu", "snkrdunk")), key=ranks.get
        ),
        **totals,
        "deadline_misses": totals["overdue"],
        "by_source_and_shard": deepcopy(due_rows),
    }
    return result
