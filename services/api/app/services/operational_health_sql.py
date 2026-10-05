"""Read-only authoritative aggregates shared by collectors and state tooling."""

ELIGIBLE = """
select m.id mapping_id, s.name source, m.id % 9 shard, w.id work_id,
 w.state, w.next_due_at, w.retry_not_before_at, w.claim_expires_at,
 ps.last_successfully_checked_at checked_at, ps.consecutive_failures
from source_card_mappings m join sources s on s.id=m.source_id
join card_prints p on p.id=m.card_print_id
left join freshness_work w on w.source_card_mapping_id=m.id and w.kind='refresh'
left join freshness_price_states ps on ps.work_id=w.id and ps.price_category='raw'
where m.is_active and m.superseded_at is null and m.review_status='approved'
and p.is_active and p.verification_status='verified'
and s.name in ('yuyutei','snkrdunk') and (s.name!='snkrdunk' or m.manual_verified)
"""
DUE_SQL = """with e as (""" + ELIGIBLE + """), gaps as (
 select w.source_id, w.source_card_mapping_id, r.fetched_at,
 extract(epoch from r.fetched_at-lag(r.fetched_at) over(partition by a.work_id order by r.fetched_at)) gap
 from freshness_attempts a join freshness_work w on w.id=a.work_id
 join raw_snapshots r on r.id=a.raw_snapshot_id
 where w.kind='refresh' and a.category_outcomes->>'raw' in ('captured','no_listing')
 and r.fetched_at >= now()-interval '7 days'
) select source, case when source='yuyutei' then shard else null end shard,
 count(*) eligible,
 count(*) filter(where checked_at is null or checked_at<=now()-interval '23 hours') due,
 count(*) filter(where checked_at is null or checked_at<now()-interval '24 hours') overdue,
 count(*) filter(where state='claimed') claimed,
 count(*) filter(where retry_not_before_at>now()) backoff,
 count(*) filter(where consecutive_failures>0) retries,
 count(*) filter(where state='blocked') quarantined,
 count(*) filter(where checked_at is null) never_checked,
 count(*) filter(where checked_at>=now()-interval '23 hours') within_23h,
 count(*) filter(where checked_at<now()-interval '23 hours' and checked_at>=now()-interval '24 hours') between_23_24h,
 count(*) filter(where checked_at<now()-interval '24 hours') over_24h,
 count(*) filter(where state='claimed' and claim_expires_at<=now()) expired_claims,
 count(*) filter(where work_id is null) unplanned,
 min(next_due_at) filter(where state='pending' and next_due_at<=now() and (retry_not_before_at is null or retry_not_before_at<=now())) oldest_actionable_due_at,
 percentile_cont(0.5) within group(order by extract(epoch from now()-checked_at)) successful_check_age_p50,
 percentile_cont(0.95) within group(order by extract(epoch from now()-checked_at)) successful_check_age_p95,
 max(extract(epoch from now()-checked_at)) successful_check_age_max,
 max(g.gap) maximum_successful_revisit_gap_seconds
 from e left join (select source_card_mapping_id,max(gap) gap from gaps group by source_card_mapping_id) g on g.source_card_mapping_id=e.mapping_id
 group by source,case when source='yuyutei' then shard else null end
"""
# Run evidence never includes free-text failure reasons, URLs, payloads or claims.
RUN_SQL = """
select count(*) claimed, count(*) filter(where a.started_at is not null) attempted,
 count(*) filter(where a.outcome is null) claims_remaining,
 count(*) filter(where a.outcome='expired') expired_claims,
 coalesce(sum(a.reserved_request_cost) filter(where a.outcome is null),0) reservations_remaining,
 count(*) filter(where a.actual_request_cost>a.reserved_request_cost or
 (select coalesce(sum(value::int),0) from json_array_elements_text(a.request_costs))>a.reserved_request_cost) reservation_overruns,
 count(*) filter(where a.outcome='transient_failure') transient,
 count(*) filter(where a.outcome='identity_refusal') identity,
 count(*) filter(where a.category_outcomes->>'raw'='parsing_failure') parsing,
 count(*) filter(where a.category_outcomes->>'raw'='captured') listed,
 count(*) filter(where a.category_outcomes->>'raw'='no_listing') no_listing,
 count(distinct a.raw_snapshot_id) raw_snapshots,
 count(*) filter(where w.source_id!=:source_id or (cast(:shard as integer) is not null and w.source_card_mapping_id%9!=:shard)) wrong_shard,
 count(*) filter(where a.outcome is not null and a.outcome!='expired' and a.actual_request_cost!=(select coalesce(sum(value::int),0) from json_array_elements_text(a.request_costs))) request_cost_mismatch,
 (select count(*) from price_observations p where p.raw_snapshot_id in (select x.raw_snapshot_id from freshness_attempts x where x.claimed_by=:owner) and p.price_type in ('sell','floor')) accepted_observations,
 (select count(*) from price_observations p where p.raw_snapshot_id in (select x.raw_snapshot_id from freshness_attempts x where x.claimed_by=:owner) and p.promotion_state='sale') promotional_hidden
from freshness_attempts a join freshness_work w on w.id=a.work_id where a.claimed_by=:owner
"""
# At most latest run per service; both start and finish events reconstruct a
# process killed before completion. No unbounded log scan or full history in YAML.
EVENT_SQL = """select context_json from (
 select distinct on (service,event_type) service,context_json,created_at,id from app_log_events
 where event_type in ('raw_execution_started','raw_execution_finished')
 and created_at>=now()-interval '48 hours'
 order by service,event_type,created_at desc,id desc
) r order by created_at desc"""

BUDGET_SQL = """
select s.name,b.enabled,b.request_limit,b.window_seconds,b.window_started_at,
 b.used_requests,b.reserved_requests,b.paused_until,
 (b.paused_until is null and b.pause_reason is not null) permanent_pause,
 coalesce(a.open_reservations,0) open_reservations,
 b.reserved_requests!=coalesce(a.open_reservations,0) reservation_mismatch
from source_dispatch_budgets b join sources s on s.id=b.source_id
left join (select w.source_id,sum(a.reserved_request_cost) open_reservations
 from freshness_attempts a join freshness_work w on w.id=a.work_id
 where a.outcome is null group by w.source_id) a on a.source_id=b.source_id
"""
