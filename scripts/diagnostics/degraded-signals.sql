-- Why a source or raw_due_work is DEGRADED: the shared operational-health population split by
-- work state, with block timing (session 13 tools/degraded_signals.py).
-- by_source_state
with e as ({{ELIGIBLE}})
select source, coalesce(state, 'unplanned') state, count(*) n,
  count(*) filter (where checked_at is null or checked_at < now() - interval '24 hours') overdue,
  count(*) filter (where checked_at is null) never_checked,
  count(*) filter (where checked_at < now() - interval '24 hours') over_24h,
  count(*) filter (where retry_not_before_at > now()) backoff
from e group by 1, 2 order by 1, 2;

-- blocked_timing
with e as ({{ELIGIBLE}})
select e.source, count(*) n, min(w.updated_at) first_blocked_update, max(w.updated_at) last_blocked_update,
  min(w.last_failure_at) min_failure_at, max(w.last_failure_at) max_failure_at,
  min(e.checked_at) oldest_success, max(e.checked_at) newest_success
from e join freshness_work w on w.id = e.work_id where e.state = 'blocked' group by 1 order by 1;

-- blocked_failure_class
with e as ({{ELIGIBLE}})
select e.source, w.last_outcome, left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 60) failure_class,
  count(*) n
from e join freshness_work w on w.id = e.work_id where e.state = 'blocked' group by 1, 2, 3 order by 4 desc;

-- overdue_not_blocked
with e as ({{ELIGIBLE}})
select source, count(*) n from e where coalesce(state, '') <> 'blocked'
  and (checked_at is null or checked_at < now() - interval '24 hours') group by 1 order by 1;
