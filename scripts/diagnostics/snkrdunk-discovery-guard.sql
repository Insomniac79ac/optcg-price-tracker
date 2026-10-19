-- SNKRDUNK automatic discovery guard inputs, read-only. Owner task (2026-10-19): watch the first
-- discovery runs after #180. The planner (snkrdunk_collector/discovery_planner.py) logs its skip
-- reason only to stdout, so this recomputes the inputs of its request_budget guard: spare budget
-- versus (pending RAW checks due within 40 minutes) x (highest RAW check request cost in 24h)
-- plus the intent's 300 requests.
-- About turns: snkrdunk-due executions in the last 12 hours (finished rows carry the outcome).
-- turns
select e.created_at, e.event_type, left(e.context_json -> 'identity' ->> 'revision', 7) revision,
  e.context_json -> 'identity' ->> 'deployment_id' deployment_id,
  e.context_json -> 'identity' ->> 'started_at' started_at,
  e.context_json -> 'identity' ->> 'runtime_seconds' runtime_seconds,
  e.context_json -> 'exit' ->> 'terminal_state' terminal_state,
  e.context_json -> 'exit' ->> 'stopped_reason' stopped_reason,
  e.context_json -> 'work' ->> 'due' due, e.context_json -> 'work' ->> 'claimed' claimed,
  e.context_json -> 'work' ->> 'attempted' attempted
from app_log_events e
where e.service = 'snkrdunk-collector'
  and e.event_type in ('raw_execution_started', 'raw_execution_finished')
  and e.created_at > now() - interval '12 hours'
order by e.id;

-- About guard_now: the request_budget guard as the planner would compute it at this moment.
-- guard_now
with s as (select id from sources where name = 'snkrdunk'),
b as (
  select b.request_limit, b.reserved_requests,
    case when extract(epoch from now() - b.window_started_at) >= b.window_seconds then 0
      else b.used_requests end used
  from source_dispatch_budgets b where b.source_id = (select id from s)),
d as (
  select count(*) demand from freshness_work w
  where w.source_id = (select id from s) and w.kind = 'refresh' and w.state = 'pending'
    and w.next_due_at <= now() + interval '40 minutes'),
p as (
  select coalesce(max(a.actual_request_cost), 0) peak from freshness_attempts a
  join freshness_work w on w.id = a.work_id
  where w.source_id = (select id from s) and w.kind = 'refresh'
    and a.finished_at >= now() - interval '1 day')
select b.request_limit - b.used - b.reserved_requests spare, d.demand, p.peak,
  d.demand * p.peak + 300 needed,
  d.demand * p.peak + 300 > b.request_limit - b.used - b.reserved_requests would_skip
from b, d, p;

-- About guard_at_turns: for each turn start in the last 12 hours, the 24h peak cost at that time and
-- the RAW checks actually claimed in the following 40 minutes (a proxy for demand then).
-- guard_at_turns
with s as (select id from sources where name = 'snkrdunk'),
t as (
  select (e.context_json -> 'identity' ->> 'started_at')::timestamptz started
  from app_log_events e
  where e.service = 'snkrdunk-collector' and e.event_type = 'raw_execution_started'
    and e.created_at > now() - interval '12 hours'),
a as (
  select a.claimed_at, a.finished_at, a.actual_request_cost from freshness_attempts a
  join freshness_work w on w.id = a.work_id
  where w.source_id = (select id from s) and w.kind = 'refresh'
    and a.claimed_at > now() - interval '40 hours')
select t.started,
  (select coalesce(max(actual_request_cost), 0) from a
    where a.finished_at >= t.started - interval '1 day' and a.finished_at < t.started) peak,
  (select count(*) from a where a.claimed_at >= t.started
    and a.claimed_at < t.started + interval '40 minutes') claimed_next_40m,
  3100 - 300 budget_after_intent
from t order by 1;

-- About check_cost_24h: RAW check request cost distribution, last 24 hours.
-- check_cost_24h
select count(*) n, min(a.actual_request_cost) min_cost,
  percentile_disc(0.5) within group (order by a.actual_request_cost) p50,
  percentile_disc(0.9) within group (order by a.actual_request_cost) p90,
  max(a.actual_request_cost) max_cost, sum(a.actual_request_cost) total
from freshness_attempts a join freshness_work w on w.id = a.work_id
join sources s on s.id = w.source_id
where s.name = 'snkrdunk' and w.kind = 'refresh' and a.finished_at >= now() - interval '1 day';
