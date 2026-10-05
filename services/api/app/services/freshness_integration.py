"""The shared opt-in collector/discovery boundary; no worker-specific scheduler.

Install opcg-collection-services from services/api in collector images. The caller
supplies its session (SNKRDUNK pins it to the singleton lock connection). Every
network grant commits before I/O; result fencing, domain writes, checkpoint writes
and completion share one transaction. Importing this module enables nothing.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import time

from sqlalchemy import select

from app.models import (
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    RawSnapshot,
    SourceDispatchBudget,
    Source,
    SourceCardMapping,
)
from app.services.freshness_policy import FreshnessPolicy, utc_now
from app.services.freshness_queue import (
    PriceCategory,
    admit_request,
    claim_due,
    complete_claim,
    lock_for_result,
    pause_source,
    plan_refresh,
)

CATEGORIES = {
    "yuyutei": {"raw": PriceCategory("sell")},
    "snkrdunk": {
        "raw": PriceCategory("floor"),
        "psa10": PriceCategory("psa10_asking", "PSA10"),
    },
}


class AdmissionStopped(RuntimeError):
    pass


@dataclass
class CaptureResult:
    outcome: str
    raw_snapshot_id: int | None = None
    observation_ids: dict[str, int] = field(default_factory=dict)
    no_listing_categories: set[str] = field(default_factory=set)
    category_outcomes: dict[str, str] = field(default_factory=dict)
    failure: str | None = None
    resume_cursor: dict | None = None
    next_due_at: datetime | None = None


def plan_product(session, mapping_id, source_name, *, high_interest, request_bound):
    """One product, one mapping, all categories; explicit conservative cost bound."""
    actual_source = session.scalar(
        select(Source.name)
        .join(SourceCardMapping, SourceCardMapping.source_id == Source.id)
        .where(SourceCardMapping.id == mapping_id)
    )
    if actual_source != source_name:
        raise ValueError("mapping does not belong to the requested source")
    return plan_refresh(
        session,
        mapping_id,
        CATEGORIES[source_name],
        high_interest=high_interest,
        estimated_request_cost=request_bound,
    )


class Attempt:
    def __init__(
        self, session, claim, *, ownership_check=lambda session: None, clock=utc_now
    ):
        self.session, self.claim = session, claim
        self.ownership_check, self.clock = ownership_check, clock
        self.ordinal = 0
        self.charged_cost = 0
        self.stopped = None
        self.denied = False
        self.raw_snapshot_id = None
        self.result = None
        self.health = {"http_403": 0, "http_429": 0, "optional_resource": 0}

    def check(self):
        if self.stopped:
            raise AdmissionStopped(self.stopped)
        self.ownership_check(self.session)

    def admit(self, *, cost=1):
        self.check()
        try:
            granted = admit_request(
                self.session,
                self.claim.claim_token,
                ordinal=self.ordinal + 1,
                cost=cost,
                clock=self.clock,
            )
            if not granted:
                raise AdmissionStopped("request ordinal already consumed")
            self.ownership_check(self.session)
            self.session.commit()
            self.ordinal += 1
            self.charged_cost += cost
        except Exception as exc:
            self.session.rollback()
            self.stopped = str(exc)
            raise AdmissionStopped(self.stopped) from exc

    def record_http(self, status):
        if status in {403, 429}:
            self.health[f"http_{status}"] += 1

    def deny(self):
        self.denied = True
        try:
            self.ownership_check(self.session)
            pause_source(self.session, self.claim.claim_token, clock=self.clock)
            self.session.commit()
        finally:
            self.stopped = "source_denial"

    def install_browser(self, context):
        """Meter ALL browser traffic, including subresources and redirects.

        fetch does not follow redirects/retry. Redirects are refused: browser
        routing does not guarantee interception of redirect chains. Service
        workers must be blocked when the context is created. APIRequestContext is separate; use
        request_bytes for artwork. Even third-party resources are charged to the
        source, conservatively. WebSockets are blocked (not a collection input).
        """

        def route_request(route):
            try:
                self.admit()
                response = route.fetch(max_redirects=0, max_retries=0, timeout=30000)
                if 300 <= response.status < 400:
                    raise AdmissionStopped(
                        "browser redirect requires explicit admitted navigation"
                    )
                self.record_http(response.status)
                if response.status in {403, 429}:
                    self.deny()
                route.fulfill(response=response)
            except Exception as exc:
                self.stopped = self.stopped or str(exc)
                route.abort()

        context.route("**/*", route_request)
        context.route_web_socket("**/*", lambda socket: socket.close())

    def http_get(self, client, url):
        """Inject into discovery/validation transports without owning checkpoints.

        Redirects are returned as evidence, never followed invisibly. The caller
        may validate the location and call again (another grant and its pacing).
        HTTP clients must use a transport with retries disabled.
        """
        self.admit()
        response = client.get(url, follow_redirects=False)
        self.record_http(response.status_code)
        if response.status_code in {403, 429}:
            self.deny()
        return response

    def request_bytes(self, page, url):
        self.admit()
        response = page.context.request.get(
            url, max_redirects=0, max_retries=0, timeout=20000
        )
        self.record_http(response.status)
        if response.status in {403, 429}:
            self.deny()
        self.check()
        if not response.ok:
            self.health["optional_resource"] += 1
        return response.body() if response.ok else None

    def snapshot(self, source_id, url, step, parser_version):
        """Persist evidence before parsing. Never use this for saved-file replay."""
        self.ownership_check(self.session)
        row = RawSnapshot(
            source_id=source_id,
            source_url=url,
            fetched_at=self.clock(),
            http_status=step.get("http_status") or 0,
            raw_content=step["html"],
            content_hash=hashlib.sha256(step["html"].encode()).hexdigest(),
            parser_version=parser_version,
        )
        self.session.add(row)
        self.session.flush()
        snapshot_id = row.id
        self.ownership_check(self.session)
        self.session.commit()
        return snapshot_id

    def begin_result(self):
        self.check()
        if not lock_for_result(self.session, self.claim.claim_token, clock=self.clock):
            raise AdmissionStopped("result already completed; skip writer")

    def finish(self, result):
        """Caller has fenced BEFORE domain/checkpoint writes. Roll back on refusal."""
        try:
            self.ownership_check(self.session)
            if not lock_for_result(
                self.session, self.claim.claim_token, clock=self.clock
            ):
                self.session.rollback()
                return False
            complete_claim(
                self.session,
                self.claim.claim_token,
                outcome=result.outcome,
                actual_request_cost=self.charged_cost,
                raw_snapshot_id=result.raw_snapshot_id,
                observation_ids=result.observation_ids,
                no_listing_categories=result.no_listing_categories,
                category_outcomes=result.category_outcomes,
                failure=result.failure,
                resume_cursor=result.resume_cursor,
                next_due_at=result.next_due_at,
                clock=self.clock,
            )
            self.ownership_check(self.session)
            self.session.commit()
            return True
        except Exception:
            self.session.rollback()
            raise


def price_facts(session, work_id, *, clock=utc_now):
    """Detached API-reader contract. This does not change any public endpoint."""
    work = session.get(FreshnessWork, work_id)
    policy = FreshnessPolicy(
        headroom=timedelta(seconds=work.execution_headroom_seconds)
    )
    latest = session.scalar(
        select(FreshnessAttempt)
        .where(
            FreshnessAttempt.work_id == work_id, FreshnessAttempt.outcome.is_not(None)
        )
        .order_by(FreshnessAttempt.id.desc())
        .limit(1)
    )
    outcomes = (latest.category_outcomes or {}) if latest else {}
    facts = []
    for state in session.scalars(
        select(FreshnessPriceState).where(FreshnessPriceState.work_id == work_id)
    ):
        capture = state.last_valid_price_observed_at
        facts.append(
            dict(
                category=state.price_category,
                policy_version=work.policy_version,
                availability=state.availability,
                attempted_at=work.last_attempted_at,
                checked_at=state.last_successfully_checked_at,
                captured_at=capture,
                observation_id=state.last_observation_id,
                next_due_at=state.next_due_at,
                retry_not_before_at=state.retry_not_before_at,
                consecutive_failures=state.consecutive_failures or 0,
                expires_at=(
                    policy.expiry(capture, high_interest=work.high_interest)
                    if capture
                    else None
                ),
                freshness=policy.verdict(
                    capture, high_interest=work.high_interest, clock=clock
                ),
                category_outcome=outcomes.get(
                    state.price_category, latest.outcome if latest else "unknown"
                ),
                last_outcome=work.last_outcome,
            )
        )
    return facts


def _drain(
    session,
    source_id,
    owner,
    runner,
    *,
    runtime_seconds,
    mapping_seconds,
    chunk_size=70,
    shard_index=None,
    delay_seconds=1,
    ownership_check=lambda session: None,
    clock=utc_now,
    monotonic=time.monotonic,
    sleep=time.sleep,
    max_work=None,
    telemetry=None,
):
    """Serial bounded chunks. Claim just-in-time so unstarted tails stay pending.

    chunk_size bounds each inner chunk, not the catalogue. No calendar sleep;
    immediately select the next due chunk within the existing runtime budget.
    """
    if (
        not 1 <= chunk_size <= 100
        or runtime_seconds <= 0
        or mapping_seconds <= 0
        or delay_seconds < 0
    ):
        raise ValueError(
            "positive bounded runtime/chunk and nonnegative pacing required"
        )
    if (
        session.scalar(
            select(SourceDispatchBudget).where(
                SourceDispatchBudget.source_id == source_id
            )
        )
        is None
    ):
        session.rollback()
        if telemetry is not None:
            telemetry["stopped_reason"] = "admission_unconfigured"
        return []  # unconfigured admission is closed, never unlimited
    if max_work is not None and (type(max_work) is not int or max_work < 1):
        raise ValueError("positive execution work bound required")
    deadline = monotonic() + runtime_seconds
    results = []
    while monotonic() + mapping_seconds <= deadline:
        for _ in range(chunk_size):
            if max_work is not None and len(results) >= max_work:
                if telemetry is not None:
                    telemetry["stopped_reason"] = "work_bound"
                return results
            if monotonic() + mapping_seconds > deadline:
                if telemetry is not None:
                    telemetry["stopped_reason"] = "runtime_bound"
                return results
            ownership_check(session)
            claims = claim_due(
                session,
                source_id,
                owner,
                limit=1,
                lease=timedelta(seconds=mapping_seconds + 60),
                clock=clock,
                yuyutei_shard_index=shard_index,
                supported_kinds={"refresh"},
            )
            session.commit()
            if not claims:
                return results
            attempt = Attempt(
                session, claims[0], ownership_check=ownership_check, clock=clock
            )
            try:
                outcome = runner(
                    session, claims[0].source_card_mapping_id, freshness=attempt
                )
                if attempt.result is None:
                    session.rollback()
                    attempt.result = CaptureResult(
                        (
                            "source_denial"
                            if attempt.denied or outcome.source_denied
                            else (
                                "identity_refusal"
                                if outcome.stage
                                in {"validation_failed", "mapping_load_failed"}
                                else "transient_failure"
                            )
                        ),
                        failure=";".join(outcome.reasons),
                    )
                if (
                    telemetry is not None
                    and getattr(outcome, "classification", None)
                    == "challenge_or_captcha"
                ):
                    telemetry["challenge"] += 1
                if attempt.result.raw_snapshot_id is None:
                    attempt.result.raw_snapshot_id = attempt.raw_snapshot_id
                attempt.finish(attempt.result)
            except AdmissionStopped as exc:
                session.rollback()
                attempt.result = CaptureResult(
                    "source_denial" if attempt.denied else "transient_failure",
                    failure=str(exc),
                    raw_snapshot_id=attempt.raw_snapshot_id,
                )
                attempt.finish(attempt.result)
            except Exception:
                session.rollback()
                # Ownership/lease failures propagate; the expired reservation is
                # recovered conservatively. Never reacquire a singleton here.
                raise
            if telemetry is not None:
                for field, count in attempt.health.items():
                    telemetry[field] += count
            results.append(price_facts(session, claims[0].work_id, clock=clock))
            session.commit()
            if attempt.stopped or attempt.result.outcome == "source_denial":
                if telemetry is not None:
                    telemetry["stopped_reason"] = (
                        "source_denial"
                        if attempt.result.outcome == "source_denial"
                        else "admission_stopped"
                    )
                return results
            sleep(delay_seconds)
    if telemetry is not None:
        telemetry["stopped_reason"] = "runtime_bound"
    return results


def drain(session, source_id, owner, runner, **kwargs):
    """Retain execution identity automatically on the natural due-work path."""
    from app.services.operational_health_runtime import execution

    with execution(
        session,
        source_id,
        owner,
        shard=kwargs.get("shard_index"),
        max_work=kwargs.get("max_work"),
        runtime_seconds=kwargs.get("runtime_seconds"),
        singleton=(
            "held"
            if session.info.get("snkrdunk_collection_lock_pid") is not None
            else "not_required" if kwargs.get("shard_index") is not None else "unknown"
        ),
    ) as telemetry:
        return _drain(
            session,
            source_id,
            telemetry["owner"] if telemetry else owner,
            runner,
            telemetry=telemetry,
            **kwargs,
        )
