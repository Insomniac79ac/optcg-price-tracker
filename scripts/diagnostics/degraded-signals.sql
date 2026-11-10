-- Why a source or raw_due_work is DEGRADED: the shared operational-health population split by
-- work state, with block timing (session 13 tools/degraded_signals.py).
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

-- old_vs_new_overdue
-- One row per source. old_overdue is the current rule: no successful check, or the
-- last successful check is older than 24 hours. new_overdue is true when
-- coalesce(last successful check, source_card_mappings.created_at) is older than
-- 24 hours, or when both times are missing. first_collection_pending is never
-- checked and created less than 24 hours ago. difference is old_overdue minus new_overdue.
with e as ({{ELIGIBLE}})
select e.source,
  count(*) filter (where e.checked_at is null or e.checked_at < now() - interval '24 hours') old_overdue,
  count(*) filter (where coalesce(e.checked_at, m.created_at) < now() - interval '24 hours'
    or (e.checked_at is null and m.created_at is null)) new_overdue,
  count(*) filter (where e.checked_at is null and m.created_at >= now() - interval '24 hours') first_collection_pending,
  count(*) filter (where e.checked_at is null or e.checked_at < now() - interval '24 hours')
    - count(*) filter (where coalesce(e.checked_at, m.created_at) < now() - interval '24 hours'
    or (e.checked_at is null and m.created_at is null)) difference
from e
join source_card_mappings m on m.id = e.mapping_id
group by 1
order by 1;

-- old_vs_new_changed_mappings
-- Every mapping whose overdue flag differs between the two rules.
-- total is the full count. At most 200 rows are returned.
with e as ({{ELIGIBLE}}),
flags as (
  select e.mapping_id, e.source, m.card_print_id, m.created_at,
    e.checked_at last_successful_check,
    (e.checked_at is null or e.checked_at < now() - interval '24 hours') old_overdue,
    (coalesce(e.checked_at, m.created_at) < now() - interval '24 hours'
      or (e.checked_at is null and m.created_at is null)) new_overdue
  from e
  join source_card_mappings m on m.id = e.mapping_id
),
changed as (
  select distinct mapping_id, source, card_print_id, created_at, last_successful_check,
    case when old_overdue then 'overdue' else 'not_overdue' end old_state,
    case when new_overdue then 'overdue' else 'not_overdue' end new_state
  from flags
  where old_overdue <> new_overdue
)
select mapping_id, source, card_print_id, created_at, last_successful_check,
  old_state, new_state, count(*) over () total
from changed
order by source, mapping_id
limit 200;

-- old_vs_new_unexpected_drop
-- Mappings created more than 24 hours ago that are overdue under the current
-- rule and not under the new rule. n should be 0. mapping_ids lists at most 50 ids.
with e as ({{ELIGIBLE}}),
drops as (
  select distinct e.mapping_id
  from e
  join source_card_mappings m on m.id = e.mapping_id
  where m.created_at < now() - interval '24 hours'
    and (e.checked_at is null or e.checked_at < now() - interval '24 hours')
    and not (
      coalesce(e.checked_at, m.created_at) < now() - interval '24 hours'
      or (e.checked_at is null and m.created_at is null)
    )
)
select count(*) n,
  coalesce(
    (select array_agg(mapping_id) from (
      select mapping_id from drops order by mapping_id limit 50
    ) ids),
    array[]::integer[]
  ) mapping_ids
from drops;
