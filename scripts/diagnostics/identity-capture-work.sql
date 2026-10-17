-- Yuyu identity-capture work (scope yuyu-identity:<candidate>:...) written by the #116 enqueue
-- tool: totals by state, the newest 100 work items with their state and attempt outcomes, and
-- outcome totals for the last 24 h, so capture progress, denials and transient failures are
-- readable from the summary. Older items (500+ on staging) stay out of the summary budget.
-- states
select w.state, count(*) n, min(w.id) min_work_id, max(w.id) max_work_id,
  count(*) filter (where w.attempt_count = 0) never_attempted
from freshness_work w join sources s on s.id = w.source_id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%'
group by 1 order by 1;

-- latest_work
select w.id work_id, split_part(w.scope_key, ':', 2) candidate_id, w.state, w.attempt_count,
  w.last_outcome, w.last_attempted_at,
  count(a.id) filter (where a.outcome = 'source_denial') denials,
  count(a.id) filter (where a.outcome = 'transient_failure') transient_failures
from freshness_work w join sources s on s.id = w.source_id
left join freshness_attempts a on a.work_id = w.id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%'
group by w.id order by w.id desc limit 100;

-- outcomes_24h
select a.outcome, count(*) n, count(distinct a.work_id) work_items, max(a.finished_at) last_finished
from freshness_attempts a join freshness_work w on w.id = a.work_id join sources s on s.id = w.source_id
where s.name = 'yuyutei' and w.scope_key like 'yuyu-identity:%' and a.started_at > now() - interval '24 hours'
group by 1 order by 1;
