-- Storage growth by component (owner decision 2026-10-17: plan, do not build, ways to cut growth).
-- Read-only. Byte figures are pg_column_size (stored, after TOAST compression) unless named
-- total_relation; they exclude index and page overhead. Windows are the last 14 UTC days.

-- raw_by_day
with r as (
  select s.name source, date_trunc('day', r.fetched_at) d, r.id, r.source_url, r.content_hash, pg_column_size(r.raw_content) bytes,
    lag(r.content_hash) over (partition by r.source_url order by r.fetched_at, r.id) prev_hash
  from raw_snapshots r join sources s on s.id = r.source_id where r.fetched_at >= now() - interval '15 days')
select r.source, r.d day_utc, count(*) snapshots, sum(r.bytes) stored_bytes,
  count(*) filter (where r.prev_hash = r.content_hash) same_as_previous, sum(r.bytes) filter (where r.prev_hash = r.content_hash) same_bytes,
  count(x.id) encoded, sum(r.bytes) filter (where x.id is not null) encoded_stored_bytes
from r left join raw_snapshot_dictionaries x on x.id = r.id
where r.d >= date_trunc('day', now()) - interval '14 days'
group by 1, 2 order by 1, 2;

-- dictionary_by_day
select date_trunc('day', created_at) day_utc, count(*) encoded, sum(original_bytes) original_bytes, sum(encoded_bytes) encoded_bytes
from raw_snapshot_dictionaries where created_at >= now() - interval '14 days' group by 1 order by 1;

-- observations_by_day
with o as (
  select s.name source, date_trunc('day', o.observed_at) d, o.price_type, pg_column_size(o.*) bytes,
    lag(o.price_jpy) over w prev_price, lag(o.stock_status) over w prev_stock, lag(o.promotion_state) over w prev_promo,
    o.price_jpy, o.stock_status, o.promotion_state
  from price_observations o join sources s on s.id = o.source_id
  where o.observed_at >= now() - interval '15 days'
  window w as (partition by o.source_id, o.source_card_mapping_id, o.card_print_id, o.price_type, o.condition_label order by o.observed_at, o.id))
select source, d day_utc, count(*) observations, sum(bytes) row_bytes,
  count(*) filter (where prev_price = price_jpy and prev_stock is not distinct from stock_status
    and prev_promo is not distinct from promotion_state) unchanged
from o where d >= date_trunc('day', now()) - interval '14 days' group by 1, 2 order by 1, 2;

-- observations_per_item_day
with c as (
  select o.source_id, o.source_card_mapping_id, o.price_type, date_trunc('day', o.observed_at) d, count(*) n
  from price_observations o where o.observed_at >= now() - interval '7 days' group by 1, 2, 3, 4)
select s.name source, price_type, count(*) item_days, sum(n) observations, max(n) max_per_item_day,
  percentile_cont(0.95) within group (order by n) p95_per_item_day
from c join sources s on s.id = c.source_id group by 1, 2 order by 1, 2;

-- table_bytes
select c.relname table_name, pg_total_relation_size(c.oid) total_relation_bytes, pg_relation_size(c.oid) heap_bytes,
  pg_indexes_size(c.oid) index_bytes, c.reltuples::bigint estimated_rows
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
  and c.relname in ('raw_snapshots', 'raw_snapshot_dictionaries', 'price_observations', 'freshness_attempts',
    'freshness_work', 'freshness_price_states', 'app_log_events', 'market_value_points', 'card_print_image_assets')
order by 2 desc;

-- rows_per_day
select 'raw_snapshots' table_name, count(*) rows_7d from raw_snapshots where fetched_at >= now() - interval '7 days'
union all select 'price_observations', count(*) from price_observations where observed_at >= now() - interval '7 days'
union all select 'freshness_attempts', count(*) from freshness_attempts where claimed_at >= now() - interval '7 days'
union all select 'app_log_events', count(*) from app_log_events where created_at >= now() - interval '7 days';

-- raw_age
select s.name source, case when r.fetched_at >= now() - interval '30 days' then '0-30d'
    when r.fetched_at >= now() - interval '90 days' then '31-90d' else 'over-90d' end age,
  count(*) snapshots, min(r.fetched_at) oldest
from raw_snapshots r join sources s on s.id = r.source_id group by 1, 2 order by 1, 2;
