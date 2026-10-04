-- Run only on a freshly resolved, fingerprint-validated staging connection.
-- Read definitions for the 2026-10-04 snapshot; credentials are never stored here.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';

-- as_of
select now() as at, current_setting('transaction_read_only') as read_only;

-- revision
select version_num from alembic_version;

-- coverage
with eligible as (select m.id,m.card_print_id,s.name from source_card_mappings m join sources s on s.id=m.source_id join card_prints p on p.id=m.card_print_id where m.is_active and m.superseded_at is null and m.review_status='approved' and p.is_active and p.verification_status='verified' and s.name in ('yuyutei','snkrdunk') and (s.name!='snkrdunk' or m.manual_verified)), counts as (select p.id,count(distinct e.name) n from card_prints p left join eligible e on e.card_print_id=p.id where p.is_active and p.verification_status='verified' group by p.id) select count(*) canonical_variants,count(*) filter(where n>0) one_or_more_sources,round(100.0*count(*) filter(where n>0)/nullif(count(*),0),4) one_or_more_sources_pct,count(*) filter(where n=2) both_sources,count(*) filter(where n=0) zero_sources from counts;

-- eligible
select s.name,count(*) from source_card_mappings m join sources s on s.id=m.source_id join card_prints p on p.id=m.card_print_id where m.is_active and m.superseded_at is null and m.review_status='approved' and p.is_active and p.verification_status='verified' and s.name in ('yuyutei','snkrdunk') and (s.name!='snkrdunk' or m.manual_verified) group by s.name;

-- duplicates
select count(*) groups from (select m.card_print_id,m.source_id from source_card_mappings m where m.is_active and m.superseded_at is null group by m.card_print_id,m.source_id having count(*)>1) d;

-- budgets
select s.name,b.enabled,b.request_limit,b.window_seconds,b.used_requests,b.reserved_requests,b.paused_until,b.pause_reason from source_dispatch_budgets b join sources s on s.id=b.source_id;

-- work
select s.name,w.kind,w.state,w.policy_version,count(*) from freshness_work w join sources s on s.id=w.source_id group by 1,2,3,4 order by 1,2,3;

-- freshness
select s.name,count(*) total,count(*) filter(where ps.last_successfully_checked_at is null) never_successfully_checked,count(*) filter(where ps.last_successfully_checked_at<now()-interval '24 hours') check_older_than_24h,count(*) filter(where ps.last_valid_price_observed_at<now()-interval '24 hours') price_older_than_24h,count(*) filter(where ps.availability='no_listing') no_listing from freshness_price_states ps join freshness_work w on w.id=ps.work_id join sources s on s.id=w.source_id where ps.price_category='raw' and w.kind='refresh' group by 1;

-- attempts_24h
select s.name,w.kind,a.outcome,count(*) attempts,max(a.finished_at) latest from freshness_attempts a join freshness_work w on w.id=a.work_id join sources s on s.id=w.source_id where a.claimed_at>=now()-interval '24 hours' group by 1,2,3 order by 1,2,3;

-- market_value
select scope_kind,max(point_date) latest_published_date,count(*) filter(where point_date in ('2026-09-27','2026-09-28')) intentional_gap_rows from market_value_points group by 1;

-- receipts
select snapshot_date,receipt_kind,expected_print_count,snapshot_row_count from market_index_snapshot_completions order by snapshot_date desc limit 3;

-- categories
select price_category,price_type,count(*) from freshness_price_states group by 1,2;

-- psa10
select count(*),max(observed_at) latest from price_observations where price_type='psa10_asking';

-- duplicate_detail
select s.name,m.card_print_id,array_agg(m.id order by m.id) mapping_ids,array_agg(m.review_status order by m.id) review_statuses from source_card_mappings m join sources s on s.id=m.source_id where m.is_active and m.superseded_at is null group by s.name,m.card_print_id having count(*)>1;

-- blocked_reasons
select s.name,w.last_failure,w.last_outcome,count(*) from freshness_work w join sources s on s.id=w.source_id where w.state='blocked' group by 1,2,3;

-- mapping_status
select s.name,m.review_status,m.is_active,m.manual_verified,count(*) from source_card_mappings m join sources s on s.id=m.source_id where m.superseded_at is null group by 1,2,3,4 order by 1,2,3,4;

ROLLBACK;
