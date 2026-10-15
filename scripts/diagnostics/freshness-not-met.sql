-- Raw refresh items behind deadline_compliance not_met (never successfully checked, or the last
-- successful check older than 24 h), grouped; same population as the state generator's freshness
-- query (session 13 tools/freshness_detail.py).
-- summary
with d as (
  select s.name source, w.state work_state, m.is_active, m.review_status,
    left(regexp_replace(coalesce(w.last_failure, ''), '[0-9]+', 'N', 'g'), 70) failure_class,
    ps.last_successfully_checked_at,
    round(extract(epoch from now() - ps.last_successfully_checked_at) / 3600) age_hours,
    coalesce(w.last_failure_at, w.updated_at) since
  from freshness_price_states ps join freshness_work w on w.id = ps.work_id join sources s on s.id = w.source_id
  left join source_card_mappings m on m.id = w.source_card_mapping_id
  where ps.price_category = 'raw' and w.kind = 'refresh'
    and (ps.last_successfully_checked_at is null or ps.last_successfully_checked_at < now() - interval '24 hours'))
select source, work_state, is_active, review_status, failure_class, count(*) n,
  count(*) filter (where last_successfully_checked_at is null) never_checked,
  min(age_hours) min_age_h, max(age_hours) max_age_h, min(since) since_min, max(since) since_max
from d group by 1, 2, 3, 4, 5 order by 1, 6 desc;

-- not_blocked_deficit
select count(*) n
from freshness_price_states ps join freshness_work w on w.id = ps.work_id
where ps.price_category = 'raw' and w.kind = 'refresh' and w.state <> 'blocked'
  and (ps.last_successfully_checked_at is null or ps.last_successfully_checked_at < now() - interval '24 hours');

-- within_target_nonblocked
select s.name source, count(*) n,
  max(round(extract(epoch from now() - ps.last_successfully_checked_at) / 3600, 1)) max_age_h
from freshness_price_states ps join freshness_work w on w.id = ps.work_id join sources s on s.id = w.source_id
where ps.price_category = 'raw' and w.kind = 'refresh' and w.state <> 'blocked'
group by 1;
