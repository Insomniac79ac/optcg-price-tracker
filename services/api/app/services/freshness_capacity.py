"""Deterministic, synthetic catalogue simulation. No DB, source I/O or activation."""

from dataclasses import asdict, dataclass
from datetime import timedelta
import heapq
import math

from app.services.freshness_policy import FreshnessPolicy, LANE_CYCLE

DAY = 86400
PRIORITY = {"high": 100, "ordinary": 50, "discovery": 0, "coverage": 20}


@dataclass(frozen=True)
class CapacityAssumptions:
    name: str
    source_products: int = 5000
    high_interest_products: int = 500
    discovery_scopes: int = 250
    first_coverage_scopes: int = 250
    seconds_per_capture: int = 6
    requests_per_capture: int = 2
    source_request_limit_per_day: int = 24000
    execution_headroom_seconds: int = 3600
    days: int = 7
    processing_chunk: int = 70

    def __post_init__(self):
        if not 0 <= self.high_interest_products <= self.source_products:
            raise ValueError("invalid product population")
        if (
            any(
                getattr(self, name) <= 0
                for name in (
                    "source_products",
                    "seconds_per_capture",
                    "requests_per_capture",
                    "source_request_limit_per_day",
                    "days",
                    "processing_chunk",
                )
            )
            or self.discovery_scopes < 0
            or self.first_coverage_scopes < 0
        ):
            raise ValueError(
                "positive configured capacity and nonnegative scopes required"
            )
        if self.source_request_limit_per_day < self.requests_per_capture:
            raise ValueError("source limit cannot admit even one capture")
        FreshnessPolicy(headroom=timedelta(seconds=self.execution_headroom_seconds))


@dataclass
class _Job:
    lane: str
    due: float
    interval: float
    expiry: float | None
    target: float | None
    sequence: int = 0


def simulate_capacity(assumptions: CapacityAssumptions) -> dict:
    """One serial source worker, continuously draining bounded chunks.

    Warm-start refresh dates are uniformly phased. Every capture succeeds, all
    timings include pacing/navigation, and there are no pauses or failures.
    These are optimistic assumptions, not measurements or deployment settings.
    """
    a = assumptions
    policy = FreshnessPolicy(headroom=timedelta(seconds=a.execution_headroom_seconds))
    jobs: list[_Job] = []
    queues: dict[str, list] = {lane: [] for lane in set(LANE_CYCLE)}
    populations = (
        ("high", a.high_interest_products, policy.high_interest_target.total_seconds()),
        (
            "ordinary",
            a.source_products - a.high_interest_products,
            policy.standard_target.total_seconds(),
        ),
        ("discovery", a.discovery_scopes, None),
        ("coverage", a.first_coverage_scopes, None),
    )
    offered_captures = 0.0
    for lane, population, target in populations:
        interval = target - a.execution_headroom_seconds if target else DAY
        offered_captures += population * DAY / interval
        for n in range(population):
            due = n * interval / population
            job = _Job(
                lane,
                due,
                interval,
                due + a.execution_headroom_seconds if target else None,
                target,
            )
            jobs.append(job)
            heapq.heappush(queues[lane], (due, 0, -PRIORITY[lane], len(jobs) - 1))
    max_time_captures = DAY / a.seconds_per_capture
    max_budget_captures = a.source_request_limit_per_day // a.requests_per_capture
    capacity = min(max_time_captures, max_budget_captures)
    now, window, charged = 0.0, 0, 0
    completed, late, sequence, next_report_day = 0, 0, 0, 1
    dispatched_requests = 0
    reports = []

    def report_until(timestamp):
        nonlocal next_report_day
        while next_report_day <= a.days and next_report_day * DAY <= timestamp:
            boundary = next_report_day * DAY
            due_by_lane = {
                lane: sum(j.lane == lane and j.due <= boundary for j in jobs)
                for lane in queues
            }
            overdue_prices = sum(
                j.expiry is not None and j.expiry <= boundary for j in jobs
            )
            backlog = sum(due_by_lane.values())
            previous = reports[-1]["outstanding_due_work"] if reports else 0
            reports.append(
                {
                    "day": next_report_day,
                    "outstanding_due_work": backlog,
                    "backlog_growth_since_previous_day": backlog - previous,
                    "expired_current_prices": overdue_prices,
                    "due_by_lane": dict(sorted(due_by_lane.items())),
                    "completed_captures_cumulative": completed,
                    "late_captures_cumulative": late,
                }
            )
            next_report_day += 1

    horizon = a.days * DAY
    while now < horizon:
        if int(now // DAY) != window:
            window, charged = int(now // DAY), 0
        if charged + a.requests_per_capture > a.source_request_limit_per_day:
            now = (window + 1) * DAY
            report_until(now)
            continue
        due_lanes = [
            lane for lane, heap in queues.items() if heap and heap[0][0] <= now
        ]
        if not due_lanes:
            now = min(heap[0][0] for heap in queues.values() if heap)
            report_until(now)
            continue
        lane = LANE_CYCLE[sequence % len(LANE_CYCLE)]
        if lane not in due_lanes:
            lane = min(due_lanes, key=lambda candidate: queues[candidate][0])
        _, _, _, job_id = heapq.heappop(queues[lane])
        job = jobs[job_id]
        charged += a.requests_per_capture
        dispatched_requests += a.requests_per_capture
        finished = now + a.seconds_per_capture
        report_until(finished)  # in-flight work is still outstanding at this boundary
        if finished > horizon:
            break
        sequence += 1
        completed += 1
        if job.expiry is not None and finished >= job.expiry:
            late += 1
        job.due, job.sequence = finished + job.interval, sequence
        job.expiry = finished + job.target if job.target else None
        heapq.heappush(queues[lane], (job.due, sequence, -PRIORITY[lane], job_id))
        now = finished
    report_until(horizon)
    return {
        "label": "SYNTHETIC SIMULATION — assumed timings, not live throughput",
        "policy_version": policy.version,
        "assumptions": asdict(a),
        "serial_workers": 1,
        "price_categories_share_product_capture": True,
        "offered_captures_per_day": round(offered_captures, 2),
        "offered_requests_per_day": round(offered_captures * a.requests_per_capture, 2),
        "capacity_captures_per_day_upper_bound": round(capacity, 2),
        "offered_load_deficit_captures_per_day": round(
            max(0, offered_captures - capacity), 2
        ),
        "capacity_can_sustain_check_cadence": offered_captures <= capacity,
        "simulated_deadlines_met": late == 0
        and all(r["expired_current_prices"] == 0 for r in reports),
        "processing_chunks_started": math.ceil(
            dispatched_requests / a.requests_per_capture / a.processing_chunk
        ),
        "actual_simulated_request_cost": dispatched_requests,
        "daily": reports,
    }
