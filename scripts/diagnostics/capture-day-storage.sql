-- Identity-capture storage breakdown (owner decision 2026-10-17 15:41Z: find exactly which tables
-- and columns make up a capture day). Read-only. Byte figures are pg_column_size (stored, after
-- TOAST compression) and octet_length (the text as stored, before TOAST compression). A capture is
-- a freshness_work discovery intent with resume_cursor.explicit_identity_capture = true; its raw
-- snapshots carry parser_version 'yuyu-identity-evidence-v1' (homepage warm-up, product page,
-- base64 Yuyu-Tei image, base64 official images). Window: the last 8 UTC days.

-- raw_by_parser_day
select s.name source, coalesce(r.parser_version, '(none)') parser_version, date_trunc('day', r.fetched_at) day_utc,
  count(*) snapshots, sum(pg_column_size(r.raw_content)) stored_bytes, sum(octet_length(r.raw_content)) text_bytes,
  count(x.id) encoded
from raw_snapshots r join sources s on s.id = r.source_id left join raw_snapshot_dictionaries x on x.id = r.id
where r.fetched_at >= date_trunc('day', now()) - interval '7 days'
group by 1, 2, 3 order by 3, 1, 2;

-- capture_roles_by_day
with cw as (
  select w.id work_id, w.state, w.resume_cursor::jsonb c, w.last_successfully_checked_at done_at
  from freshness_work w
  where w.kind = 'discovery' and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'explicit_identity_capture' = 'true'),
refs as (
  select (c ->> 'source_product_snapshot_id')::bigint snapshot_id, 'product_page' role, work_id from cw
  where c ->> 'source_product_snapshot_id' is not null
  union all
  select (c ->> 'source_image_snapshot_id')::bigint, 'yuyu_image', work_id from cw
  where c ->> 'source_image_snapshot_id' is not null
  union all
  select (o ->> 'raw_snapshot_id')::bigint, 'official_image', cw.work_id
  from cw cross join lateral jsonb_array_elements(coalesce(cw.c -> 'official_images', '[]'::jsonb)) o),
cap as (
  select r.id, date_trunc('day', r.fetched_at) d, coalesce(refs.role, 'warmup_or_unfinished') role, refs.work_id,
    pg_column_size(r.raw_content) stored_bytes, octet_length(r.raw_content) text_bytes
  from raw_snapshots r left join refs on refs.snapshot_id = r.id
  where r.parser_version = 'yuyu-identity-evidence-v1')
select d day_utc, role, count(*) snapshots, sum(stored_bytes) stored_bytes, sum(text_bytes) text_bytes,
  round(avg(stored_bytes)) avg_stored_bytes, count(distinct work_id) captures
from cap where d >= date_trunc('day', now()) - interval '7 days' group by 1, 2 order by 1, 2;

-- capture_roles_all_time
with cw as (
  select w.id work_id, w.state, w.resume_cursor::jsonb c, w.last_successfully_checked_at done_at
  from freshness_work w
  where w.kind = 'discovery' and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'explicit_identity_capture' = 'true'),
refs as (
  select (c ->> 'source_product_snapshot_id')::bigint snapshot_id, 'product_page' role, work_id from cw
  where c ->> 'source_product_snapshot_id' is not null
  union all
  select (c ->> 'source_image_snapshot_id')::bigint, 'yuyu_image', work_id from cw
  where c ->> 'source_image_snapshot_id' is not null
  union all
  select (o ->> 'raw_snapshot_id')::bigint, 'official_image', cw.work_id
  from cw cross join lateral jsonb_array_elements(coalesce(cw.c -> 'official_images', '[]'::jsonb)) o),
cap as (
  select r.id, date_trunc('day', r.fetched_at) d, coalesce(refs.role, 'warmup_or_unfinished') role, refs.work_id,
    pg_column_size(r.raw_content) stored_bytes, octet_length(r.raw_content) text_bytes
  from raw_snapshots r left join refs on refs.snapshot_id = r.id
  where r.parser_version = 'yuyu-identity-evidence-v1')
select role, count(*) snapshots, sum(stored_bytes) stored_bytes, sum(text_bytes) text_bytes,
  round(avg(stored_bytes)) avg_stored_bytes, max(stored_bytes) max_stored_bytes, min(d) first_day, max(d) last_day
from cap group by 1 order by 3 desc;

-- capture_intents
with cw as (
  select w.id work_id, w.state, w.resume_cursor::jsonb c, w.last_successfully_checked_at done_at
  from freshness_work w
  where w.kind = 'discovery' and w.resume_cursor is not null
    and w.resume_cursor::jsonb ->> 'explicit_identity_capture' = 'true'),
refs as (
  select (c ->> 'source_product_snapshot_id')::bigint snapshot_id, 'product_page' role, work_id from cw
  where c ->> 'source_product_snapshot_id' is not null
  union all
  select (c ->> 'source_image_snapshot_id')::bigint, 'yuyu_image', work_id from cw
  where c ->> 'source_image_snapshot_id' is not null
  union all
  select (o ->> 'raw_snapshot_id')::bigint, 'official_image', cw.work_id
  from cw cross join lateral jsonb_array_elements(coalesce(cw.c -> 'official_images', '[]'::jsonb)) o),
cap as (
  select r.id, date_trunc('day', r.fetched_at) d, coalesce(refs.role, 'warmup_or_unfinished') role, refs.work_id,
    pg_column_size(r.raw_content) stored_bytes, octet_length(r.raw_content) text_bytes
  from raw_snapshots r left join refs on refs.snapshot_id = r.id
  where r.parser_version = 'yuyu-identity-evidence-v1')
select state, date_trunc('day', done_at) done_day, count(*) intents,
  sum(jsonb_array_length(coalesce(c -> 'considered_print_ids', '[]'::jsonb))) considered_prints
from cw group by 1, 2 order by 2 nulls first, 1;

-- other_tables_by_day
select 'freshness_attempts' table_name, date_trunc('day', claimed_at) day_utc, count(*) row_count, sum(pg_column_size(a.*)) row_bytes
from freshness_attempts a where claimed_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'app_log_events', date_trunc('day', created_at), count(*), sum(pg_column_size(e.*))
from app_log_events e where created_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'source_mapping_proposal_groups', date_trunc('day', created_at), count(*), sum(pg_column_size(g.*))
from source_mapping_proposal_groups g where created_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'source_mapping_proposal_alternatives', date_trunc('day', created_at), count(*), sum(pg_column_size(t.*))
from source_mapping_proposal_alternatives t where created_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'market_index_snapshots', date_trunc('day', created_at), count(*), sum(pg_column_size(m.*))
from market_index_snapshots m where created_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'price_observations', date_trunc('day', observed_at), count(*), sum(pg_column_size(o.*))
from price_observations o where observed_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
union all
select 'raw_snapshot_dictionaries', date_trunc('day', created_at), count(*), sum(pg_column_size(x.*))
from raw_snapshot_dictionaries x where created_at >= date_trunc('day', now()) - interval '7 days' group by 1, 2
order by 2, 1;

-- relation_split
select c.relname table_name, pg_relation_size(c.oid) heap_bytes,
  coalesce(pg_relation_size(nullif(c.reltoastrelid, 0)), 0) toast_bytes, pg_indexes_size(c.oid) index_bytes,
  pg_total_relation_size(c.oid) total_bytes
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r' order by 5 desc limit 15;
