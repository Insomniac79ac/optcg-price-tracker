-- Why a source or raw_due_work is DEGRADED: the shared operational-health population split by
-- work state, with block timing (session 13 tools/degraded_signals.py).
-- old_vs_new_overdue
-- Same eligible population as the health signal. old_overdue counts a never-checked
-- mapping immediately; new_overdue waits 24h after mapped_at. difference equals
-- first_collection_pending when every row has mapped_at.
with e as ({{ELIGIBLE}})
select source,
 count(*) filter (where checked_at is null or checked_at < now() - interval '24 hours') old_overdue,
 count(*) filter (where coalesce(checked_at, mapped_at) < now() - interval '24 hours'
   or (checked_at is null and mapped_at is null)) new_overdue,
 count(*) filter (where checked_at is null and mapped_at >= now() - interval '24 hours') first_collection_pending,
 count(*) filter (where checked_at is null or checked_at < now() - interval '24 hours')
   - count(*) filter (where coalesce(checked_at, mapped_at) < now() - interval '24 hours'
   or (checked_at is null and mapped_at is null)) difference
from e group by 1 order by 1;

-- by_source_state
with e as ({{ELIGIBLE}})
select source, coalesce(state, 'unplanned') state, count(*) n,
  count(*) filter (where coalesce(checked_at, mapped_at) < now() - interval '24 hours'
    or (checked_at is null and mapped_at is null)) overdue,
  count(*) filter (where checked_at is null) never_checked,
  count(*) filter (where checked_at is null and mapped_at >= now() - interval '24 hours') first_collection_pending,
  count(*) filter (where coalesce(checked_at, mapped_at) < now() - interval '24 hours'
    or (checked_at is null and mapped_at is null)) over_24h,
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
  and (coalesce(checked_at, mapped_at) < now() - interval '24 hours'
    or (checked_at is null and mapped_at is null)) group by 1 order by 1;
