"""Retain due execution boundaries in existing app_log_events, not a new truth store.

Independent short event transactions cannot commit collector/domain transactions.
Only staging is instrumented. A failed event write cannot enable requests or
turn an incomplete receipt healthy; underlying attempts remain reconstructible.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
import os
import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models import AppLogEvent
from app.services.operational_health import empty_summary
from app.services.operational_health_sql import DUE_SQL, RUN_SQL


def utc():
    return datetime.now(timezone.utc).isoformat()


def persist(engine, summary, terminal=False):
    try:
        with Session(engine) as event_session:
            event_session.add(
                AppLogEvent(
                    level="info",
                    service=summary["identity"]["service"],
                    event_type=(
                        "raw_execution_finished"
                        if terminal
                        else "raw_execution_started"
                    ),
                    message="RAW execution evidence",
                    context_json=summary,
                )
            )
            event_session.commit()
        return True
    except Exception:
        # No provider/driver exception text: it can contain credentials.
        return False


@contextmanager
def execution(
    session,
    source_id,
    owner,
    *,
    shard=None,
    max_work=None,
    runtime_seconds=None,
    singleton="not_required",
    clock=utc,
):
    # Instrument only the pinned Railway staging environment; no production write.
    if (
        os.environ.get("RAILWAY_ENVIRONMENT_ID")
        != "05d1eac2-510d-4bd3-999e-fea9ead766b7"
        or os.environ.get("APP_ENV") == "production"
    ):
        yield None
        return
    run_owner = f"{owner}:{uuid.uuid4().hex}"
    summary = empty_summary()
    identity = summary["identity"]
    identity.update(
        source="yuyutei" if shard is not None else "snkrdunk",
        service=(
            f"yuyutei-collector-shard-{shard}"
            if shard is not None
            else "snkrdunk-collector"
        ),
        shard=shard,
        execution_id=run_owner,
        deployment_id=os.environ.get("RAILWAY_DEPLOYMENT_ID"),
        revision=None,
        trigger="unknown",
        started_at=clock(),
    )
    provider_service = os.environ.get("RAILWAY_SERVICE_NAME")
    if provider_service and re.fullmatch(
        r"snkrdunk-collector|yuyutei-collector-shard-[0-8](?:-v2)?", provider_service
    ):
        identity["service"] = provider_service
    try:
        from app.services.collector_build import REVISION
    except ImportError:
        REVISION = None
    if REVISION and re.fullmatch("[0-9a-f]{40}", REVISION):
        identity["revision"] = REVISION
    summary["work"]["max_work"] = max_work
    summary["work"]["runtime_limit_seconds"] = runtime_seconds
    summary["safety"].update(
        singleton=singleton,
        identity_integrity="guarded",
        promotion_policy="guarded" if shard is not None else "not_applicable",
        production_impact=False,
    )
    summary["exit"].update(terminal_state="running")
    engine = session.get_bind()
    # A pinned connection cannot be shared by independent event transactions.
    event_engine = getattr(engine, "engine", engine)
    persist(event_engine, summary)
    telemetry = {
        "owner": run_owner,
        "summary": summary,
        "http_403": 0,
        "http_429": 0,
        "challenge": 0,
        "optional_resource": 0,
        "stopped_reason": None,
    }
    try:
        yield telemetry
        summary["exit"].update(
            terminal_state="completed", stopped_reason=telemetry["stopped_reason"]
        )
    except BaseException as error:
        summary["exit"].update(
            terminal_state="interrupted",
            stopped_reason=(
                "singleton_lost"
                if type(error).__name__ == "LockLost"
                else "execution_error"
            ),
        )
        if type(error).__name__ == "LockLost":
            summary["safety"]["singleton"] = "lost"
        raise
    finally:
        identity["finished_at"] = clock()
        identity["runtime_seconds"] = (
            datetime.fromisoformat(identity["finished_at"])
            - datetime.fromisoformat(identity["started_at"])
        ).total_seconds()
        # Never infer the OS exit code from Python return/exception; process may
        # die after this boundary. This is the execution's terminal receipt.
        try:
            # The caller commits each attempt. Read on a separate connection
            # so telemetry never changes or commits any domain transaction.
            with event_engine.connect() as connection:
                connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                connection.execute(text("SET LOCAL statement_timeout = '30s'"))
                facts = dict(
                    connection.execute(
                        text(RUN_SQL),
                        {"owner": run_owner, "source_id": source_id, "shard": shard},
                    )
                    .mappings()
                    .one()
                )
                rows = connection.execute(text(DUE_SQL)).mappings().all()
                relevant = [
                    r
                    for r in rows
                    if r["source"] == identity["source"]
                    and (shard is None or r["shard"] == shard)
                ]
                for field in (
                    "claimed",
                    "attempted",
                    "listed",
                    "no_listing",
                    "completed",
                    "discovery_progress",
                    "raw_snapshots",
                    "accepted_observations",
                    "promotional_hidden",
                ):
                    summary["work"][field] = facts[field]
                summary["work"]["selected"] = facts[
                    "claimed"
                ]  # just-in-time selection == claim
                summary["work"]["eligible"] = sum(r["eligible"] for r in relevant)
                summary["work"]["due"] = sum(r["due"] for r in relevant)
                for field in (
                    "claims_remaining",
                    "expired_claims",
                    "reservations_remaining",
                    "reservation_overruns",
                    "wrong_shard",
                ):
                    summary["safety"][field] = facts[field]
                summary["safety"]["duplicate_requests"] = (
                    0 if facts["request_cost_mismatch"] == 0 else None
                )
                for field in ("transient", "parsing", "identity"):
                    summary["failure"][field] = facts[field]
                for field in ("http_403", "http_429", "challenge", "optional_resource"):
                    summary["failure"][field] = telemetry[field]
                summary["failure"]["unexpected_skip"] = (
                    0 if summary["exit"]["terminal_state"] == "completed" else None
                )
                summary["freshness"].update(
                    successful_checks=facts["listed"] + facts["no_listing"],
                    deadline_misses=sum(r["overdue"] for r in relevant),
                    never_checked=sum(r["never_checked"] for r in relevant),
                    backoff=sum(r["backoff"] for r in relevant),
                    retries=sum(r["retries"] for r in relevant),
                )
                if len(relevant) == 1:
                    for field in (
                        "successful_check_age_p50",
                        "successful_check_age_p95",
                        "successful_check_age_max",
                        "maximum_successful_revisit_gap_seconds",
                    ):
                        summary["freshness"][field] = (
                            float(relevant[0][field])
                            if relevant[0][field] is not None
                            else None
                        )
        except Exception:
            # Partial/null metrics explicitly prevent a false HEALTHY verdict.
            pass
        persist(event_engine, summary, terminal=True)
